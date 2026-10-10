# 05b — Day 3-4 Completion Checklist (Layer 2: Woo MCP Server)

> **Status: DONE AND VERIFIED** on `kind-urumi` (helm release `urumi`, revision 3, `deployed`), 2026-10-10.
> Every check below was executed against the live cluster; nothing here is aspirational.

## Exit criteria (from `docs/08_IMPLEMENTATION_ROADMAP.md`)

- [x] `src/woo-mcp/` — FastAPI/Starlette + `mcp` SDK, 6 tools via `httpx` to `wc/v3`
- [x] `WooRestClient` with CK/CS Basic auth, timeout 10s, error mapping
- [x] Dockerfile + K8s Deployment/Service (ClusterIP) + probes (readyz hits Woo)
- [x] Tested via `kubectl port-forward` AND in-cluster: `tools/list` (6 tools) + `call create_product` → verified on storefront
- [x] NetworkPolicy: only gateway can reach woo-mcp
- **Exit: `npx @modelcontextprotocol/inspector` via port-forward shows 6 tools, all working — verified**

## Files created (Layer 2)

```
src/woo-mcp/
  config.py        # env-driven settings (WOO_URL/WOO_CONSUMER_KEY/WOO_CONSUMER_SECRET)
  woo_client.py    # WooRestClient: Basic auth, 10s timeout, follow_redirects=False, error classes
  tools.py         # the 6 tools with pydantic validation + ToolAnnotations
  main.py          # FastMCP(json_response=True, stateless_http=True) + /healthz /readyz /
  requirements.txt # mcp==1.12.*, httpx==0.27.*, uvicorn, pydantic==2.11.*
  Dockerfile       # python:3.12-slim, non-root (uid 1000), healthcheck
scripts/verify-mcp.py   # `make verify-mcp` body: handshake + tools + error mapping
helm/values.yaml        # wooMcp.enabled=true
helm/values-local.yaml  # wooMcp.image → local build (pullPolicy Never)
helm/templates/networkpolicy.yaml  # + allow-woo-mcp-egress, allow-gateway-to-woo-mcp
helm/templates/deployment-woo-mcp.yaml  # + /tmp emptyDir (readOnlyRootFilesystem)
Makefile                # + woo-mcp-image, verify-mcp
```

## Tool contract (docs/03 §2 — all shipped)

| Tool | readOnlyHint | Woo call |
|---|---|---|
| `list_products` | true | `GET /wp-json/wc/v3/products` (search/status/sku/per_page/page) |
| `get_product` | true | `GET /wp-json/wc/v3/products/{id}` |
| `create_product` | false | `POST /wp-json/wc/v3/products` |
| `list_orders` | true | `GET /wp-json/wc/v3/orders` (after/before/status) |
| `get_order` | true | `GET /wp-json/wc/v3/orders/{id}` |
| `update_order_status` | false | `PUT /wp-json/wc/v3/orders/{id}` (status enum) |

## Verification evidence

```bash
make woo-mcp-image   # build + import into kind node
make verify-mcp      # 9 checks + isolation assertion
make verify-cod      # storefront unaffected (Layer 1 still green)
```

`make verify-mcp` output (last run):
```
PASS  initialize 200 status=200
PASS  serverInfo {"name": "woo-mcp", "version": "1.0.0"}
PASS  protocolVersion 2025-03-26
PASS  initialized 202 status=202
PASS  6 tools [...all six...]
PASS  readOnly annotations
PASS  create_product {"created":true,"id":24,...}
PASS  unknown id -> WOO_NOT_FOUND
PASS  duplicate SKU -> isError
=== FAILURES: none ===
wordpress -> woo-mcp/mcp: 000 (blocked by NetworkPolicy)
```
Plus an out-of-band raw-wire + real SDK-client run (21 checks, all PASS) covering
`list_orders`, `get_order`, `update_order_status`, duplicate-SKU, unknown tool,
and an MCP SDK `ClientSession` (`streamablehttp_client`) listing + calling tools
— i.e. exactly what the gateway will do in Days 5-7.

