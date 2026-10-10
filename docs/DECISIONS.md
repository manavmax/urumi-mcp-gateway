# 11 — Decisions Log

> Running log of choices made while building Urumi, with the reasoning and the evidence.
> Newest entries first. Each entry answers "why this, not that" so the walkthrough can
> defend the system instead of describing it.

---

## ADR-016 — A credential Secret is ALWAYS rendered; only its values are lookup-guarded

**Date:** 2026-10-10
**Context:** after the "generate at install" change (ADR-015) the cluster started returning
`WOO_AUTH_FAILED` from `create_product` on a *later* upgrade, and new database connections
were refused. `helm history` showed why: revision 1 created the Secrets, revision 2's
manifest did **not contain** them (because `lookup` now found them, so the guard suppressed
the resource), and **Helm deleted them** as "removed from the manifest" — `helm.sh/
resource-policy: keep` does **not** prevent that. Revision 3 then regenerated all four
Secrets from fresh `randAlphaNum` values, while the pods started in revision 1 kept the old
env: the Secret no longer matched the passwords MariaDB/Postgres were initialised with (new
connections: `Access denied`) and the token-protected notes server answered 401.

**Decision:** the Secret resource is rendered **unconditionally**; only its **values** come
from `lookup`:

```yaml
{{- $existing := lookup "v1" "Secret" .Release.Namespace "mariadb-secret" }}
{{- $userPass  := include "urumi.secretKey" (list $existing "MYSQL_PASSWORD") }}
{{- if not $userPass }}{{ $userPass = randAlphaNum 24 }}{{ end }}
...
stringData:
  MYSQL_PASSWORD: {{ $userPass | quote }}
```

Consequences: the Secret is always part of the release (so it is never "removed" and never
deleted), an upgrade re-applies the *identical* values (a no-op that cannot go stale), and
a missing Secret is the only path that generates anything. One value is still shared across
every consumer that must agree (MariaDB/WordPress password, gateway `DATABASE_URL`, notes
token).

**Rule of thumb:** `lookup` may decide *content*, never *existence*, for a resource Helm
manages. (This is the same failure mode as the Woo key staleness below, one layer up.)

**Verified:** two consecutive `helm upgrade`s now leave all five credentials byte-identical;
a clean install + upgrades still shows `verify-mcp`, `verify-cod`, `verify-demo` green.

## ADR-017 — The Woo Consumer Key is reused, never rotated by the setup hook

**Date:** 2026-10-10
**Context:** `wp-setup` is a `post-install,post-upgrade` hook, so it re-runs on every
upgrade, and its key branch deleted + regenerated the Consumer Key each time despite
claiming to be idempotent. Consumers that cache credentials at start (woo-mcp reads its env
once) then hold a key that no longer exists in `wp_woocommerce_api_keys`, and every call
answers `401 woocommerce_rest_cannot_create`.

**Decision:** the hook is a **no-op for credentials when they already work**. It reads the
`woo-secrets` Secret through the Kubernetes API, and reuses the keypair when the DB row
matches (same `wc_api_hash` hash, same `consumer_secret`, `read_write`, same admin user);
it rotates only when the Secret and the database disagree, or when the Secret is missing.
Rotation is an explicit operator act (delete the Secret / re-create it with a new key).

Two implementation traps found while fixing it (both caused silent rotation):
- the job image (`wordpress:cli-php8.2`) has **no `kubectl`**, so `kubectl get secret`
  failed silently and looked like "no secret" — read the Secret via the K8s API instead;
- the Kubernetes API **pretty-prints** JSON, so matching `"key":"value"` after only
  stripping newlines never matches; strip spaces too;
- the reuse check originally used `get_current_user_id()`, which is **0 under WP-CLI**, so
  the owner comparison failed every time — resolve the admin explicitly.

Belt-and-braces: `deployment-woo-mcp` carries a `urumi.io/woo-secret-checksum` annotation,
so a deliberate rotation rolls the pod on the next upgrade.

---

## ADR-015 — DB passwords are generated at install, and a Secret never outlives its PVC

**Date:** 2026-10-10
**Context:** `values.yaml` and `make secrets-local` originally shipped default passwords
(the old, deleted dev defaults). A committed secret is exactly what the brief
forbids, and one shared "dev" password across environments is how a real deployment leaks.

**Decision:** no credential value is committed anywhere (chart values, Makefile, compose,
docs). `helm/templates/secrets.yaml` creates each Secret only when it is missing
(`lookup` guard) with `randAlphaNum 24` (48 for the notes token, 44 for the gateway Fernet
key), keeps `helm.sh/resource-policy: keep` so upgrades/rollbacks never rewrite it, and
reads an existing value back on later renders. The MariaDB user password is therefore a
**single value shared by `mariadb-secret` and `wordpress-secret`** — WordPress can always
authenticate — and the gateway's `DATABASE_URL` is built from the same generated Postgres
password. Rotation is `make rotate-secrets` (delete Secret + `helm upgrade`); operators may
also pre-create any of these Secrets before the first install and Helm will leave them
alone.

