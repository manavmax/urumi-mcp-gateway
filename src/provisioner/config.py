"""Provisioner settings (Phase 5, ADR-060).

Every value is env-driven; the Helm chart (templates gated on
provisioner.enabled) supplies them. The shared token is the ONLY secret here
and it lives in the provisioner-token Secret, never in values or git.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    port: int = 9000
    # shared internal secret (from the provisioner-token Secret); the gateway
    # must present it in the X-Provisioner-Token header (constant-time compare)
    shared_token: str = ""
    # where the store chart is baked into the image
    chart_dir: str = "/charts/store"
    # the namespace the GATEWAY runs in (for the store chart's NetworkPolicy)
    gateway_namespace: str = "urumi"
    # per-store ingress host = <slug>.<base_domain> (local: localhost)
    base_domain: str = "localhost"
    ingress_class: str = "nginx"
    storage_class: str = "standard"
    node_cidr: str = "172.18.0.0/16"
    # overall provisioning budget per store (the brief's provisionTimeoutSeconds)
    provision_timeout_seconds: int = 600
    # how many stores may provision at once (protects the laptop node)
    max_concurrent: int = 2
    # helm per-attempt wait (HOOKS included): the wp-setup hook needs several
    # minutes on a laptop node; must stay below the overall budget
    helm_timeout: str = "540s"
    reconcile_interval_seconds: int = 10
    log_level: str = "INFO"
    # store chart image repos/tags: forwarded from the MAIN release's resolved
    # values by the Helm chart (values-local rewrites repos to node-local
    # urumi/...; prod keeps ghcr.io/...), so store pods always run the same
    # images as the main release.
    store_image_wordpress_repo: str = "ghcr.io/urumi/wordpress"
    store_image_wordpress_tag: str = "6.6-php8.2-apache-hardened"
    store_image_woo_mcp_repo: str = "ghcr.io/urumi/woo-mcp"
    store_image_woo_mcp_tag: str = "0.1.0"
    store_image_wp_cli_repo: str = "ghcr.io/urumi/wp-cli"
    store_image_wp_cli_tag: str = "cli-php8.2-hardened"
    store_image_assets_repo: str = "ghcr.io/urumi/store-assets"
    store_image_assets_tag: str = "0.1.0"
    store_image_mariadb_repo: str = "mariadb"
    store_image_mariadb_tag: str = "11.4"

    @property
    def kubeconfig_path(self) -> str:
        return "/tmp/provisioner-kubeconfig"


@lru_cache
def get_settings() -> Settings:
    return Settings()
