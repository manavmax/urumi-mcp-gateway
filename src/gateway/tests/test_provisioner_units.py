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
