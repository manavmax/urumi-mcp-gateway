"""Provisioning tasks: helm install/ uninstall driving, task manager, reconcile.

Design (ADR-060):
- The CLUSTER is the state: a store exists iff its labeled namespace exists;
  it is ready iff the helm release deployed AND the WordPress Deployment is
  Available; it is deleting iff the namespace carries the deleting label.
  The task manager keeps NO persistent state, so a provisioner restart loses
  nothing: the reconcile loop re-derives in-flight work from the cluster.
- Idempotent by construction: `helm upgrade --install` with deterministic
  release/namespace names is safe to re-run; re-driving a half-installed
  store finishes it. Teardown deletes the namespace (cascades everything).
- Bounded concurrency (stores.maxConcurrent, default 2) protects the node.
- The overall provisioning budget (stores.provisionTimeoutSeconds) is enforced
  by the status derivation: past the deadline a not-ready store reports
  failed(reason=timeout) and stops being re-driven.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from config import get_settings
from slugs import StoreError, store_namespace, validate_slug

logger = logging.getLogger("provisioner.tasks")


def t_done(t: asyncio.Task) -> bool:
    """asyncio.Task.done() via a module function so unit tests can fake tasks."""
    return t.done()


def _safe_reason(tail: str) -> str:
    """A short human reason for the failure annotation. Helm failure output can
    contain huge resource diffs (JSON/YAML blocks): keep only real error lines
    and never more than 200 chars. No secret can appear in them - the chart
    generates its own credentials via randAlphaNum and helm errors quote only
    --set values (hosts and image repos)."""
    for line in tail.splitlines():
        s = line.strip()
        if s.startswith(("Error:", "UPGRADE FAILED", "INSTALLATION FAILED", "Rollback was")):
            return s[:200]
    # no recognizable error line: a generic reason instead of a JSON/YAML dump
    return "helm release install failed (see provisioner logs)"


class HelmRunner:
    """Thin async wrapper around the helm CLI (baked into the image with the
    store chart at /charts/store). The kubeconfig is written once from the
    pod's ServiceAccount; helm output is sanitized to the last lines only -
    helm never sees a secret, and neither do the logs."""

    def __init__(self):
        self._kubeconfig_written = False

    async def _ensure_kubeconfig(self) -> None:
        if self._kubeconfig_written:
            return
        s = get_settings()
        host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
        port = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
        try:
            with open("/var/run/secrets/kubernetes.io/serviceaccount/token") as fh:
                token = fh.read().strip()
        except OSError as exc:
            raise StoreError("service account token missing") from exc
        cfg = f"""apiVersion: v1
kind: Config
clusters:
- name: incluster
  cluster:
    server: https://{host}:{port}
    certificate-authority: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
users:
- name: provisioner
  user:
    token: {token}
contexts:
- name: incluster
  context:
    cluster: incluster
    user: provisioner
