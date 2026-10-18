# 03 — WooCommerce MCP Server (Custom)

## 1. Responsibility

Single purpose: be the **only component that talks to WooCommerce**. Every product/order mutation flows through its tools (8 after F3: products, orders, images). It is **ClusterIP-only**; gateway is its sole caller.

```
Browser/Gateway --X--> Woo MCP --X--> Woo REST API --X--> WordPress/MariaDB
                    (no Ingress)    (CK/CS Basic Auth)
```

---

## 2. Tool Contract (8 tools after F3)

| Tool | Input Schema | Output | Woo REST Call |
|---|---|---|---|
| `list_products` | `{search?: string, status?: "publish"|"draft", per_page?: int (1-100), page?: int, sku?: string}` | `content: text JSON array [{id,name,price,sku,status}]` | `GET /wp-json/wc/v3/products?search&status&per_page&page&sku` |
| `get_product` *(bonus)* | `{id: int}` | single product JSON | `GET /wp-json/wc/v3/products/{id}` |
| `create_product` | `{name: string, regular_price: string, description?: string, sku?: string, type?: "simple"|"variable"}` | `Created product {id}` | `POST /wp-json/wc/v3/products {name,type,regular_price,description,sku}` |
| `list_orders` | `{after?: ISO8601, before?: ISO8601, status?: string, per_page?: int, page?: int}` | array of orders with `id, status, total, line_items, date_created` | `GET /wp-json/wc/v3/orders?after&before&status&per_page` |
| `get_order` | `{id: int}` | single order | `GET /wp-json/wc/v3/orders/{id}` |
| `update_order_status` | `{id: int, status: enum[pending,processing,on-hold,completed,cancelled,refunded,failed]}` | updated order | `PUT /wp-json/wc/v3/orders/{id} {status}` |
| `list_product_images` *(F3)* | `{id: int}` | `{product_id, images:[{id,src,alt}], count}` | `GET /wp-json/wc/v3/products/{id}` (images) |
| `add_product_image` *(F3, write)* | `{product_id: int, filename?: string (advisory), image_base64: string}` | `{attached:true, image_id, url, mime}` | `POST /wp-json/urumi/v1/media` (mu-plugin sideload, ADR-035) + `PUT /wp-json/wc/v3/products/{id} {images:[{id}]}` |

**Annotations:** `list_*` + `get_*` => `readOnlyHint: true`; `create/update/add` => `readOnlyHint: false`. There are deliberately NO delete tools.

**F3 image validation (shared helper, mirrored in the gateway):** only PNG/JPEG/WEBP by magic bytes (claimed type/extension never trusted; no SVG, no GIF), 5 MB cap (`IMAGE_MAX_BYTES`), 4096 px per side, decompression-bomb guard, Pillow re-encode strips EXIF/GPS and polyglot payloads; the stored filename is always server-generated.

---

## 3. How It Talks to the Store (and why REST)

| Option | Verdict | Reason |
|---|---|---|
| **Woo REST API `wc/v3` + Consumer Key/Secret** | **Use** | Official, preserves Woo hooks/inventory, no DB coupling, no extra plugin |
| WP-CLI (`wp wc product create`) | Seeding only | Requires exec into WP pod, not HTTP, unsuitable for MCP Streamable HTTP |
| Direct MySQL | Never | Breaks abstraction, bypasses hooks, fragile schema |
| GraphQL (WPGraphQL) | No | Extra plugin, not standard Woo |

**Auth:** `Authorization: Basic base64(ck:cs)` from env `WOO_URL`, `WOO_CONSUMER_KEY`, `WOO_CONSUMER_SECRET` (K8s Secret `woo-secrets`).

**Note (verified while implementing):** WooCommerce only performs Basic auth when `is_ssl()` is true — see the `urumi-internal-rest` MU plugin installed by the Day 1-2 setup Job, which marks `/wp-json/` requests as SSL for in-cluster callers. Without it every `wc/v3` call answers `401 woocommerce_rest_cannot_view` and the tools would all report `WOO_AUTH_FAILED`.