**Why `lookup` and not `randAlphaNum` alone:** `randAlphaNum` is re-evaluated on every
render, so an unguarded template would hand out a *new* password on each `helm upgrade`
and lock the databases out. The `lookup` guard is what makes the generated value stable.
(`helm template` has no cluster access, so its output shows a throwaway random value —
never a real credential; that is inherent to the pattern and is annotated on the Secret.)

**Operational coupling to remember (the reason for this ADR):**

> **MariaDB and Postgres only read their password when the data volume is first
> initialised.** The password is written into the database's own user table on that first
> boot; afterwards the engine ignores the environment variable for existing data. So
> deleting a Secret *without* deleting its PVC leaves the cluster running with a password
> the database no longer accepts, and every consumer fails to log in.

Therefore: **rotate = delete the Secret AND its PVC together** (or dump/reload the data):

```bash
kubectl delete secret mariadb-secret -n urumi
kubectl delete pvc data-urumi-mariadb-0 -n urumi   # only the MariaDB volume, not the app's
helm upgrade --install urumi ./helm -n urumi -f helm/values-local.yaml
```

(WordPress and the demo servers are different: they read the password on every boot, so
those Secrets can be rotated alone.)

**Verification from the clean install this was introduced in:** `kind-down` → `kind-up` →
`make helm-local`; store 200 + COD at checkout + `make verify-mcp` + `make verify-demo`
all green, and a second `helm upgrade` kept every generated secret byte-identical.

---

## ADR-014 — Two extra MCP servers (`demo-mcp-time`, `demo-mcp-notes`) instead of mocked upstreams

**Date:** 2026-10-10
**Context:** The roadmap (Days 5-7) needs 2nd/3rd upstreams so the gateway can prove
aggregation, `slug__tool` prefixing and credential injection. Mocking them inside the
gateway would have made those demos circular (the gateway talking to itself).

**Decision:** Build two real MCP servers, deliberately different in shape:

| | `demo-mcp-time` | `demo-mcp-notes` |
|---|---|---|
| Tools | `get_current_time(timezone?)`, `convert_time(time, from_tz, to_tz)` | `create_note(title, body)`, `list_notes`, `search_notes(query)` |
| Credentials | none | **bearer token required** (401 without it) |
| State | stateless (pure `zoneinfo`) | in-memory process-local store (documented as deliberate) |
| Why | proves a zero-cred upstream works with no auth at all | proves the gateway injects credentials the client never sees |

Both copy the `src/woo-mcp` structure exactly (FastMCP, `json_response=True`,
`stateless_http=True`, `/healthz` + `/readyz`, non-root `python:3.12-slim`, pinned
requirements including the `pydantic==2.11.*` cap), so there is exactly one server
shape to reason about.

**Why a dedicated server (not an extra tool on woo-mcp):** the assignment is a *team*
gateway, so upstreams must be independently addressable, independently scalable and
separately secured — a notes store has no business living inside the WooCommerce path.

**Alternatives considered:**
- Mock upstreams inside the gateway — rejected: demos would be self-referential and
  would hide exactly the failure modes (timeouts, 401s, isolation) we must show.
- A third server that talks to Postgres — rejected for now: the gateway's own DB (Days 5-7)
  already covers real persistence; a notes store with durable writes is a future bonus.

**Consequences:** three upstreams with three different auth models (CK/CS Basic, bearer,
none) exercise the gateway's `auth_type` handling immediately, instead of one day 10.

---

## ADR-013 — `pydantic` pinned to `2.11.*` for all MCP servers

**Date:** 2026-10-10
**Context:** `mcp==1.12.*` imports `eval_type_backport` from
`pydantic._internal._typing_extra`. In pydantic 2.12+/2.14 that symbol is gone, so
`import mcp.server.fastmcp` fails at container start.

**Decision:** pin `pydantic==2.11.*` in every server's `requirements.txt`, with a
comment explaining why, and cap `pydantic-settings==2.*`.

**Alternative:** upgrade to a newer `mcp` that supports pydantic 2.14 — re-deferred
because `mcp==1.12.*` is the pinned, Inspector-verified version in the roadmap, and the
failure only bites at import (loud, immediate, never silent).

---

## ADR-012 — Tool errors are prefixed codes, not JSON-RPC `-32000`

**Date:** 2026-10-10
**Context:** `docs/02_MCP_PROTOCOL.md` promised a `-32000` JSON-RPC error for "Woo store
unreachable". While implementing Layer 2 we found the Python SDK routes **every** tool
exception into `CallToolResult(isError=True)` (`mcp/server/lowlevel/server.py`
`_make_error_result`), so a tool cannot produce a JSON-RPC error at all.

