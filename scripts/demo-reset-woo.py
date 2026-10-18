"""Reset the demo store's WooCommerce data through the Woo REST API (runs in the woo-mcp pod).

Why this runs in the woo-mcp pod (kubectl exec -c woo-mcp) and not on the host:
that pod is the only component holding WOO_CONSUMER_KEY/WOO_CONSUMER_SECRET in its
environment, and the only one the NetworkPolicy lets reach wordpress:80
(helm/templates/networkpolicy.yaml - the gateway may talk to woo-mcp, never to Woo).

Rules
-----
- Deletes go through wc/v3 with force=true. wp_posts / wp_wc_* rows are never touched
  with hand-written SQL: WooCommerce owns them, and a raw DELETE leaves orphaned
  product-meta and stale lookup tables behind (docs/03).
- Only products that are NOT in the seed manifest (scripts/demo-seeds.json, now the
  12 SKUs of store/products.json) are deleted; every order is deleted (incl. the
  checkout drafts the block checkout creates), because wp-setup seeds none.
- Orphan media is deleted by scripts/demo-reset-media.php running in the wordpress
  pod (the Woo consumer key cannot authenticate wp/v2/media; the F3 upload route has
  no delete endpoint by design) - see demo-reset.sh run_media.
- Settings (COD, tax, shipping, pages) are never written.

Credentials are read from the pod environment and never printed - not in output,
not in URLs (httpx sends them as an Authorization header), not in error paths.

Contract with scripts/demo-reset.sh
----------------------------------
  stdout   human-readable listing: every product as KEEP or DELETE, every order
  last line SUMMARY_JSON {...}    machine-readable counts, no secrets
  exit     0 = ok (incl. nothing to do), 3 = Woo env missing, 4 = a delete failed

Run:
  kubectl exec -n urumi <woo-mcp-pod> -c woo-mcp -- \
    python3 -c "$(cat scripts/demo-reset-woo.py)" --dry-run --seeds-json "$(cat scripts/demo-seeds.json)"
"""

from __future__ import annotations

import argparse
import json
import os

import httpx

SUMMARY_PREFIX = "SUMMARY_JSON "
WOO_API = "wp-json/wc/v3"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="WooCommerce demo-data reset (REST only)")
    ap.add_argument("--dry-run", action="store_true", help="list what would change, change nothing")
    ap.add_argument("--seeds-json", required=True, help="contents of scripts/demo-seeds.json")
    return ap.parse_args()


def load_seeds(raw: str) -> tuple[set[str], set[str]]:
    """Return (seed SKUs upper-cased, seed names) from the manifest JSON."""
    data = json.loads(raw)
    skus = {str(p.get("sku", "")).strip().upper() for p in data.get("products") or [] if p.get("sku")}
    names = {str(p.get("name", "")).strip() for p in data.get("products") or [] if p.get("name")}
    return skus, names


def list_all(client: httpx.Client, path: str, params: dict) -> list[dict]:
    """Fetch every page of a wc/v3 collection (status=any includes drafts + trash)."""
    items: list[dict] = []
    page = 1
    while True:
        resp = client.get(f"{WOO_API}/{path}", params={**params, "per_page": 100, "page": page})
        if resp.status_code >= 400:
            raise RuntimeError(f"Woo GET {path} -> HTTP {resp.status_code} {resp.text[:200]}")
        chunk = resp.json()
        if not isinstance(chunk, list) or not chunk:
            return items
        items.extend(chunk)
        page += 1


def is_seed(product: dict, seed_skus: set[str], seed_names: set[str]) -> bool:
    """KEEP rule from the manifest: SKU match wins; a SKU-less product falls back to name."""
    sku = str(product.get("sku") or "").strip()
    if sku:
        return sku.upper() in seed_skus
    return str(product.get("name") or "").strip() in seed_names


def describe_product(product: dict) -> str:
    sku = product.get("sku") or "(none)"
    return f"#{product.get('id')} {product.get('name')!r} sku={sku} status={product.get('status')}"


def describe_order(order: dict) -> str:
    return (
        f"#{order.get('id')} status={order.get('status')} "
        f"total={order.get('total')} {order.get('currency')} created={order.get('date_created')}"
    )


