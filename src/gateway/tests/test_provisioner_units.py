"""Provisioner unit tests (Phase 5, ADR-060): slug rules + the label contract.

The cluster interactions are exercised live in the phase-5 gate; these pin the
SAFETY-CRITICAL invariants that are pure logic:
  - slug validation (DNS-1123 shape, reserved names, no -- and no store- prefix)
  - namespace naming
  - the label guard: K8sClient.require_managed refuses foreign namespaces
    (tested against a faked namespace object - no cluster needed)
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "provisioner"))

from slugs import (
    StoreError,
    is_managed,
    slug_from_display_name,
    store_namespace,
    validate_slug,
)


def _load_provisioner_config():
    """The provisioner's config.py is ALSO named `config` (collides with the
    gateway's config module already in sys.modules): load it by path under a
    unique module name."""
    import importlib.util

    cfg_path = Path(__file__).resolve().parents[2] / "provisioner" / "config.py"
    spec = importlib.util.spec_from_file_location("urumi_provisioner_config", cfg_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validate_slug_accepts_good_slugs():
    assert validate_slug("alpha") == "alpha"
    assert validate_slug("bangalore-branch") == "bangalore-branch"
    assert validate_slug("s2") == "s2"


def test_validate_slug_rejects_bad_shape():
    for bad in ("", "-alpha", "alpha-", "UPPER", "a" * 31, "two--hyphens", "sp ace", "st/ash", "store-alpha"):
        with pytest.raises(StoreError):
            validate_slug(bad)


def test_validate_slug_rejects_reserved():
    for slug in ("woo", "gateway", "kubernetes", "provisioner", "admin"):
        with pytest.raises(StoreError, match="reserved"):
            validate_slug(slug)


def test_slug_from_display_name():
    assert slug_from_display_name("Bangalore Branch!") == "bangalore-branch"
    assert slug_from_display_name("  --Weird Name--  ") == "weird-name"
    assert slug_from_display_name("Über store") == "ber-store"


def test_store_namespace_prefix():
    assert store_namespace("alpha") == "store-alpha"
    with pytest.raises(StoreError):
        store_namespace("woo")


def test_is_managed_label_contract():
    assert is_managed({"urumi.io/managed-by": "provisioner"})
    assert not is_managed({})
    assert not is_managed({"urumi.io/managed-by": "someone-else"})
    assert not is_managed(None)


@pytest.mark.asyncio
async def test_require_managed_refuses_foreign_namespace(monkeypatch):
    """The code-level label guard: an EXISTING namespace without the managed
    label must be refused, whatever it is (this is the documented mitigation
    for the cluster-scoped ClusterRole)."""
    import k8s

    class FakeK8s(k8s.K8sClient):
        def __init__(self, ns_obj):
            self._ns_obj = ns_obj

        async def get_namespace(self, ns):
            return self._ns_obj

    foreign = {"metadata": {"name": "kube-system", "labels": {"kubernetes.io/metadata.name": "kube-system"}}}
    client = FakeK8s(foreign)
    with pytest.raises(StoreError, match="not managed"):
        await client.require_managed("kube-system")

    ours = {"metadata": {"name": "store-alpha", "labels": {"urumi.io/managed-by": "provisioner"}}}
    client2 = FakeK8s(ours)
    assert await client2.require_managed("store-alpha") is ours

    class Fake404(k8s.K8sClient):
        async def get_namespace(self, ns):
            return None

    with pytest.raises(StoreError, match="not found"):
        await Fake404().require_managed("store-alpha")


@pytest.mark.asyncio
async def test_create_store_namespace_refuses_foreign_existing(monkeypatch):
    """Adoption resistance: an existing namespace WITHOUT the label is never
    adopted as a store namespace, even on the create path."""
    import k8s

    class FakeK8s(k8s.K8sClient):
        def __init__(self, ns_obj):
            self._ns_obj = ns_obj
            self.posts = 0

        async def get_namespace(self, ns):
            return self._ns_obj

        async def _client_post(self, path, json=None):
            raise AssertionError("create must never POST when a foreign namespace exists")

    foreign = {"metadata": {"name": "store-beta", "labels": {"team": "other"}}}
    client = FakeK8s(foreign)
    with pytest.raises(StoreError, match="not managed"):
        await client.create_store_namespace("beta")


# ---- provisioning failure marker + image plumbing -------------------------

@pytest.mark.asyncio
async def test_provision_failure_reason_from_namespace():
    """The fail-fast marker lives in the namespace annotations (the cluster is
    the state; it survives provisioner restarts)."""
    import k8s

    client = k8s.K8sClient.__new__(k8s.K8sClient)  # no SA token needed for this
    marked = {"metadata": {"annotations": {"urumi.io/provision-failure": "helm timed out"}}}
    assert await client.provision_failure_reason(marked) == "helm timed out"
    clean = {"metadata": {"annotations": {"other": "x"}}}
    assert await client.provision_failure_reason(clean) is None
    assert await client.provision_failure_reason({"metadata": {}}) is None


def test_store_image_env_forwarded(monkeypatch):
    """The main chart forwards its RESOLVED image repos as env (values-local
    rewrites repos to node-local urumi/...; prod keeps ghcr.io/...) and
    pydantic-settings reads the exact names the chart sets."""
    prov_config = _load_provisioner_config()
    monkeypatch.setenv("STORE_IMAGE_WORDPRESS_REPO", "urumi/wordpress")
    monkeypatch.setenv("STORE_IMAGE_WOO_MCP_REPO", "urumi/woo-mcp")
    monkeypatch.setenv("STORE_IMAGE_MARIADB_TAG", "11.7")
    s = prov_config.Settings()
    assert s.store_image_wordpress_repo == "urumi/wordpress"
    assert s.store_image_woo_mcp_repo == "urumi/woo-mcp"
    assert s.store_image_mariadb_tag == "11.7"


def test_store_image_defaults_match_chart():
    prov_config = _load_provisioner_config()
    s = prov_config.Settings()
    assert s.store_image_wordpress_repo == "ghcr.io/urumi/wordpress"
    assert s.store_image_woo_mcp_repo == "ghcr.io/urumi/woo-mcp"
    assert s.store_image_mariadb_repo == "mariadb"


def test_store_tls_env_forwarded(monkeypatch):
    """Per-store TLS (ADR-064): stores.tls.* from the MAIN release travel to
    the provisioner as STORE_TLS_* env and on to every store release
    (global.tlsEnabled + ingress.clusterIssuer). Default off/empty."""
    prov_config = _load_provisioner_config()
    monkeypatch.setenv("STORE_TLS_ENABLED", "true")
    monkeypatch.setenv("STORE_TLS_CLUSTER_ISSUER", "letsencrypt-prod")
    s = prov_config.Settings()
    assert s.store_tls_enabled is True
    assert s.store_tls_cluster_issuer == "letsencrypt-prod"
    # pydantic parses the chart's quoted Go booleans ("true"/"false")
    monkeypatch.setenv("STORE_TLS_ENABLED", "false")
    assert prov_config.Settings().store_tls_enabled is False
    # no env at all: off/empty (committed values default)
    monkeypatch.delenv("STORE_TLS_ENABLED", raising=False)
    monkeypatch.delenv("STORE_TLS_CLUSTER_ISSUER", raising=False)
    s2 = prov_config.Settings()
    assert s2.store_tls_enabled is False
    assert s2.store_tls_cluster_issuer == ""


# ---- Phase 6 (ADR-062): hosted servers -------------------------------------

def _load_provisioner_hosted():
    """The provisioner's hosted.py collides with the GATEWAY's hosted package
    (both named `hosted`): load by path under a unique module name."""
    import importlib.util

    p = Path(__file__).resolve().parents[2] / "provisioner" / "hosted.py"
    spec = importlib.util.spec_from_file_location("urumi_provisioner_hosted", p)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hosted_validate_image_rules():
    """Tag/digest REQUIRED; :latest and bare names refused; registry paths pass."""
    hosted = _load_provisioner_hosted()

    assert hosted.validate_image("ghcr.io/urumi/demo-mcp-time:0.1.0")
    assert hosted.validate_image("urumi/demo-mcp-time:0.1.0")
    assert hosted.validate_image("r.io/x@sha256:" + "a" * 12)
    for bad in ("demo-mcp-time:0.1.0", "ghcr.io/x", "ghcr.io/x:latest", "", "x" * 300):
        with pytest.raises(hosted.HostedImageError):
            hosted.validate_image(bad)


def test_hosted_namespace_naming():
    hosted = _load_provisioner_hosted()

    assert hosted.hosted_namespace("time2") == "hosted-time2"
    with pytest.raises(StoreError):
        hosted.hosted_namespace("Bad_Name")


def test_hosted_build_objects_shape(monkeypatch):
    """The generated objects carry the safety contract: non-root, read-only
    rootfs, NO SA token, capped resources, gateway-only ingress, DNS-only egress,
    env via secretKeyRef (values only in the Secret)."""
    hosted = _load_provisioner_hosted()

    class S:
        gateway_namespace = "urumi"
        hosted_cpu_request = "30m"
        hosted_memory_request = "64Mi"
        hosted_cpu_limit = "200m"
        hosted_memory_limit = "256Mi"

    monkeypatch.setattr(hosted, "get_settings", lambda: S(), raising=True)
    objs = hosted.build_objects("time2", "hosted-time2", "ghcr.io/urumi/demo-mcp-time:0.1.0", 8000,
                                {"TOKEN": "sekrit"})
    kinds = [(o["kind"], o["metadata"]["name"]) for o in objs]
    assert ("NetworkPolicy", "default-deny") in kinds
    assert ("NetworkPolicy", "allow-gateway") in kinds
    assert ("Secret", "time2-env") in kinds
    assert ("Service", "time2") in kinds
    assert ("Deployment", "time2") in kinds
    dep = next(o for o in objs if o["kind"] == "Deployment")
    spec = dep["spec"]["template"]["spec"]
    assert spec["automountServiceAccountToken"] is False
    assert spec["containers"][0]["securityContext"]["runAsNonRoot"] is True
    assert spec["containers"][0]["securityContext"]["readOnlyRootFilesystem"] is True
    assert spec["containers"][0]["securityContext"]["allowPrivilegeEscalation"] is False
    res = spec["containers"][0]["resources"]
    assert res["limits"] == {"cpu": "200m", "memory": "256Mi"}
    # env values ONLY in the Secret; the Deployment references the keys
    secret = next(o for o in objs if o["kind"] == "Secret")
    assert secret["stringData"] == {"TOKEN": "sekrit"}
    env_ref = spec["containers"][0]["env"][0]
    assert env_ref["valueFrom"]["secretKeyRef"]["key"] == "TOKEN"
    # the Deployment spec must not carry the VALUE itself
    import json as _json

    assert "sekrit" not in _json.dumps(dep)


# ---- reconcile: hosted namespaces are never treated as stores ---------------

def _load_provisioner_tasks():
    """Load the provisioner's tasks.py by path under a unique module name: its
    `from config import get_settings` must resolve against whatever `config`
    is in sys.modules (the gateway's, in this test tree)."""
    import importlib.util

    p = Path(__file__).resolve().parents[2] / "provisioner" / "tasks.py"
    spec = importlib.util.spec_from_file_location("urumi_provisioner_tasks", p)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_reconcile_skips_hosted_namespaces(monkeypatch):
    """The store reconcile loop lists namespaces labeled
    urumi.io/managed-by=provisioner - which ALSO matches hosted-<name>. Before
    the fix every cycle GETs namespaces/store-<hosted-name> (a guaranteed 404)
    and would even re-drive a store install under a hosted name. The loop must
    skip hosted namespaces entirely while still processing stores."""
    import k8s as prov_k8s

    tasks_mod = _load_provisioner_tasks()

    from datetime import UTC, datetime

    hosted_ns = {"metadata": {"name": "hosted-weather",
                              "labels": {"urumi.io/managed-by": "provisioner", "urumi.io/store-slug": "weather"}}}
    store_ns = {"metadata": {"name": "store-alpha",
                             "labels": {"urumi.io/managed-by": "provisioner", "urumi.io/store-slug": "alpha"},
                             "annotations": {"urumi.io/created-at": datetime.now(UTC).isoformat()}}}

    class FakeK8s(prov_k8s.K8sClient):
        def __init__(self):
            self.get_namespace_calls: list[str] = []

        async def list_managed_namespaces(self):
            return [hosted_ns, store_ns]

        async def get_namespace(self, ns):
            self.get_namespace_calls.append(ns)
            for o in (hosted_ns, store_ns):
                if o["metadata"]["name"] == ns:
                    return o
            return None

    class FakeHelm:
        async def release_deployed(self, slug):
            return False

        async def release_status(self, slug):
            return None

    fake_k8s = FakeK8s()
    manager = tasks_mod.TaskManager(fake_k8s, FakeHelm())
    started: list[tuple[str, str]] = []
    monkeypatch.setattr(manager, "start_provision", lambda slug: started.append(("provision", slug)))
    monkeypatch.setattr(manager, "start_deprovision", lambda slug: started.append(("deprovision", slug)))
    # store_state reads the PROVISIONER settings; the gateway config in
    # sys.modules has no provision_timeout_seconds, so stub the module's accessor
    monkeypatch.setattr(tasks_mod, "get_settings",
                        lambda: SimpleNamespace(provision_timeout_seconds=600, max_concurrent=2))

    await manager.reconcile_once()

    # the hosted namespace was skipped BEFORE any store-<name> lookup: the only
    # GET is the real store's namespace, and no task was started for "weather"
    assert "store-weather" not in manager.k8s.get_namespace_calls, manager.k8s.get_namespace_calls
    # and the store was still processed (provisioning resumed)
    assert ("provision", "alpha") in started, started
    assert ("provision", "weather") not in started


async def test_reconcile_never_gets_store_namespace_for_hosted(monkeypatch):
    """Direct evidence: with a hosted-<name> namespace present, reconcile must
    not issue the GET namespaces/store-<name> request at all."""
    import k8s as prov_k8s

    tasks_mod = _load_provisioner_tasks()

    hosted_ns = {"metadata": {"name": "hosted-weather",
                              "labels": {"urumi.io/managed-by": "provisioner", "urumi.io/store-slug": "weather"}}}

    class FakeK8s(prov_k8s.K8sClient):
        def __init__(self):
            self.get_namespace_calls: list[str] = []

        async def list_managed_namespaces(self):
            return [hosted_ns]

        async def get_namespace(self, ns):
            self.get_namespace_calls.append(ns)
            return hosted_ns if ns == "hosted-weather" else None

        async def store_slug_for_namespace(self, ns_obj):
            return (ns_obj.get("metadata", {}).get("labels", {}) or {}).get("urumi.io/store-slug")

    class FakeHelm:
        async def release_deployed(self, slug):
            return False

        async def release_status(self, slug):
            return None

    manager = tasks_mod.TaskManager(FakeK8s(), FakeHelm())
    started: list[str] = []
    monkeypatch.setattr(manager, "start_provision", lambda slug: started.append(slug))
    monkeypatch.setattr(manager, "start_deprovision", lambda slug: started.append(slug))
    monkeypatch.setattr(tasks_mod, "get_settings",
                        lambda: SimpleNamespace(provision_timeout_seconds=600, max_concurrent=2))

    await manager.reconcile_once()

    assert manager.k8s.get_namespace_calls == [], (
        f"reconcile must not GET any store-<hosted> namespace, got {manager.k8s.get_namespace_calls}"
    )
    assert started == []
