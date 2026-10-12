# 04 — Gateway Backend (Dashboard + MCP Aggregation)

## 1. What the Gateway Is

One FastAPI process that is **simultaneously**:
- **MCP Client** to N upstreams (httpx outgoing)
- **MCP Server** at `POST/GET /mcp` (incoming)
- **Admin REST API** at `/api/*` for dashboard

```
                Upstream MCPs
                /      |      \
         woo-mcp   time-mcp  github-mcp
               \      |      /
                \     |     /  streamablehttp_client (ephemeral, timeout)
                 +----+----+
                 | Gateway |  <-- verifies user API key, RBAC, SSRF, audit
                 +----+----+
                   /  |  \
            /api/*  /mcp  /api/chat  (Ingress path routing)
               \     |     /
            Dashboard SPA  MCP Inspector / Claude Code
```

---

## 2. Module Layout

```
src/gateway/
  main.py            # FastAPI lifespan: health_loop, audit_worker, httpx pools
  config.py          # pydantic-settings
  db/
    models.py        # users, api_keys, servers, tools, audit_logs, permissions
    session.py       # async engine + SessionLocal
  auth/
    keys.py          # generate, sha256 digest (the only stored material), verify, revoke
    rbac.py          # require_admin, require_member dependencies
    session.py       # cookie session for dashboard (itsdangerous)
  registry/
    validator.py     # SSRF: scheme, blocked nets, DNS resolve, redirect check
    crypto.py        # Fernet encrypt/decrypt for upstream creds
    crud.py          # servers CRUD + health status
  mcp/
    aggregator.py    # tools/list fan-out, collision prefix, timeout isolation
    router.py        # tools/call routing + permission check
    breaker.py       # circuit breaker per server
    health.py        # background probe loop
  audit/
    queue.py         # asyncio.Queue + batch flush to PG
    crud.py          # query with filters
  chat/
    agent.py         # LLM tool loop (OpenAI), streaming SSE
    prompts.py       # system prompt, tool-output sanitization
  routes/
    mcp.py           # POST/GET /mcp (Streamable HTTP handler)
    servers.py       # /api/servers CRUD
    users.py         # /api/users, /api/keys
    audit.py         # /api/audit
    chat.py          # /api/chat/completions
    tools.py         # /api/tools (aggregated catalog for dashboard)
```

---

## 3. Data Models (PostgreSQL + SQLAlchemy async)

```sql
-- users
CREATE TABLE users (
  id UUID PRIMARY KEY, email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,  -- dashboard login (argon2id)
  role TEXT CHECK (role IN ('admin','member')) NOT NULL,
  is_active BOOL DEFAULT true, created_at TIMESTAMPTZ DEFAULT now()
);

-- api_keys (per-user, for /mcp)
CREATE TABLE api_keys (
  id UUID PRIMARY KEY, user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  prefix TEXT NOT NULL DEFAULT 'urumi_sk_',
  hash TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE, last4 TEXT NOT NULL,
  revoked_at TIMESTAMPTZ, expires_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON api_keys(sha256); CREATE INDEX ON api_keys(user_id);

-- servers (upstream MCP registry)
CREATE TABLE servers (
  id UUID PRIMARY KEY, slug TEXT UNIQUE NOT NULL CHECK (slug ~ '^[a-z0-9-]+$'),
  url TEXT NOT NULL, auth_type TEXT CHECK (auth_type IN ('none','bearer','header')) NOT NULL DEFAULT 'none',
  header_name TEXT, credential_encrypted BYTEA, credential_key_id TEXT,
  enabled BOOL DEFAULT true, status TEXT DEFAULT 'Unknown', last_error TEXT,
  timeout_ms INT DEFAULT 10000, created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);

-- tools (cached catalog)
CREATE TABLE tools (
  id UUID PRIMARY KEY, server_id UUID REFERENCES servers(id) ON DELETE CASCADE,
  upstream_name TEXT NOT NULL, exposed_name TEXT UNIQUE NOT NULL,
  description TEXT, input_schema JSONB NOT NULL, updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(server_id, upstream_name)
);

-- permissions (per-tool RBAC, optional but do it)
CREATE TABLE permissions (
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  server_id UUID REFERENCES servers(id) ON DELETE CASCADE,
  tool_exposed_name TEXT, effect TEXT CHECK (effect IN ('allow','deny')) NOT NULL DEFAULT 'allow',
  PRIMARY KEY (user_id, server_id, tool_exposed_name)
);

-- audit_logs (partitioned monthly in prod)
CREATE TABLE audit_logs (
  id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  user_id UUID REFERENCES users(id), api_key_id UUID REFERENCES api_keys(id),
  server_id UUID, server_slug TEXT NOT NULL,
  tool_exposed_name TEXT NOT NULL, tool_upstream_name TEXT NOT NULL,
  request_id UUID NOT NULL, duration_ms INT NOT NULL,
  outcome TEXT CHECK (outcome IN ('success','upstream_error','permission_denied','timeout','circuit_open','validation_error')) NOT NULL,
  error_code TEXT, client_ip INET
);
CREATE INDEX ON audit_logs(ts DESC); CREATE INDEX ON audit_logs(user_id, ts DESC);
```