def delete_one(client: httpx.Client, path: str) -> tuple[bool, bool]:
    """DELETE with force=true. Returns (deleted, already_gone); raises on other failures."""
    resp = client.delete(f"{WOO_API}/{path}", params={"force": "true"})
    if resp.status_code < 300:
        return True, False
    if resp.status_code == 404:
        return False, True
    raise RuntimeError(f"Woo DELETE {path} -> HTTP {resp.status_code} {resp.text[:200]}")


def main() -> int:
    args = parse_args()
    seed_skus, seed_names = load_seeds(args.seeds_json)

    base_url = os.environ.get("WOO_URL", "").strip().rstrip("/")
    consumer_key = os.environ.get("WOO_CONSUMER_KEY", "")
    consumer_secret = os.environ.get("WOO_CONSUMER_SECRET", "")
    if not base_url or not consumer_key or not consumer_secret:
        print("ERROR: WOO_URL / WOO_CONSUMER_KEY / WOO_CONSUMER_SECRET are not all set in the woo-mcp pod env")
        return 3

    # httpx auth=(key, secret) sends an Authorization header: the credentials never
    # appear in a URL, in output, or in an exception message.
    with httpx.Client(
        base_url=base_url,
        auth=(consumer_key, consumer_secret),
        timeout=httpx.Timeout(30.0),
        follow_redirects=False,
        headers={"Accept": "application/json", "User-Agent": "urumi-demo-reset/1"},
    ) as client:
        try:
            products = list_all(client, "products", {"status": "any"})
            orders = list_all(client, "orders", {"status": "any"})
        except (RuntimeError, httpx.HTTPError) as exc:
            print(f"ERROR: {exc}")
            return 3

        keep = [p for p in products if is_seed(p, seed_skus, seed_names)]
        drop = [p for p in products if not is_seed(p, seed_skus, seed_names)]

        print(f"== WooCommerce via Woo REST ({base_url}) ==")
        print(f"products: {len(products)} total | KEEP {len(keep)} (seed manifest) | DELETE {len(drop)}")
        for p in keep:
            print(f"  KEEP    product {describe_product(p)}")
        for p in drop:
            print(f"  DELETE  product {describe_product(p)}")
        print(f"orders: {len(orders)} total | DELETE {len(orders)} (wp-setup seeds no orders)")
        for o in orders:
            print(f"  DELETE  order {describe_order(o)}")

        deleted_products = already_products = deleted_orders = already_orders = 0
        failures: list[str] = []
        if not args.dry_run:
            for p in drop:
                try:
                    deleted, gone = delete_one(client, f"products/{p['id']}")
                except (RuntimeError, httpx.HTTPError) as exc:
                    failures.append(str(exc))
                    print(f"  FAILED  product #{p['id']}: {exc}")
                    continue
                if deleted:
                    deleted_products += 1
                    print(f"  deleted product #{p['id']} {p.get('name')!r}")
                elif gone:
                    already_products += 1
                    print(f"  already gone product #{p['id']}")
            for o in orders:
                try:
                    deleted, gone = delete_one(client, f"orders/{o['id']}")
                except (RuntimeError, httpx.HTTPError) as exc:
                    failures.append(str(exc))
                    print(f"  FAILED  order #{o['id']}: {exc}")
                    continue
                if deleted:
                    deleted_orders += 1
                    print(f"  deleted order #{o['id']}")
                elif gone:
                    already_orders += 1
                    print(f"  already gone order #{o['id']}")

    if args.dry_run:
        print("DRY RUN: no WooCommerce object was changed.")

    summary = {
        "dry_run": args.dry_run,
        "products_total": len(products),
        "products_kept": [
            {"id": p.get("id"), "name": p.get("name"), "sku": p.get("sku")} for p in keep
        ],
        "products_planned": len(drop),
        "products_deleted": deleted_products,
        "products_already_gone": already_products,
        "orders_total": len(orders),
        "orders_planned": len(orders),
        "orders_deleted": deleted_orders,
        "orders_already_gone": already_orders,
        "failures": len(failures),
    }
    print(SUMMARY_PREFIX + json.dumps(summary, separators=(",", ":")))
    return 4 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
