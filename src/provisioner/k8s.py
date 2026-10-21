"""Kubernetes REST access for the provisioner (Phase 5, ADR-060).

Plain httpx against the in-cluster API with the pod's ServiceAccount token -
no kubectl dependency. Every namespace operation enforces the
urumi.io/managed-by=provisioner label contract (see slugs.py): ClusterRole RBAC
is cluster-scoped, so the CODE is what keeps the provisioner inside store
namespaces.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
from slugs import (
    CREATED_AT_ANNOTATION,
    DELETING_LABEL,
    FAILURE_ANNOTATION,
    MANAGED_LABEL,
    MANAGED_LABEL_VALUE,
    SLUG_LABEL,
    StoreError,
    is_managed,
    store_namespace,
    validate_slug,
)

logger = logging.getLogger("provisioner.k8s")


class K8sClient:
    def __init__(self):
        host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
        port = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
        self._host = f"https://{host}:{port}"
        self._token = ""
        try:
            with open("/var/run/secrets/kubernetes.io/serviceaccount/token") as fh:
                self._token = fh.read().strip()
        except OSError as exc:  # pragma: no cover - no token in unit tests
            logger.warning("no service account token (%s); API calls will fail", exc)
        self._ca = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        self._client = httpx.AsyncClient(
            base_url=self._host,
            headers={"Authorization": f"Bearer {self._token}"},
            verify=self._ca if self._token else False,
            timeout=30,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str):
        return await self._client.get(path)

    async def _patch(self, path: str, body: dict):
        """RFC 7386 merge patch: an OBJECT body. A null value removes the key
        (how the failure marker is cleared). Never a JSON-Patch array - the
        content type below is merge-patch, and an array body 415s."""
        return await self._client.patch(path, json=body, headers={"Content-Type": "application/merge-patch+json"})

    # ---- generic object apply (Phase 6: hosted servers) --------------------
    # Apply = create if missing, replace-if-changed otherwise. Only used for the
    # four hosted-server kinds inside hosted-<name> namespaces the provisioner
    # itself created (require_managed checked by callers).

    async def apply_object(self, api_version: str, kind: str, ns: str, body: dict) -> None:
        """Create-or-replace a namespaced object by kind path. Only the kinds
        the hosted-server flow needs. Idempotent: an identical existing object
        is a no-op; a changed one is replaced (objects are provisioner-owned).
        Returns nothing; raises StoreError with a status-only reason (the body
        may contain a Secret - never in the message)."""
        paths = {
            ("v1", "Secret"): "/api/v1/namespaces/{ns}/secrets/{name}",
            ("v1", "Service"): "/api/v1/namespaces/{ns}/services/{name}",
            ("v1", "ConfigMap"): "/api/v1/namespaces/{ns}/configmaps/{name}",
            ("apps/v1", "Deployment"): "/apis/apps/v1/namespaces/{ns}/deployments/{name}",
            ("networking.k8s.io/v1", "NetworkPolicy"): "/apis/networking.k8s.io/v1/namespaces/{ns}/networkpolicies/{name}",
        }
        template = paths.get((api_version, kind))
        if template is None:
            raise StoreError(f"unsupported kind {kind}")
        name = body["metadata"]["name"]
        path = template.format(ns=quote(ns), name=quote(name))
        r = await self._client.get(path)
        if r.status_code == 200:
            # replace: the provisioner owns these objects wholesale
            r = await self._client.put(path, json=body)
        else:
            r = await self._client.post(template.format(ns=quote(ns), name="").rsplit("/", 1)[0], json=body)
        if r.status_code not in (200, 201, 409):
            raise StoreError(f"{kind} apply failed: {r.status_code} (details not logged)")

    # ---- namespaces -------------------------------------------------------

    async def namespace_exists(self, ns: str) -> bool:
        r = await self._get(f"/api/v1/namespaces/{quote(ns)}")
        return r.status_code == 200

    async def get_namespace(self, ns: str) -> dict | None:
        r = await self._get(f"/api/v1/namespaces/{quote(ns)}")
        return r.json() if r.status_code == 200 else None

    async def require_managed(self, ns: str) -> dict:
        """The label guard: every operation on an EXISTING namespace asserts the
        managed label first. Raises StoreError (refused) otherwise."""
        obj = await self.get_namespace(ns)
        if obj is None:
            raise StoreError(f"namespace {ns} not found")
        if not is_managed(obj.get("metadata", {}).get("labels")):
            raise StoreError(f"namespace {ns} is not managed by the provisioner")
        return obj

    async def create_store_namespace(self, slug: str) -> dict:
        """Create (idempotently) the store namespace WITH the managed labels."""
        validate_slug(slug)
        ns = store_namespace(slug)
        return await self._create_managed_namespace(ns, slug, "store")

    async def create_hosted_namespace(self, name: str) -> dict:
        """Create (idempotently) the hosted-<name> namespace WITH the managed
        labels (Phase 6, ADR-062). Same adoption resistance as stores."""
        validate_slug(name)
        ns = f"hosted-{name}"
        return await self._create_managed_namespace(ns, name, "hosted")

    async def _create_managed_namespace(self, ns: str, slug: str, kind: str) -> dict:
        """Create (idempotently) a managed namespace. The slug label carries the
        store/hosted name so reconcile can map namespace -> entity."""
        existing = await self.get_namespace(ns)
        if existing is not None:
            # only continue when it is one of ours
            await self.require_managed(ns)
            return existing
        body = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": ns,
                "labels": {
                    MANAGED_LABEL: MANAGED_LABEL_VALUE,
                    SLUG_LABEL: slug,
                    "app.kubernetes.io/managed-by": "provisioner",
                },
                "annotations": {CREATED_AT_ANNOTATION: datetime.now(UTC).isoformat()},
            },
        }
        r = await self._client.post("/api/v1/namespaces", json=body)
        if r.status_code not in (200, 201, 409):
            raise StoreError(f"namespace create failed: {r.status_code} (details not logged)")
        return await self.get_namespace(ns) or body

    async def label_deleting(self, slug: str) -> None:
        ns = store_namespace(slug)
        await self.require_managed(ns)
        r = await self._patch(
            f"/api/v1/namespaces/{quote(ns)}",
            {"metadata": {"labels": {DELETING_LABEL: "true"}}},
        )
        if r.status_code not in (200, 201):
            raise StoreError(f"could not mark {ns} deleting: {r.status_code}")

    async def delete_store_namespace(self, slug: str) -> None:
        """Delete the namespace (cascades PVCs, Secrets, Ingress, everything).
        Refuses anything not managed by the provisioner."""
        ns = store_namespace(slug)
        await self.require_managed(ns)
        r = await self._client.delete(f"/api/v1/namespaces/{quote(ns)}")
        if r.status_code not in (200, 202, 404):
            raise StoreError(f"namespace delete failed: {r.status_code}")

    async def list_managed_namespaces(self) -> list[dict]:
        """Namespaces carrying the managed label (list is label-filtered, so we
        never even LOOK at foreign namespaces)."""
        r = await self._get(f"/api/v1/namespaces?labelSelector={MANAGED_LABEL}%3D{MANAGED_LABEL_VALUE}")
        if r.status_code != 200:
            logger.warning("namespace list failed: %s", r.status_code)
            return []
        return r.json().get("items", [])

    # ---- derived store state ---------------------------------------------

    async def namespace_created_at(self, ns_obj: dict) -> datetime | None:
        ann = ns_obj.get("metadata", {}).get("annotations", {}) or {}
        raw = ann.get(CREATED_AT_ANNOTATION) or ns_obj.get("metadata", {}).get("creationTimestamp")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None

    async def deployment_ready(self, ns: str, name: str) -> bool:
        r = await self._get(f"/apis/apps/v1/namespaces/{quote(ns)}/deployments/{quote(name)}")
        if r.status_code != 200:
            return False
        return bool(r.json().get("status", {}).get("conditions") and any(
            c.get("type") == "Available" and c.get("status") == "True" for c in r.json()["status"]["conditions"]
        ))

    async def store_slug_for_namespace(self, ns_obj: dict) -> str | None:
        labels = ns_obj.get("metadata", {}).get("labels", {}) or {}
        return labels.get(SLUG_LABEL)

    async def namespace_is_deleting(self, ns_obj: dict) -> bool:
        labels = ns_obj.get("metadata", {}).get("labels", {}) or {}
        return labels.get(DELETING_LABEL) == "true"

    async def reset_provision_clock(self, slug: str) -> None:
        """Restart the provisioning budget for a NEW attempt (the gateway's
        retry endpoint). Without this, a store that timed out once is instantly
        re-failed by store_state's namespace-age check even while a fresh,
        healthy attempt is running."""
        ns = store_namespace(slug)
        await self.require_managed(ns)
        r = await self._patch(
            f"/api/v1/namespaces/{quote(ns)}",
            {"metadata": {"annotations": {CREATED_AT_ANNOTATION: datetime.now(UTC).isoformat()}}},
        )
        if r.status_code not in (200, 201):
            raise StoreError(f"could not reset {ns} provisioning clock: {r.status_code}")

    # ---- provisioning failure marker ---------------------------------------
    # helm failures are recorded on the NAMESPACE (the cluster is the state, so
    # the marker survives provisioner restarts) and reported by store_state as
    # phase=failed without waiting out the provisioning budget. The reason is
    # helm's sanitized tail (no secret ever appears in it: the chart generates
    # its own credentials via randAlphaNum and helm errors quote values only
    # from --set, which carries hosts/images only).

    async def annotate_provision_failure(self, slug: str, reason: str) -> None:
        ns = store_namespace(slug)
        await self.require_managed(ns)
        r = await self._patch(
            f"/api/v1/namespaces/{quote(ns)}",
            {"metadata": {"annotations": {FAILURE_ANNOTATION: reason[:200]}}},
        )
        if r.status_code not in (200, 201):
            raise StoreError(f"could not mark {ns} failed: {r.status_code}")

    async def clear_provision_failure(self, slug: str) -> None:
        ns = store_namespace(slug)
        await self.require_managed(ns)
        r = await self._patch(
            f"/api/v1/namespaces/{quote(ns)}",
            {"metadata": {"annotations": {FAILURE_ANNOTATION: None}}},
        )
        if r.status_code not in (200, 201):
            raise StoreError(f"could not clear {ns} failure marker: {r.status_code}")

    async def provision_failure_reason(self, ns_obj: dict) -> str | None:
        ann = ns_obj.get("metadata", {}).get("annotations", {}) or {}
        return ann.get(FAILURE_ANNOTATION)


def dump_for_log(obj) -> str:
    """Compact JSON for logs; never called with secrets (the provisioner only
    logs namespace names, phases and reasons)."""
    try:
        return json.dumps(obj, default=str)[:200]
    except Exception:
        return "<unserializable>"
