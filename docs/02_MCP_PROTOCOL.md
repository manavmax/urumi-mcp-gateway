# 02 — MCP Protocol Deep Dive (Streamable HTTP)

> **Goal:** You can whiteboard the MCP lifecycle and defend every wire decision in the live walkthrough.

## 1. Spec Version & Why Streamable HTTP

- **Target spec:** `2025-03-26` (single endpoint `POST /mcp` + `GET /mcp` SSE, JSON or SSE response). `2025-06-18` is similar but forbids JSON-RPC batch — pin server to handle single-object POST.
- **Why not SSE (2024-11-05):** Deprecated, 2 endpoints (`GET /sse` + `POST <endpoint>`), harder to load-balance. Streamable HTTP is DNS-rebind safe, works with standard Ingress.
- **Transport docs:** `modelcontextprotocol.io/specification/2025-03-26/basic/transports` + `server/tools` + Python SDK `py.sdk.modelcontextprotocol.io`.

---

## 2. Wire Format (JSON-RPC 2.0 over HTTP)

### 2.1 Initialize Handshake

```http
POST /mcp HTTP/1.1
Host: dashboard.127.0.0.1.nip.io
Accept: application/json, text/event-stream
Content-Type: application/json
Authorization: Bearer <user-api-key>
MCP-Protocol-Version: 2025-03-26

{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
  "protocolVersion":"2025-03-26",
  "capabilities":{"roots":{"listChanged":true}},
  "clientInfo":{"name":"claude-code","version":"1.0.0"}
}}
```
Response (gateway):
```http
HTTP/1.1 200 OK
Content-Type: application/json
Mcp-Session-Id: 1868a90c-...   # optional, if gateway uses sticky sessions (we don't — stateless)

{"jsonrpc":"2.0","id":1,"result":{
  "protocolVersion":"2025-03-26",
  "capabilities":{"tools":{"listChanged":true}},
  "serverInfo":{"name":"urumi-gateway","version":"1.0.0"},
  "instructions":"Use tools via gateway; tools are prefixed slug__tool"
}}
```
Client sends `notifications/initialized` -> `202 Accepted`.

**Our choice: stateless gateway** — no `Mcp-Session-Id` issued. Every `tools/call` is independent, so N replicas work without Redis sticky session. Document this tradeoff (vs stateful session needing `Last-Event-ID` replay).

### 2.2 Tools Discovery

```http
POST /mcp
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
```
Response (aggregated):
```json
{"jsonrpc":"2.0","id":2,"result":{
  "tools":[
    {"name":"woo__list_products","description":"[woo] List products","inputSchema":{"type":"object","properties":{"search":{"type":"string"},"per_page":{"type":"integer"} }}},
    {"name":"woo__create_product","description":"[woo] Create product","inputSchema":{"type":"object","properties":{"name":{"type":"string"},"regular_price":{"type":"string"}},"required":["name","regular_price"]}},
    {"name":"woo__list_orders","description":"[woo] List orders","inputSchema":{"type":"object","properties":{"after":{"type":"string"},"status":{"type":"string"}}}},
    {"name":"woo__get_order","description":"[woo] Get order by id","inputSchema":{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}},
    {"name":"woo__update_order_status","description":"[woo] Update order status","inputSchema":{"type":"object","properties":{"id":{"type":"integer"},"status":{"type":"string","enum":["pending","processing","on-hold","completed","cancelled","refunded","failed"]}},"required":["id","status"]}},
    {"name":"time__get_current_time","description":"[time] Get current time","inputSchema":{"type":"object","properties":{"timezone":{"type":"string"}}}}
  ]
}}
```

### 2.3 Tool Call

```http
POST /mcp
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
  "name":"woo__create_product",
  "arguments":{"name":"Urumi Tee","regular_price":"29.99"}
}}
```
Gateway strips prefix `woo__` -> forwards `create_product` to Woo MCP:
```http
POST http://woo-mcp.urumi.svc.cluster.local:8000/mcp
Authorization: Bearer <upstream-cred>  # server-side only
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"create_product","arguments":{"name":"Urumi Tee","regular_price":"29.99"}}}
```
Success response:
```json
{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"Created product 123: Urumi Tee ($29.99)"}],"isError":false}}
```
Tool error (still `result`):
```json
{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"Woo API 400: regular_price required"}],"isError":true}}
```
Protocol error:
```json
{"jsonrpc":"2.0","id":3,"error":{"code":-32602,"message":"Unknown tool: woo__unknown"}}
```

---

## 3. Aggregation Design (Gateway as Client + Server)

### 3.1 Registry & Tool Cache

```python
# gateway/mcp/registry.py (conceptual)
@dataclass
class Upstream:
  id: UUID; slug: str; url: str; auth_type: str
  credential_encrypted: bytes; enabled: bool
  status: Literal["Connected","Unreachable","Disabled"]
  tools_cache: list[Tool]  # last successful tools/list
  last_checked: datetime
```