---

## 4. Auth: API Keys + RBAC

**Generation:**
```python
import secrets; from argon2 import PasswordHasher; import hashlib
ph = PasswordHasher()
raw = f"urumi_sk_{secrets.token_urlsafe(32)}"
sha = hashlib.sha256(raw.encode()).hexdigest()
hashed = ph.hash(raw)  # store hash + sha + last4
# return raw ONCE to user
```

**Verification (on every /mcp request):**
```python
async def verify_api_key(request: Request, db):
  key = request.headers.get("authorization","").removeprefix("Bearer ").strip() \
        or request.headers.get("x-api-key","").strip()
  if not key: raise HTTPException(401)
  sha = hashlib.sha256(key.encode()).hexdigest()
  row = await db.fetch_one("SELECT * FROM api_keys WHERE sha256=:sha AND revoked_at IS NULL", {"sha":sha})
  if not row or not ph.verify(row.hash, key): raise HTTPException(401, "invalid key")
  if row.expires_at and row.expires_at < now(): raise HTTPException(401, "expired")
  return await get_user(row.user_id)
```

**RBAC:**
```python
def require_admin(user=Depends(get_current_user)):
  if user.role != "admin": raise HTTPException(403)
  return user
# Apply to POST/PATCH/DELETE /api/servers, /api/users, revocation
```

---

## 5. SSRF Validator (must be on every upstream URL write AND read)

```python
import ipaddress, socket, asyncio
from urllib.parse import urlparse

BLOCKED_NETS = [ipaddress.ip_network(c) for c in [
  "127.0.0.0/8","10.0.0.0/8","172.16.0.0/12","192.168.0.0/16",
  "169.254.0.0/16","100.64.0.0/10","::1/128","fc00::/7","fe80::/10"
]]
BLOCKED_HOSTS = {"metadata.google.internal","metadata.google","instance-data","169.254.169.254"}

def validate_url(url: str):
  p = urlparse(url)
  if p.scheme not in ("https","http"): raise ValueError("Only http/https")
  if "@" in p.netloc: raise ValueError("userinfo not allowed")
  host = p.hostname
  if not host or host.lower() in BLOCKED_HOSTS: raise ValueError("Blocked host")
  if host == "localhost": raise ValueError("localhost not allowed")
  # optional allowlist: if ALLOWED_DOMAINS set, enforce suffix match

async def resolve_and_validate(host: str):
  infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
  for _,_,_,_,(ip, *_) in infos:
    ip_obj = ipaddress.ip_address(ip)
    if any(ip_obj in n for n in BLOCKED_NETS) or ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
      raise ValueError(f"Blocked IP {ip}")
```

- Call `validate_url` at `POST /api/servers` and `PATCH`.
- Call `resolve_and_validate` inside `proxy_call` before opening httpx connection (TOCTOU prevention).
- `follow_redirects=False` (re-validate redirect target if you enable).

---

## 6. MCP Aggregation Details

### 6.1 Collision — Prefix

```
exposed_name = f"{slug}__{upstream_name}"   # woo__list_products, time__get_current_time
description  = f"[{slug}] {upstream_desc}"
```

