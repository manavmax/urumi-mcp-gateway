"""Regress-core: place a REAL storefront order via the WooCommerce Store API.

Runs INSIDE the woo-mcp pod (the only pod with egress to WordPress). The flow is
the same one the block checkout drives in a browser: pick a product, add it to a
guest cart with the store nonce, place a Cash-on-delivery order through
/wc/store/v1/checkout.

  python3 regress_store_order.py place          -> prints ORDER_ID=<id> PRODUCT_ID=<id>
  python3 regress_store_order.py cleanup <id>   -> deletes the order via wc/v3

Credentials (WOO_CONSUMER_KEY/SECRET) exist only in the pod env and are never
printed. The placed order is deleted by `cleanup` so repeated regress runs leave
the store clean.
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid

import httpx

BASE = os.environ.get("WOO_URL", "http://urumi-wordpress:80").rstrip("/")


def log(msg: str) -> None:
    print(msg, flush=True)


def _nonce_and_cookies(client: httpx.Client) -> tuple[dict, httpx.Cookies]:
    """Store API nonce: from the block-cart page markup, falling back to the
    cart endpoint's response headers."""

    r = client.get(f"{BASE}/cart/", timeout=30)
    m = re.search(r"storeApiNonce: '([a-f0-9]+)'", r.text)
    headers = {"Content-Type": "application/json"}
    if m:
        headers["Nonce"] = m.group(1)
        return headers, client.cookies
    r2 = client.get(f"{BASE}/wp-json/wc/store/v1/cart", timeout=30)
    nonce = r2.headers.get("X-WC-Store-API-Nonce") or r2.headers.get("Nonce")
    if nonce:
        headers["Nonce"] = nonce
        return headers, client.cookies
    raise RuntimeError(f"no store nonce found (cart page status={r.status_code})")


def place() -> int:
    with httpx.Client(timeout=60) as client:
        headers, _ = _nonce_and_cookies(client)
        r = client.get(f"{BASE}/wp-json/wc/store/v1/products?per_page=1", headers=headers, timeout=30)
        products = r.json() if r.status_code == 200 else []
        if not products:
            log("FAIL no products returned by the store")
            return 1
        product = products[0]
        r = client.post(
            f"{BASE}/wp-json/wc/store/v1/cart/add-item",
            headers=headers,
            json={"id": product["id"], "quantity": 1},
            timeout=30,
        )
        if r.status_code not in (200, 201):
            log(f"FAIL add-item status={r.status_code} body={r.text[:160]}")
            return 1
        billing = {
            "first_name": "Regress",
            "last_name": "Probe",
            "address_1": "1 Test St",
            "city": "Testville",
            "state": "CA",
            "postcode": "90001",
            "country": "US",
            "email": f"regress-{uuid.uuid4().hex[:8]}@example.invalid",
            "phone": "5555555555",
        }
        r = client.post(
            f"{BASE}/wp-json/wc/store/v1/checkout",
            headers=headers,
            json={"billing_address": billing, "payment_method": "cod", "customer_note": "regress-core probe order"},
            timeout=60,
        )
        body = r.json() if r.status_code == 200 else {}
        order_id = body.get("order_id")
        if not order_id:
            log(f"FAIL checkout status={r.status_code} body={r.text[:200]}")
            return 1
        log(f"PASS storefront order placed via Store API (COD): #{order_id} product={product['id']}")
        log(f"ORDER_ID={order_id}")
        log(f"PRODUCT_ID={product['id']}")
        return 0


def cleanup(order_id: str) -> int:
    """Delete the probe order through wc/v3 (Basic CK/CS from the pod env)."""
    import base64

    ck = os.environ.get("WOO_CONSUMER_KEY", "")
    cs = os.environ.get("WOO_CONSUMER_SECRET", "")
    if not ck or not cs:
        log("FAIL cleanup needs WOO_CONSUMER_KEY/SECRET in the pod env")
        return 1
    token = base64.b64encode(f"{ck}:{cs}".encode()).decode()
    with httpx.Client(timeout=60) as client:
        r = client.delete(
            f"{BASE}/wp-json/wc/v3/orders/{order_id}",
            params={"force": "true"},
            headers={"Authorization": f"Basic {token}"},
        )
        if r.status_code in (200, 204):
            log(f"PASS probe order {order_id} deleted from the store")
            return 0
        # already gone is success
        if r.status_code == 404 and json.loads(r.text or '{}').get("code") == "woocommerce_rest_shop_order_invalid_id":
            log(f"PASS probe order {order_id} already absent")
            return 0
        log(f"FAIL delete order status={r.status_code} (body not printed)")
        return 1


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("place", "cleanup"):
        log("usage: regress_store_order.py place | cleanup <order_id>")
        raise SystemExit(2)
    if sys.argv[1] == "place":
        raise SystemExit(place())
    if len(sys.argv) < 3:
        log("cleanup needs the order id")
        raise SystemExit(2)
    raise SystemExit(cleanup(sys.argv[2]))
