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