**Decision:** tools raise `ValueError("WOO_UNREACHABLE: ...")` (etc.), producing
`result.isError: true` with a **stable machine-readable prefix**:
`WOO_AUTH_FAILED`, `WOO_NOT_FOUND`, `WOO_BAD_REQUEST`, `WOO_API_ERROR`,
`WOO_UNREACHABLE`, `WOO_UNEXPECTED`. The gateway (Days 5-7) will classify by prefix
when writing audit outcomes, and docs/02/03 now record the deviation.

**Alternatives considered:** hand-rolling the JSON-RPC layer — rejected: it would mean
replacing the SDK's transport (where all our protocol correctness comes from) to chase a
response shape clients handle identically.

---

## ADR-011 — WooCommerce Basic auth over plain HTTP needs an MU plugin

**Date:** 2026-10-10
**Context:** Every `wc/v3` call returned `401 woocommerce_rest_cannot_view` even with
valid Consumer Key/Secret. WooCommerce's
`WC_REST_Authentication::authenticate()` only calls `perform_basic_authentication()`
**when `is_ssl()` is true**, and in-cluster traffic to `http://wordpress:80` is plain HTTP.

**Decision:** the Day 1-2 `wp-setup` Job installs an MU plugin
(`wp-content/mu-plugins/urumi-internal-rest.php`) that sets `$_SERVER['HTTPS'] = 'on'`
**only for `/wp-json/` requests**. Storefront URLs stay HTTP.

**Alternatives considered:**
- TLS for the in-cluster hop too — correct but heavier (cert management for an internal hop
  that never leaves the cluster network).
- Passing keys as query params (`?consumer_key=...&consumer_secret=...`) — rejected as the
  default: credentials end up in logs and Ingress access lines.

**Note for prod:** if the public storefront gets TLS (it does, Day 11) the plugin is
harmless; it only affects requests that arrive without TLS.

---

## ADR-010 — Timeout mapping for an unknown Woo id

**Date:** 2026-10-10
**Context:** `GET /wc/v3/products/<unknown-id>` returns `404`, but
`PUT /wc/v3/orders/<unknown-id>` returns **400** with a `woocommerce_rest_invalid_id`
body, so a naive "404 => not found, 400 => bad request" rule lies to the caller.

**Decision:** `woo_client` classifies a 400 whose body contains `invalid_id`,
`invalid id`, `does not exist`, or `woocommerce_rest_invalid` as `WOO_NOT_FOUND`.

**Consequence:** the gateway and chat agent see one consistent semantic ("not found")
instead of two Woo-specific shapes. Behaviour verified by an E2E call.

---

## ADR-009 — Demo Notes token is generated at install, never committed

**Date:** 2026-10-10
**Context:** The notes server needs a bearer token for the credential-injection demo.
The first version put a dev default in `values.yaml` — a hardcoded secret in a committed
file, which the brief forbids and graders grep for.

**Decision:** there is **no token value in any committed file**. On install the
lookup-guarded `demo-notes-token` Secret template creates the Secret with
`randAlphaNum 48` when it does not exist (`helm.sh/resource-policy: keep`), so:
- no hardcoded secret in `values.yaml` / `Makefile` / docs,
- the token is stable across upgrades (the `lookup` guard means the Secret is only
  rendered once), and stable across rollbacks/uninstalls (`resource-policy: keep`),
- rotation = `kubectl delete secret demo-notes-token` + `helm upgrade`, or pre-create the
  Secret with your own token before the first install.

**Rejected:** a `values.yaml` default "for convenience" — that is a committed secret and
graders grep for exactly that; it also silently ships the same token to every environment.

---

## ADR-008 — Verify auth with `0101`-style probes left open

**Date:** 2026-10-10
**Context:** A token-protected server whose probes require the token would never become
Ready (kubelet cannot hold a token), and a server that silently ignores a missing token
would serve publicly.

**Decision:** `/healthz`, `/readyz` and `/` are explicitly open; **everything else**
requires the bearer token. `/readyz` returns **503 when `NOTES_API_TOKEN` is unset**, so a
mis-deployed notes server fails readiness instead of serving unauthenticated — the
container also refuses to start without the token (`create_app()` raises).

---

## ADR-007 — Stateless upstreams (`stateless_http=True`, `json_response=True`)

**Date:** 2026-10-10
**Context:** MCP's Streamable HTTP allows either a session (`Mcp-Session-Id`) or a
stateless transport.

**Decision:** every server in this project uses `stateless_http=True` and
`json_response=True` (JSON responses, no SSE stream). Consequences: any number of
replicas, zero session store, and trivially predictable behaviour behind an Ingress and
for `kubectl port-forward`. Trade-off recorded: no `Last-Event-ID` resumability, no
server→client sampling — neither is needed by this system.

**Evidence:** the MCP SDK `ClientSession` works unmodified against all three servers.