## K8s posture

- [x] Service `urumi-woo-mcp` is **ClusterIP** — no Ingress route (ingress shows only `store.` and `dashboard.` hosts)
- [x] NetworkPolicies: `allow-woo-mcp-egress` (→ wordpress:80 only), `allow-gateway-to-woo-mcp` (ingress from `app=gateway` only), `allow-gateway-egress-to-woo-mcp`
- [x] Proven isolation: `kubectl exec` from the **wordpress** pod → `000` (blocked by default-deny)
- [x] Probes: liveness `/healthz` (no external deps), readiness `/readyz` (actually reaches `wc/v3`, flips 503 when Woo is down — verified by pointing the client at a dead port)
- [x] `securityContext`: non-root uid 1000, `drop ALL`, `readOnlyRootFilesystem: true` with `/tmp` emptyDir
- [x] Credentials: only from the `woo-secrets` Secret (`WOO_URL/WOO_CONSUMER_KEY/WOO_CONSUMER_SECRET`), no plaintext in values

## Gotchas solved here (do not relearn)

1. **`streamable_http_app()` already serves `/mcp`** — mounting it under `Mount("/mcp")` produced a **307 redirect loop**. Reuse the returned app and append probe routes to its router instead.
2. **`pydantic 2.14` breaks `mcp 1.12`** (`ImportError: eval_type_backport`) — pin `pydantic==2.11.*` (in `src/woo-mcp/requirements.txt`, with a comment).
3. **Tool failures surface as `result.isError: true`, not JSON-RPC errors** — SDK 1.12 maps *every* tool exception through `CallToolResult(isError=True)`, so the documented `-32000` for "Woo unreachable" cannot be produced by a tool. Tools therefore emit a **stable machine-readable prefix** (`WOO_AUTH_FAILED`, `WOO_NOT_FOUND`, `WOO_BAD_REQUEST`, `WOO_UNREACHABLE`, `WOO_UNEXPECTED`) that the gateway will classify in Days 5-7.
4. **Unknown id → 400, not 404** — Woo returns `woocommerce_rest_invalid_id` (400) for a missing product/order on PUT, so the classifier maps those 400 bodies to `WOO_NOT_FOUND` (`_NOT_FOUND_MARKERS` in `woo_client.py`).
5. **`readOnlyRootFilesystem: true` needs a writable `/tmp`** — add an `emptyDir` volume, otherwise the pod can't write temp files.
6. **Protocol negotiation**: the SDK echoes the requested version if supported; a raw client asking `2025-03-26` is answered `2025-03-26` (verified), while the SDK client negotiates its newest (`2025-06-18`). Gateway will pin `2025-03-26`.
7. **Default-deny blocks self-calls via the Service IP** — the pod must use loopback (`127.0.0.1:8000`) for local checks; the NetworkPolicy is doing its job.
8. **`streamablehttp_client()` takes no `http_client` kwarg** in SDK 1.12 — pass `httpx_client_factory=<callable returning a new AsyncClient>`.
9. Writes to the store are visible instantly (Woo hooks/inventory preserved) — `create_product` results appear in `wc/v3/products` and on the storefront.

## Left for later / notes for future self

- **Days 5-7 (Gateway)** is the next layer: seed `woo` upstream pointing at `http://urumi-woo-mcp.urumi.svc.cluster.local:8000/mcp`; classify the `WOO_*` error prefixes into audit outcomes; prefix tools `woo__*`.
- `values.yaml` still sets `wooMcp.image` to `ghcr.io/urumi/woo-mcp:0.1.0` for prod; `values-local.yaml` overrides to the locally built image.
- Products created by tests accumulate on the storefront (`MCP E2E Tee`, `Verify Tee`, `Port Forward Tee`, …). Harmless, but re-run `make kind-up` for a clean demo, or prune via `wc/v3`.
- Bootstrap note: this image is not pushed to a registry yet; Day 11 (k3s/VPS) needs `docker push` or a local registry.