**Note (F3 image route):** WooCommerce's REST auth only processes its `wc/*` namespaces, so the image route authenticates the same `woo-secrets` Basic pair itself on `determine_current_user` (priority 10, before WordPress' application-password gate) for `/wp-json/urumi/*` paths only — see `docs/DECISIONS.md` ADR-035 postscript.

**Example (Python `httpx`):**
```python
import httpx, base64, os

WOO_URL = os.environ["WOO_URL"]  # http://wordpress.urumi.svc.cluster.local
CK = os.environ["WOO_CONSUMER_KEY"]
CS = os.environ["WOO_CONSUMER_SECRET"]
auth = base64.b64encode(f"{CK}:{CS}".encode()).decode()

async with httpx.AsyncClient(base_url=WOO_URL, timeout=10) as c:
  r = await c.get("/wp-json/wc/v3/products", headers={"Authorization": f"Basic {auth}"}, params={"per_page": 10})
  r.raise_for_status()
```

**Error mapping:**
- Woo 401/403 -> MCP `isError:true` + "Woo auth failed — check Consumer Key"
- Woo 404 -> `isError:true` + "Product/order not found"
- Woo 400 -> `isError:true` + Woo message
- Network/timeout -> MCP `error -32000` "Woo store unreachable"

---

## 4. Implementation Skeleton

```
src/woo-mcp/
  Dockerfile           # python:3.12-slim, pip install mcp httpx
  main.py              # create_streamable_http_app(mcp)
  woo_client.py        # WooRestClient class
  tools.py             # 8 tool handlers + pydantic validators + F3 image validation
  config.py            # settings from env
  health.py            # /healthz, /readyz
```

```python
# main.py
from mcp.server import MCPServer
from mcp.server.streamable_http import create_streamable_http_app
from tools import register_tools

mcp = MCPServer("woo-mcp", instructions="WooCommerce products/orders via REST")
register_tools(mcp)
app = create_streamable_http_app(mcp, json_response=True)

# tools.py
@mcp.tool(annotations={"readOnlyHint": True})
async def list_products(search: str | None = None, per_page: int = 10) -> str:
  data = await woo_client.get("/wp-json/wc/v3/products", params={...})
  return json.dumps([{"id":p["id"],"name":p["name"],"price":p["price"]} for p in data])

@mcp.tool(annotations={"readOnlyHint": False})
async def create_product(name: str, regular_price: str, description: str | None = None) -> str:
  data = await woo_client.post("/wp-json/wc/v3/products", json={"name":name,"type":"simple","regular_price":regular_price,"description":description or ""})
  return f"Created product {data['id']}: {data['name']} (${data['price']})"
# ... plus list_orders, get_order, update_order_status
```

**Dockerfile:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 5. Kubernetes Wiring

```yaml
Service: woo-mcp ClusterIP 8000 (no Ingress)
Deployment: 1 replica, probes:
  livenessProbe: httpGet /healthz:8000 (10s)
  readinessProbe: httpGet /readyz:8000 (5s) -> checks Woo REST reachable
  startupProbe: httpGet /healthz:8000 (failureThreshold 30)
EnvFrom: Secret woo-secrets
NetworkPolicy: ingress from gateway label only; egress to wordpress svc + DNS + 443 (if woo needs external)
Resources: 100m/128Mi requests, 300m/256Mi limits
SecurityContext: runAsNonRoot, readOnlyRootFilesystem, drop ALL
```

---

## 6. Operational Notes

- **Idempotency:** `create_product` with same SKU returns Woo 400 duplicate — surface as `isError:true`; chat agent should handle by searching first.
- **Pagination:** Always cap `per_page <=100`, default 10, return `nextCursor` hint in text.
- **Date filter:** `list_orders after: 2026-10-26T00:00:00` uses Woo `after` param (ISO8601).
- **Seeding:** Helm `post-install` Job creates CK/CS via `wp wc` or Woo REST key endpoint, stores in Secret.

---

## 7. What to Show in Video

1. `kubectl get svc woo-mcp` -> `ClusterIP` (not LoadBalancer/Ingress).
2. `kubectl describe networkpolicy allow-gateway-to-woo-mcp` -> only gateway can reach.
3. Live `tools/call create_product` -> product appears on storefront.
4. Kill Woo MCP pod -> dashboard shows Unreachable, other tools still work.
