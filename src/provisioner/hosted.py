"""Hosted MCP servers (Phase 6, ADR-062): admin adds a server BY CONTAINER IMAGE.

The provisioner deploys, into a dedicated namespace hosted-<name> (carrying the
SAME managed label as stores - the label guard keeps every operation inside
provisioner-owned namespaces):
  - Deployment: the admin's image, non-root, read-only root filesystem, NO
    service account token, mandatory resource requests/limits (capped by Helm
    values), probes on the admin-supplied port
  - Service: the port
  - Secret: env var VALUES (the gateway never sees them; only names reach any API)
  - NetworkPolicies: default-deny; ingress ONLY from the gateway pods; egress DNS only

Image rules (enforced HERE and in the gateway):
  - a tag or digest is REQUIRED (bare name or :latest refused)
  - optional registry allowlist (hostedServers.allowedRegistries) in the gateway

State is derived from the cluster exactly like stores: the hosted server exists
iff its labeled namespace exists; it is ready iff the Deployment is Available.
Applies are idempotent (apply_object), so a re-drive is safe. Teardown deletes
the namespace (cascades everything).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from config import get_settings
from slugs import StoreError, is_managed, validate_slug

if TYPE_CHECKING:
    from k8s import K8sClient

logger = logging.getLogger("provisioner.hosted")

HOSTED_NAMESPACE_PREFIX = "hosted-"
CREATED_AT_ANNOTATION = "urumi.io/created-at"
MANAGED_LABEL = "urumi.io/managed-by"
MANAGED_LABEL_VALUE = "provisioner"
SLUG_LABEL = "urumi.io/store-slug"
DELETING_LABEL = "urumi.io/deleting"


class HostedImageError(StoreError):
    """A hosted-server request the caller can fix (bad image, bad name)."""


def validate_image(image: str) -> str:
    """An image reference WITH a tag or digest, never :latest, never bare."""
    if not isinstance(image, str) or "/" not in image:
        raise HostedImageError(
            "image must be registry/repo:tag (e.g. ghcr.io/urumi/demo-mcp-time:0.1.0)"
        )
    last = image.split("/")[-1]
    if ":" not in last and "@" not in image:
        raise HostedImageError("image needs a tag or digest (e.g. ...:0.1.0)")
    if image.endswith(":latest"):
        raise HostedImageError(":latest is not allowed; pin a version tag or digest")
    return image


def hosted_namespace(name: str) -> str:
    return f"hosted-{validate_slug(name)}"


def _probe(port: int, path: str) -> dict:
    """A readiness/liveness probe: a plain TCP connect is the safest generic
    probe for an arbitrary admin image (no path assumptions beyond the port).
    `path` is reserved for an HTTP probe once a hosted server declares one."""
    return {
        "tcpSocket": {"port": port},
        "initialDelaySeconds": 3,
        "periodSeconds": 5,
        "timeoutSeconds": 2,
        "failureThreshold": 3,
    }


def build_objects(name: str, ns: str, image: str, port: int, env: dict) -> list[dict]:
    """The four (or three) objects for one hosted server, in apply order:
    default-deny netpol, allow-gateway netpol, env Secret (only when env given),
    Service, Deployment. Labels mark them hosted so reconcile maps them."""
    s = get_settings()
    common = {"urumi.io/hosted": name}
    deployment_labels = {"app": "hosted-mcp", "urumi.io/hosted-name": name}
    objects: list[dict] = [
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": "default-deny", "labels": common},
            "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]},
        },
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": "allow-gateway", "labels": common},
            "spec": {
                "podSelector": {"matchLabels": deployment_labels},
                "policyTypes": ["Ingress", "Egress"],
                "ingress": [{
                    "from": [{
                        "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": s.gateway_namespace}},
                        "podSelector": {"matchLabels": {"app": "gateway"}},
                    }],
                    "ports": [{"port": port, "protocol": "TCP"}],
                }],
                "egress": [{
                    # DNS only
                    "to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}}],
                    "ports": [
                        {"protocol": "UDP", "port": 53},
                        {"protocol": "TCP", "port": 53},
                        {"protocol": "UDP", "port": 9153},
                        {"protocol": "TCP", "port": 9153},
                    ],
                }],
            },
        },
    ]
    if env:
        objects.append({
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": f"{name}-env", "labels": common},
            "type": "Opaque",
            "stringData": dict(env),
        })
    objects.extend([
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": name, "labels": common},
            "spec": {
                "selector": deployment_labels,
                "ports": [{"port": port, "targetPort": "http", "protocol": "TCP", "name": "http"}],
            },
        },
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": name, "labels": common},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": deployment_labels},
                "template": {
                    "metadata": {"labels": {"app.kubernetes.io/name": "urumi-hosted", **deployment_labels}},
                    "spec": {
                        "automountServiceAccountToken": False,
                        "containers": [{
                            "name": "server",
                            "image": image,
                            "imagePullPolicy": "IfNotPresent",
                            "ports": [{"containerPort": port, "name": "http"}],
                            "env": [
                                {"name": k, "valueFrom": {"secretKeyRef": {"name": f"{name}-env", "key": k}}}
                                for k in env
                            ],
                            "resources": {
                                "requests": {"cpu": s.hosted_cpu_request, "memory": s.hosted_memory_request},
                                "limits": {"cpu": s.hosted_cpu_limit, "memory": s.hosted_memory_limit},
                            },
                            "securityContext": {
                                "runAsNonRoot": True,
                                "runAsUser": 1000,
                                "runAsGroup": 1000,
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "livenessProbe": {
                                "tcpSocket": {"port": port},
                                "initialDelaySeconds": 5,
                                "periodSeconds": 10,
                                "failureThreshold": 6,
                            },
                            "readinessProbe": {
                                "tcpSocket": {"port": port},
                                "initialDelaySeconds": 3,
                                "periodSeconds": 3,
                            },
                            "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
                        }],
                        "volumes": [{"name": "tmp", "emptyDir": {}}],
                    },
                },
            },
        },
    ])
    return objects


class HostedTasks:
    """Hosted-server lifecycle. No long-running tasks: applies are quick API
    calls and readiness is derived from the Deployment; the cluster is the
    state, so a provisioner restart needs no re-drive."""

    def __init__(self, k8s: K8sClient):
        self.k8s = k8s

    async def host(self, name: str, image: str, port: int, env: dict) -> None:
        """Create hosted-<name> and apply the objects. Idempotent."""
        from hosted import hosted_namespace

        validate_slug(name)
        port = int(port)
        if not (1 <= port <= 65535):
            raise StoreError("port must be 1-65535")
        if env is None:
            env = {}
        if not isinstance(env, dict):
            raise StoreError("env must be an object of name -> value")
        for k, v in env.items():
            ok_name = bool(k) and (k[0].isalpha() or k[0] == "_") and all(c.isalnum() or c == "_" for c in k)
            if not ok_name:
                raise StoreError("env names must be simple identifiers (letters, digits, underscore)")
            if not isinstance(v, str):
                raise StoreError("env values must be strings")
        ns = hosted_namespace(name)
        await self.k8s.create_hosted_namespace(name)
        for obj in build_objects(name, ns, image, port, env):
            await self.k8s.apply_object(obj["apiVersion"], obj["kind"], ns, obj)
        logger.info("hosted %s applied in %s", name, ns)

    async def unhost(self, name: str) -> None:
        """Delete the hosted-<name> namespace (cascades Deployment, Service,
        Secret, NetworkPolicies). Requires the managed label."""
        from hosted import hosted_namespace

        ns = hosted_namespace(name)
        obj = await self.k8s.get_namespace(ns)
        if obj is None:
            return
        await self.k8s.require_managed(ns)
        r = await self.k8s._client.delete(f"/api/v1/namespaces/{ns}")
        if r.status_code not in (200, 202, 404):
            raise StoreError(f"hosted namespace delete failed: {r.status_code}")
        logger.info("hosted %s deleted (namespace teardown started)", name)

    async def state(self, name: str) -> dict:
        """Derive {phase} from the cluster: provisioning | ready | gone."""
        from hosted import hosted_namespace

        validate_slug(name)
        ns = hosted_namespace(name)
        ns_obj = await self.k8s.get_namespace(ns)
        if ns_obj is None:
            return {"phase": "gone"}
        if not is_managed(ns_obj.get("metadata", {}).get("labels")):
            raise StoreError(f"namespace {ns} is not managed by the provisioner")
        if await self.k8s.deployment_ready(ns, name):
            return {"phase": "ready", "reason": ""}
        return {"phase": "provisioning", "reason": ""}
