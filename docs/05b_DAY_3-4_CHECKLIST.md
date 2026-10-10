# 05b — Day 3-4 Completion Checklist (Layer 2: Woo MCP Server)

> **Status: DONE AND VERIFIED** on `kind-urumi` (helm release `urumi`, `deployed` — the revision number is a moving target, so it is deliberately not quoted here; check `helm list -n urumi`), 2026-10-10.
> Every check below was executed against the live cluster; nothing here is aspirational.
> Layer 2 also grew two extra demo upstreams (`src/demo-mcp-time`, `src/demo-mcp-notes`) so the
> gateway has non-Woo servers to aggregate: `make verify-demo` (39 checks) covers both.

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
scripts/verify-demo-time.py / verify-demo-notes.py / verify-demo-notes-401.py
helm/values.yaml            # wooMcp.enabled=true (+ demoTime/demoNotes)
helm/values-local.yaml      # wooMcp/demo images -> local build (pullPolicy Never)
helm/templates/networkpolicy.yaml             # allow-woo-mcp-egress, allow-gateway-to-woo-mcp (+ demo equivalents)
helm/templates/deployment-woo-mcp.yaml        # /tmp emptyDir, non-root, readOnlyRootFilesystem, urumi.io/woo-secret-checksum
helm/templates/deployment-demo-time.yaml, deployment-demo-notes.yaml
helm/templates/service-demo-time.yaml, service-demo-notes.yaml
helm/templates/secrets.yaml                   # demo-notes-token (generated on install, never committed) - ADR-015/016
Makefile                    # woo-mcp-image, verify-mcp, demo-images, demo-time-image, demo-notes-image, verify-demo
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
make verify-mcp      # 14 checks + isolation assertion
make verify-demo      # 39 checks: time server, notes server (authenticated), 18 auth checks
make verify-cod      # storefront unaffected (Layer 1 still green)
```

`make verify-mcp` runs **14 checks** (`scripts/verify-mcp.py`). Every negative case asserts the
*specific* code it expects, because a loose "isError == True" passes even when every call is
401ing — that is exactly how a stale Consumer Key hid behind a green run:
```
PASS  initialize 200 status=200
PASS  serverInfo {"name": "woo-mcp", "version": "1.0.0"}
PASS  protocolVersion 2025-03-26
PASS  initialized 202 status=202
PASS  6 tools [...all six...]
PASS  readOnly annotations
PASS  list_products authenticated (not isError)     <-- positive control: a 401ing cluster fails here
PASS  list_products returns a product list
PASS  create_product ok {"created":true,"id":24,...}
PASS  create_product returned an id
PASS  get_product round trip (reads back what we created)
PASS  list_orders authenticated
PASS  unknown product -> WOO_NOT_FOUND (and not an auth error)
PASS  unknown order   -> WOO_NOT_FOUND (not WOO_BAD_REQUEST)
PASS  duplicate SKU   -> WOO_BAD_REQUEST
PASS  unknown tool -> isError with 'Unknown tool'
PASS  probe /healthz
PASS  probe /readyz (Woo reachable)
=== FAILURES: none ===
wordpress -> woo-mcp/mcp: 000 (blocked by NetworkPolicy)
```

There is also an out-of-band run using a **real MCP SDK `ClientSession`**
(`streamablehttp_client`) that lists and calls tools — i.e. exactly what the gateway does in
Days 5-7. The SDK client negotiates its **newest supported** protocol version, so it answers
**2025-06-18** rather than 2025-03-26 (the raw checks above request 2025-03-26 and get it
echoed) — see the "left for later" note on protocol pinning.

Demo upstreams (`make verify-demo`, 39 checks): both handshakes, every tool called, and 18 auth
checks on `demo-mcp-notes` (no token / wrong token / malformed header / `tools/list` /
`tools/call` all -> 401 while the probes stay open).


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
6. **Protocol negotiation**: the SDK echoes the requested version when supported; a raw client asking `2025-03-26` is answered `2025-03-26` (verified), while the **SDK client negotiates its newest**, i.e. `2025-06-18` (this is also what the MCP Inspector negotiated against woo-mcp). Open item for Days 5-7: **verify whether the SDK client can pin a protocol version** — if it cannot, the gateway must simply accept whatever the CLI/Inspector negotiates and not assume `2025-03-26` on the wire.
7. **Default-deny blocks self-calls via the Service IP** — the pod must use loopback (`127.0.0.1:8000`) for local checks; the NetworkPolicy is doing its job.
8. **`streamablehttp_client()` takes no `http_client` kwarg** in SDK 1.12 — pass `httpx_client_factory=<callable returning a new AsyncClient>`.
9. Writes to the store are visible instantly (Woo hooks/inventory preserved) — `create_product` results appear in `wc/v3/products` and on the storefront.

## Left for later / notes for future self

- **Days 5-7 (Gateway)** is the next layer: seed the `woo` upstream pointing at `http://urumi-woo-mcp.urumi.svc.cluster.local:8000/mcp`; classify the `WOO_*` error prefixes into audit outcomes; prefix tools `woo__*`.
- **`gateway-secrets` must follow the credential pattern** (see the same note in `05a`): it is gated on `gateway.enabled` and therefore **not rendered by the chart today**. When the gateway ships it must **always render** (a `lookup`-guarded Secret is deleted by Helm on the next upgrade — gotcha 16 in `05a`, ADR-016), pull values from `lookup` so upgrades are no-ops, carry a **checksum annotation on the gateway Deployment** so a deliberate rotation rolls the pod, and keep the **Fernet key stable across upgrades** — it encrypts upstream credentials at rest, so rotating it makes every stored credential undecryptable.
- `values.yaml` still sets `wooMcp.image` to `ghcr.io/urumi/woo-mcp:0.1.0` for prod; `values-local.yaml` overrides to the locally built image.
- Products created by tests accumulate on the storefront (`MCP E2E Tee`, `Verify Tee`, `Port Forward Tee`, …). Harmless, but re-run `make kind-up` for a clean demo, or prune via `wc/v3`.
- Bootstrap note: this image is not pushed to a registry yet; Day 11 (k3s/VPS) needs `docker push` or a local registry.