- Persist mapping in `tools` table; route by splitting on `__`.
- Document: "Two servers with same tool name get distinct prefixed names."

### 6.2 Timeout & Isolation

```python
# per-server httpx client
httpx.AsyncClient(timeout=httpx.Timeout(connect=2, read=10, write=5, pool=2))

# fan-out with isolation
results = await asyncio.gather(*[fetch(s) for s in servers], return_exceptions=True)
# fetch wraps call in asyncio.wait_for(8)

# tools/call
async def call_tool(user, exposed_name, args):
  if not can_call(user, exposed_name): audit(..., "permission_denied"); raise 403
  slug, orig = exposed_name.split("__", 1)
  server = await get_by_slug(slug)
  if breaker.is_open(server.id): raise 503
  try:
    result = await asyncio.wait_for(proxy(server, orig, args), timeout=10)
  except TimeoutError: breaker.fail(server.id); audit(..., "timeout"); raise 504
```

### 6.3 Credential Injection (server-side only)

```python
from cryptography.fernet import Fernet
fernet = Fernet(settings.FERNET_KEY)  # from K8s Secret

def encrypt(plaintext: str) -> bytes: return fernet.encrypt(plaintext.encode())
def decrypt(cipher: bytes) -> str: return fernet.decrypt(cipher).decode()

# at proxy time:
creds = decrypt(server.credential_encrypted)  # cached 60s in memory LRU
headers = {}
if server.auth_type == "bearer": headers["Authorization"] = f"Bearer {creds}"
elif server.auth_type == "header": headers[server.header_name] = creds
# never log headers, never return credential in API
```

---

## 7. Audit Queue (async, never blocks tool call)

```python
audit_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)

async def audit_worker():
  batch = []
  while True:
    try:
      item = await asyncio.wait_for(audit_queue.get(), timeout=1.0)
      batch.append(item)
      if len(batch) >= 100: await flush(batch); batch.clear()
    except asyncio.TimeoutError:
      if batch: await flush(batch); batch.clear()

async def log_audit(**kw):
  try: audit_queue.put_nowait(kw)
  except asyncio.QueueFull: logger.error("audit queue full, dropping")
```

- Every `tools/call` (and chat's internal calls) logs: `user_id, api_key_id, server_slug, tool, duration_ms, outcome, request_id`.

---

## 8. Lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
  app.state.audit_task = asyncio.create_task(audit_worker())
  app.state.health_task = asyncio.create_task(health_loop())
  yield
  app.state.audit_task.cancel(); app.state.health_task.cancel()
```

---

## 9. Routes Summary

| Method | Path | Auth | Description |
|---|---|---|---|
| POST, GET | `/mcp` | Bearer API key | Streamable HTTP MCP |
| GET | `/api/servers` | session | list servers (credential masked) |
| POST | `/api/servers` | admin | create (SSRF validate, encrypt cred, probe) |
| PATCH | `/api/servers/:id` | admin | edit |
| POST | `/api/servers/:id/disable` | admin | disable -> tools vanish |
| DELETE | `/api/servers/:id` | admin | remove |
| GET | `/api/tools` | session | aggregated catalog for chat |
| GET | `/api/audit` | admin/member (own) | audit log |
| POST | `/api/users` | admin | invite |
| POST | `/api/keys` | self | generate own key |
| DELETE | `/api/keys/:id` | owner/admin | revoke |
| POST | `/api/chat/completions` | session | LLM tool loop |

---

## 10. Three Upstream Servers (satisfies "at least 3")

| # | Server | Why chosen | Tools example |
|---|---|---|---|
| 1 | **woo-mcp** (custom) | Required, Woo products/orders | 6 tools above |
| 2 | **time-mcp** (`mcp/time` or custom `time` server) | Trivial, proves cross-server aggregation, deterministic | `get_current_time`, `convert_time` |
| 3 | **memory/github-mcp** (or tiny custom `notes` MCP) | Shows second domain, enables "2-server prompt" demo | `search_notes`, `create_note` OR `list_repos`, `search_issues` |

Pick ones that are **fast, free, no API key** to reduce demo flake (avoid GitHub rate limits; `time` + `memory` are perfect).