current-context: incluster
"""
        with open(s.kubeconfig_path, "w") as fh:
            fh.write(cfg)
        os.chmod(s.kubeconfig_path, 0o600)
        self._kubeconfig_written = True

    async def _run(self, *args: str, timeout: float, full: bool = False) -> tuple[int, str]:
        s = get_settings()
        await self._ensure_kubeconfig()
        env = dict(os.environ)
        env["KUBECONFIG"] = s.kubeconfig_path
        env["HELM_KUBEAPISERVER"] = ""  # never leak the API URL in errors
        proc = await asyncio.create_subprocess_exec(
            "helm", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            return 124, "helm timed out"
        text = out.decode(errors="replace")
        if full:
            # callers that PARSE the output (helm status --output json) need it
            # all; pretty JSON is multi-line so the tail truncation would break it
            return proc.returncode or 0, text.strip()
        # keep only the tail: reason lines for failures, never full logs
        tail = "\n".join(text.strip().splitlines()[-4:])
        return proc.returncode or 0, tail

    async def install_store(self, slug: str, *, redrive: bool = False) -> str:
        """`helm upgrade --install <slug> /charts/store -n store-<slug>`.
        Deterministic names make re-runs safe. Returns a sanitized reason (''
        on success).

        NO --wait/--atomic: the store chart's post-install hook (wp-setup)
        creates the woo-secrets Secret that woo-mcp needs to START, so waiting
        for every Deployment to be Ready can never converge on a first install
        (the main chart's documented first-install gotcha). Readiness is
        instead derived from the CLUSTER by TaskManager.store_state. `redrive`
        (a release exists but is not deployed: pending/failed) uninstalls the
        broken release first and reinstalls fresh."""
        validate_slug(slug)
        ns = store_namespace(slug)
        release = slug
        s = get_settings()
        args = [
            "upgrade", "--install", release, s.chart_dir,
            "--namespace", ns,
            # deterministic resource names <slug>-wordpress/-woo-mcp/-mariadb:
            # the store chart's fullname helper would otherwise append the chart
            # name (gate-alpha-urumi-store-wordpress), which the readiness
            # derivation and the gateway's woo-mcp URL do not match
            "--set", f"fullnameOverride={slug}",
            "--set", f"ingress.hosts.store={slug}.{s.base_domain}",
            "--set", f"gatewayNamespace={s.gateway_namespace}",
            "--set", f"global.ingressClass={s.ingress_class}",
            "--set", f"global.storageClass={s.storage_class}",
            "--set", f"global.nodeCIDR={s.node_cidr}",
            # same images as the main release (repos/tags forwarded by the chart)
            "--set", f"wordpress.image.repository={s.store_image_wordpress_repo}",
            "--set", f"wordpress.image.tag={s.store_image_wordpress_tag}",
            "--set", f"wooMcp.image.repository={s.store_image_woo_mcp_repo}",
            "--set", f"wooMcp.image.tag={s.store_image_woo_mcp_tag}",
            "--set", f"wpSetup.image.repository={s.store_image_wp_cli_repo}",
            "--set", f"wpSetup.image.tag={s.store_image_wp_cli_tag}",
            "--set", f"storeAssets.image.repository={s.store_image_assets_repo}",
            "--set", f"storeAssets.image.tag={s.store_image_assets_tag}",
            "--set", f"mariadb.image.repository={s.store_image_mariadb_repo}",
            "--set", f"mariadb.image.tag={s.store_image_mariadb_tag}",
        ]
        if redrive:
            # a pending/failed release cannot be upgraded over reliably (--force
            # replaces objects and PVC specs are immutable: "failed to replace
            # object: PersistentVolumeClaim ... spec is immutable"). Instead of
            # --force, uninstall the broken release first - deterministic names
            # make the reinstall identical; the chart's PVCs carry
            # helm.sh/resource-policy: keep so their data survives, and the
            # fresh install re-adopts the same PVCs.
            with contextlib.suppress(StoreError):
                await self.uninstall_store(slug)
        # --timeout applies to HOOK jobs too (helm waits for the wp-setup hook
        # even without --wait; on this loaded laptop node the WooCommerce
        # install needs several minutes - helm's 5m default timed out and
        # marked the release failed while the job was still succeeding)
        args += ["--timeout", s.helm_timeout]
        rc, tail = await self._run(*args, timeout=float(s.provision_timeout_seconds) + 60)
        if rc != 0:
            logger.warning("helm install rc=%s for %s tail=%s", rc, slug, tail)
        return "" if rc == 0 else _safe_reason(tail)

    async def uninstall_store(self, slug: str) -> str:
        validate_slug(slug)
        ns = store_namespace(slug)
        release = slug
        rc, tail = await self._run(
            "uninstall", release, "--namespace", ns, "--wait", "--timeout", "3m",
            timeout=240,
        )
        # 'not found' is success for teardown
        if rc != 0 and "release: not found" not in tail.lower():
            logger.warning("helm uninstall rc=%s for %s tail=%s", rc, slug, tail)
            return tail
        return ""

    async def release_deployed(self, slug: str) -> bool:
        validate_slug(slug)
        rc, out = await self._run(
            "status", slug, "--namespace", store_namespace(slug), "--output", "json",
            timeout=60, full=True,
        )
        if rc != 0:
            return False
        try:
            import json

            return json.loads(out).get("info", {}).get("status") == "deployed"
        except Exception:
            return False

    async def release_status(self, slug: str) -> str | None:
        """The helm release status string, or None when no release exists."""
        validate_slug(slug)
        rc, out = await self._run(
            "status", slug, "--namespace", store_namespace(slug), "--output", "json",
            timeout=60, full=True,
        )
        if rc != 0:
            return None
        try:
            import json

            return json.loads(out).get("info", {}).get("status")
        except Exception:
            return None


class TaskManager:
    """In-flight provisioning/deprovisioning tasks + the reconcile loop."""

    def __init__(self, k8s, helm: HelmRunner):
        self.k8s = k8s
        self.helm = helm
        self._tasks: dict[str, asyncio.Task] = {}
        self._semaphore: asyncio.Semaphore | None = None

    def _gate(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(get_settings().max_concurrent)
        return self._semaphore

    # ---- task lifecycle ---------------------------------------------------

    def start_provision(self, slug: str, *, reset_clock: bool = False) -> None:
        validate_slug(slug)
        if slug in self._tasks and not self._tasks[slug].done():
            return  # idempotent: already driving
        self._tasks[slug] = asyncio.create_task(self._provision(slug, reset_clock=reset_clock))

    def start_deprovision(self, slug: str) -> None:
        validate_slug(slug)
        if slug in self._tasks and not self._tasks[slug].done():
            self._tasks[slug].cancel()
        self._tasks[slug] = asyncio.create_task(self._deprovision(slug))

    async def _provision(self, slug: str, *, reset_clock: bool = False) -> None:
        gate = self._gate()
        try:
            async with gate:
                # label guard: create refuses to adopt foreign namespaces
                await self.k8s.create_store_namespace(slug)
                # a fresh attempt clears any previous failure marker first (the
                # gateway's retry endpoint is what re-drives a Failed store)
                with contextlib.suppress(StoreError):
                    await self.k8s.clear_provision_failure(slug)
                if reset_clock:
                    # ADR-060: the provisioning budget is PER ATTEMPT - a retry
                    # restarts the clock, reconcile resumes keep the original
                    with contextlib.suppress(StoreError):
                        await self.k8s.reset_provision_clock(slug)
                reason = await self.helm.install_store(
                    slug, redrive=await self._needs_redrive(slug),
                )
                if reason:
                    # fail FAST (no 600s timeout wait): mark the namespace and
                    # let store_state report the reason to the gateway
                    with contextlib.suppress(StoreError):
                        await self.k8s.annotate_provision_failure(slug, reason)
                    logger.warning("provision failed for %s: %s", slug, reason)
                else:
                    logger.info("store %s helm release deployed", slug)
        except StoreError as exc:
            logger.warning("provision refused for %s: %s", slug, exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("provision task error for %s: %s", slug, exc)

    async def _needs_redrive(self, slug: str) -> bool:
        """True when a release exists but is not deployed (pending/failed):
        such a release is uninstalled and reinstalled fresh (see install_store)."""
        status = await self.helm.release_status(slug)
        return status is not None and status != "deployed"

    async def _deprovision(self, slug: str) -> None:
        gate = self._gate()
        try:
            async with gate:
                # the DELETING LABEL goes on FIRST - it is the intent marker.
                # Labeled before the uninstall, a crash mid-teardown leaves a
                # namespace reconcile correctly RESUMES DELETING instead of
                # resurrecting a store the user asked to delete (the label is
                # what makes store_state report phase=deleting).
                try:
                    await self.k8s.label_deleting(slug)
                except StoreError as exc:
                    logger.warning("deprovision refused for %s: %s", slug, exc)
                    return
                # a missing release is fine: the namespace delete is what counts
                with contextlib.suppress(StoreError):
                    await self.helm.uninstall_store(slug)
                await self.k8s.delete_store_namespace(slug)
                logger.info("store %s deleted (namespace teardown started)", slug)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover
            logger.exception("deprovision task error for %s: %s", slug, exc)

    # ---- derived state (the status the gateway polls) -----------------------

    async def store_state(self, slug: str) -> dict:
        """Derive {phase, reason} from the cluster. Phases: provisioning,
        ready, failed, deleting, gone."""
        validate_slug(slug)
        s = get_settings()
        ns = store_namespace(slug)
        ns_obj = await self.k8s.get_namespace(ns)
        if ns_obj is None:
            # no namespace YET: with a concurrency gate, a queued task (waiting
            # for the semaphore) has not created it yet - that is still
            # "provisioning", NOT "lost" (the gateway would otherwise mark the
            # store Failed while its turn simply has not come)
            task = self._tasks.get(slug)
            if task is not None and not t_done(task):
                return {"phase": "provisioning", "reason": ""}
            return {"phase": "gone", "reason": ""}
        from slugs import is_managed

        if not is_managed(ns_obj.get("metadata", {}).get("labels")):
            # exists but not ours: refuse to even report on it
            raise StoreError(f"namespace {ns} is not managed by the provisioner")
        if await self.k8s.namespace_is_deleting(ns_obj):
            return {"phase": "deleting", "reason": ""}
        # a helm failure is recorded on the namespace immediately (fail fast);
        # the gateway's retry endpoint clears it by re-driving the install
        failure = await self.k8s.provision_failure_reason(ns_obj)
        if failure:
            return {"phase": "failed", "reason": failure}
        deployed = await self.helm.release_deployed(slug)
        # "ready" means the STOREFRONT and the MCP bridge both serve: WordPress
        # Available AND woo-mcp Available. woo-mcp only starts AFTER the
        # post-install wp-setup hook created its woo-secrets, so this check is
        # also what makes a no---wait first install honest.
        wp_ready = deployed and await self.k8s.deployment_ready(ns, f"{slug}-wordpress")
        mcp_ready = deployed and await self.k8s.deployment_ready(ns, f"{slug}-woo-mcp")
        if wp_ready and mcp_ready:
            return {"phase": "ready", "reason": ""}
        created = await self.k8s.namespace_created_at(ns_obj)
        if created is not None:
            from datetime import UTC, datetime

            age = (datetime.now(UTC) - created).total_seconds()
            if age > s.provision_timeout_seconds:
                return {"phase": "failed", "reason": f"provisioning timed out after {s.provision_timeout_seconds}s"}
        return {"phase": "provisioning", "reason": ""}

    # ---- reconcile ---------------------------------------------------------

    async def reconcile_once(self) -> None:
        """Resume or fail stores stuck after a provisioner restart, and re-drive
        teardowns that never finished."""
        namespaces = await self.k8s.list_managed_namespaces()
        for ns_obj in namespaces:
            slug = await self.k8s.store_slug_for_namespace(ns_obj)
            if not slug:
                continue
            try:
                validate_slug(slug)
            except StoreError:
                logger.warning("reconcile: namespace %s has an invalid store slug; ignoring", ns_obj["metadata"]["name"])
                continue
            state = await self.store_state(slug)
            phase = state["phase"]
            if phase == "deleting":
                if slug not in self._tasks or self._tasks[slug].done():
                    self.start_deprovision(slug)
                continue
            # re-drive (idempotent helm) unless another task is running
            if phase == "provisioning" and (slug not in self._tasks or self._tasks[slug].done()):
                logger.info("reconcile: resuming provisioning of %s", slug)
                self.start_provision(slug)

    async def reconcile_loop(self) -> None:
        s = get_settings()
        while True:
            try:
                await self.reconcile_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("reconcile pass failed: %s", exc)
            await asyncio.sleep(s.reconcile_interval_seconds)