- `tools/list` fans out to all `enabled` upstreams with `asyncio.gather(return_exceptions=True)` + `wait_for(3s)` per upstream (`gateway.timeouts.listSeconds`, ADR-089); a call gets 15s by default (`gateway.timeouts.callSeconds`).
- Success -> upsert `tools` table (`exposed_name = slug__original`), cache in memory + PG.
- Failure -> mark `Unreachable`, keep stale cache for 30s or return partial `warnings`.

### 3.2 Collision Handling — Prefix Scheme

| Approach | Pros | Cons | Verdict |
|---|---|---|---|
| Prefix `slug__tool` | Deterministic, LLM-friendly, zero ambiguity | Tool names longer | **Use** |
| Separate `server` param wrapper | Clean names | Breaks MCP spec (tool name must be unique string) | No |
| Allow duplicates, client chooses | Simple | Spec violation, routing ambiguous | No |

- On `tools/list`: expose `woo__list_products`; description prefixed `[woo]`.
- On `tools/call`: `name.split("__",1)` -> `(slug, original)`; lookup map; 404 if disabled/unknown.
- Audit stores both `exposed_name` and `upstream_name`.

### 3.3 Failure Isolation

```python
# gateway/mcp/aggregator.py
async def list_tools(user: User) -> list[Tool]:
  servers = await get_enabled_servers()
  allowed = filter_by_permissions(user, servers)  # per-tool RBAC

  async def fetch(s):
    try:
      async with asyncio.timeout(8):
        async with streamablehttp_client(s.url, headers=auth_headers(s)) as (r,w,_):
          async with ClientSession(r,w) as sess:
            await sess.initialize()
            res = await sess.list_tools()
            return [(s.slug, t) for t in res.tools]
    except Exception as e:
      breaker.record_failure(s.id); mark_unhealthy(s.id, str(e))
      return e  # return_exceptions path

  results = await asyncio.gather(*[fetch(s) for s in allowed], return_exceptions=True)
  tools = []
  warnings = []
  for r in results:
    if isinstance(r, Exception):
      warnings.append(str(r)); continue
    for slug, tool in r:
      tools.append(to_dict_with_prefix(tool, slug))
  # never throw because one upstream died
  return tools  # + warnings in _meta if SSE
```

For `tools/call`:
```python
async def call_tool(user, exposed_name, arguments):
  check_permission(user, exposed_name)  # 403 if denied
  slug, original = split_prefix(exposed_name)
  server = await get_server_by_slug(slug)
  if breaker.is_open(server.id): raise McpError(503, f"Upstream {slug} circuit open")
  try:
    async with asyncio.timeout(server.timeout or 10):
      result = await proxy_call(server, original, arguments)
    audit(user, server, original, "success", duration)
    breaker.record_success(server.id)
    return result
  except TimeoutError:
    audit(..., "timeout"); breaker.record_failure(server.id); raise McpError(504, "upstream timed out")
  except Exception as e:
    audit(..., "upstream_error"); breaker.record_failure(server.id); raise
```

### 3.4 Health Loop (async background)

```python
async def health_loop():
  while True:
    for s in await get_enabled_servers():
      try:
        async with asyncio.timeout(5):
          await probe_tools_list(s)  # lightweight
        mark_connected(s.id)
      except Exception as e:
        mark_unreachable(s.id, str(e))
    await asyncio.sleep(15)
```

Dashboard polls `GET /api/servers` which reads `status` column.

---

## 4. Python SDK Usage (pinned)

```python
# Woo MCP server
from mcp.server import MCPServer
from mcp.server.streamable_http import create_streamable_http_app

mcp = MCPServer("woo-mcp", instructions="WooCommerce products/orders")

@mcp.tool(annotations={"readOnlyHint": True})
def list_products(search: str | None = None, per_page: int = 10) -> str: ...

# Mount on FastAPI
app = create_streamable_http_app(mcp, json_response=True)  # serves POST /mcp, GET /mcp
```

```python
# Gateway upstream client (ephemeral)
from mcp.client.streamable_http import streamable_http_client
from mcp import ClientSession
import httpx

async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as hc:
  async with streamable_http_client(url, http_client=hc) as (read, write, _):
    async with ClientSession(read, write) as sess:
      await sess.initialize()
      tools = await sess.list_tools()
      res = await sess.call_tool("list_products", {"per_page": 5})
```

---

## 5. Security Headers & Origin Validation

- Validate `Origin` header (DNS rebinding defense) if browser-facing.
- `Authorization: Bearer <user-key>` required on every `/mcp` POST; `401` with `WWW-Authenticate: Bearer`.
- Upstream `Authorization` header stripped from logs/errors.
- `Content-Type: application/json` enforced; max body 1MB.

---

## 6. Interview Defence Checklist

- Explain why **Streamable HTTP** vs SSE (single endpoint, Ingress-friendly, spec current).
- Walk `initialize -> tools/list -> tools/call` with headers and JSON.
- Justify **stateless gateway** (scale) vs session (resume) tradeoff.
- Show prefix collision routing with code.
- Show timeout + `return_exceptions` isolation + health loop + circuit breaker.
- Show credential never leaves server: encrypted column, injected at proxy time, no echo to client.
