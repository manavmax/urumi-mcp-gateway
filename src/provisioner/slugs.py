"""Store slug validation + the managed-namespace contract (Phase 5, ADR-060).

The provisioner's RBAC is cluster-scoped (Kubernetes RBAC cannot filter
namespaces by label), so the mitigation is CODE: the provisioner only ever
creates namespaces labeled urumi.io/managed-by=provisioner, refuses to touch
any namespace that exists WITHOUT that label, and asserts the label before
every namespaced operation (helm included). The label is the contract.
"""

from __future__ import annotations

import re

MANAGED_LABEL = "urumi.io/managed-by"
MANAGED_LABEL_VALUE = "provisioner"
SLUG_LABEL = "urumi.io/store-slug"
CREATED_AT_ANNOTATION = "urumi.io/created-at"
DELETING_LABEL = "urumi.io/deleting"
FAILURE_ANNOTATION = "urumi.io/provision-failure"
STORE_NAMESPACE_PREFIX = "store-"

# DNS-1123 label: lowercase alphanumerics + '-', 1..30 chars (namespace limit is
# 63; the store-<slug> prefix eats 6, and tool prefixes want headroom)
SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,28}[a-z0-9])?$")

# never usable as a store slug: gateway server slugs (the tools namespace),
# cluster system namespaces, and obvious service names. A store slug becomes
# BOTH a namespace name and an MCP server slug, so collisions are dangerous.
RESERVED_SLUGS = {
    "woo", "gateway", "dashboard", "postgres", "mariadb", "wordpress",
    "demo-time", "demo-notes", "urumi", "admin", "api", "app", "auth",
    "www", "mail", "store", "stores", "kubernetes", "kube-system",
    "kube-public", "kube-node-lease", "default", "ingress-nginx",
    "monitoring", "provisioner", "oauth", "staging", "prod", "test",
    "gateway-provisioner", "cluster", "internal",
}

MAX_DISPLAY_NAME = 60


class StoreError(ValueError):
    """A store request the caller can fix (bad slug, unmanaged namespace)."""


def validate_slug(slug: str) -> str:
    if not isinstance(slug, str) or not slug:
        raise StoreError("store slug is required")
    if not SLUG_RE.match(slug):
        raise StoreError(
            "slug must be 1-30 chars of lowercase letters, digits and '-' "
            "(DNS-1123), starting and ending with a letter or digit"
        )
    if "--" in slug:
        raise StoreError("slug must not contain '--'")
    if slug in RESERVED_SLUGS:
        raise StoreError("that name is reserved")
    if slug.startswith("store-"):
        raise StoreError("the 'store-' prefix is reserved")
    return slug


def slug_from_display_name(display_name: str) -> str:
    """Derive the slug from a display name: lowercase, non-alphanumerics ->
    '-', collapsed, trimmed to 30. The gateway derives the slug; the
    provisioner only validates what it receives."""
    import re as _re

    slug = _re.sub(r"[^a-z0-9-]+", "-", (display_name or "").strip().lower()).strip("-")
    slug = _re.sub(r"-{2,}", "-", slug)[:30].rstrip("-")
    return slug


def store_namespace(slug: str) -> str:
    return f"{STORE_NAMESPACE_PREFIX}{validate_slug(slug)}"


def is_managed(labels: dict | None) -> bool:
    return bool(labels) and labels.get(MANAGED_LABEL) == MANAGED_LABEL_VALUE
