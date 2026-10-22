# Urumi AI — MCP Gateway on Kubernetes (Brain Docs)

> **Status:** Days 0-7 complete and verified live on Kind — store + MariaDB + Ingress + setup Job + Woo MCP server (Layer 2: 8 tools) **and Layer 3** (gateway + dashboard + 3-server `/mcp` aggregation, `verify-gateway` 23/23 PASS + `make test` 29 unit tests). Days 8-9 (chat exit demo) are code-complete but un-demonstrated: the LLM key is empty by design until an operator supplies one (ADR-022). Take-home due **26 Oct 2026, 11:59 PM IST**.

## What This Is

The assignment: **WooCommerce hosting + Team MCP Gateway on Kubernetes + Helm**, with a custom Woo MCP server, a gateway that aggregates N Streamable-HTTP servers behind one `/mcp` endpoint, a React dashboard, and a chat agent that calls tools via the gateway as the logged-in user.

Evaluation: working core > unfinished bonus; must demo E2E with 2 users (chat + MCP client), revocation, disable, kill-pod isolation, audit log.

## How to Navigate the Brain

| Doc | Read When |
|---|---|
| `docs/00_OVERVIEW_AND_TRACEABILITY.md` | First — traceability matrix, DoD demo script, mandatory checklist, stack, bonus gate |
| `docs/01_ARCHITECTURE.md` | Boxes/arrows: 4 layers, 3 request flows, topology, resource table |
| `docs/02_MCP_PROTOCOL.md` | MCP Streamable HTTP wire (initialize/tools/list/call), aggregation, collision, SDK |
| `docs/03_WOOCOMMERCE_MCP_SERVER.md` | 6 tools contract, Woo REST vs WP-CLI vs DB, K8s wiring |
| `docs/04_GATEWAY_BACKEND.md` | Gateway modules, data models, auth/SSRF/audit/breaker |
| `docs/05_DASHBOARD_AND_CHAT_AGENT.md` | React pages, chat server-side tool loop, SSE, anti-injection |
| `docs/06_KUBERNETES_AND_HELM.md` | Kind vs k3s, Helm chart, Ingress/hosts, probes, NP, PVC |
| `docs/05a_DAY_0-2_CHECKLIST.md` | **Day 0-2 done + verified** — what shipped, gotchas solved, what's left |
| `docs/05b_DAY_3-4_CHECKLIST.md` | **Day 3-4 done + verified** — Woo MCP (Layer 2): 6 tools, probes, isolation, error mapping |
| `docs/DECISIONS.md` | Decision log (ADR): why each choice, with rejected alternatives |
| `docs/07_SECURITY_AND_THREAT_MODEL.md` | 6 threats + mitigations, interview talk-track (long form of `THREAT_MODEL.md`) |
| `docs/08_IMPLEMENTATION_ROADMAP.md` | 14-day day-by-day plan with exit criteria |
| `docs/09_STAND_OUT_AND_BONUS.md` | Which bonuses to pick (depth > breadth), multi-store summary |
| `docs/10_BONUS_MULTI_STORE.md` | Full multi-store provisioning blueprint (optional bonus, gated) |
| `SYSTEM_DESIGN_AND_TRADEOFFS.md` | Required short note (tradeoffs + prod deltas) |
| `THREAT_MODEL.md` | Required short note (4 threats + SSRF table) |

## Quick Demo Script (what you will record)

1. Store: open `store.<domain>` → add to cart → COD checkout → Woo Admin order visible.
2. Chat as User A: "create product Urumi Tee $29.99" → storefront shows it; hand-place order; "what orders today?" → returns it.
3. Inspector as User B (gateway URL + other key): `tools/list` shows all 3 servers; same orders question succeeds; one prompt uses 2 servers.
4. Control: revoke B's key → 401; disable a server → tools vanish; kill woo-mcp pod → others work, dashboard Unreachable; audit shows all calls.

## Tech Stack (Python)

Python 3.12 · FastAPI · `mcp` SDK · `httpx` · Postgres 16 + SQLAlchemy async · React 18 + Vite + TS + Tailwind + TanStack Query · OpenAI `gpt-4o-mini` (swappable) · Kind (local) + k3s (VPS) · ingress-nginx · Helm (no Kustomize).

## Local Setup (verified)

```bash
make kind-up                                  # kind create cluster --name urumi --config kind-config.yaml
make ingress                                  # ingress-nginx for kind
make helm-local                              # secrets-local + helm upgrade --install (runs wp-setup hook)
make woo-mcp-image                            # Layer 2: build + import woo-mcp image into the kind node
make smoke-images                             # build all 8 images host-platform + per-image smoke test (no push)
make verify-store                             # lint, ps, wp-setup logs, store curl, woo-secrets
make verify-cod                               # COD offered at checkout (Store API) + COD option value
make verify-mcp                               # Layer 2: MCP handshake, 6 tools, error mapping, isolation
open http://store.127.0.0.1.nip.io             # title: "Urumi Store" (COD checkout works)
# MCP Inspector against the Woo MCP server:
kubectl port-forward -n urumi svc/urumi-woo-mcp 8000:8000   # then connect to http://localhost:8000/mcp
```

VPS is the same `helm/` + `helm/values-prod.yaml` (domain, storageClass, TLS). Full stranger-runnable walkthrough: **[docs/DEPLOY_VPS.md](docs/DEPLOY_VPS.md)**. Upgrade and rollback (rehearsed with real output): **docs/UPGRADE_ROLLBACK.md**.

## Credentials & LLM wiring (no committed secrets)

Every credential is chart-generated at install into a Secret (`lookup`-guarded, `helm.sh/resource-policy: keep`), never committed: `mariadb-secret`, `wordpress-secret`, `pg-secret`, `gateway-secrets`, `gateway-admin`, `gateway-llm`, `demo-notes-token`, `wordpress-admin`.

```bash
make admin-password            # WordPress admin (Secret wordpress-admin)
make gateway-admin-password    # Gateway dashboard admin (Secret gateway-admin)
kubectl get secret gateway-llm -n urumi -o jsonpath='{.data.OPENAI_API_KEY}' | base64 -d | wc -c   # length only, never print
```

The chat assistant's LLM endpoint is values, not code — `gateway.llm` in `helm/values.yaml`:

| value | default | meaning |
|---|---|---|
| `gateway.llm.enabled` | `true` | injects `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` into the gateway pod |
| `gateway.llm.baseUrl` | `https://api.openai.com/v1` | any OpenAI-compatible endpoint works (groq, together, vllm, ...) — no code change |
| `gateway.llm.model` | `gpt-4o-mini` | model name passed to the chat completions call |
| `gateway.llm.existingSecret` | `""` | optional prod override: name of a pre-created Secret holding key `OPENAI_API_KEY`; when set the chart renders no `gateway-llm` Secret |

No API key is committed anywhere. The chart renders a `gateway-llm` Secret whose `OPENAI_API_KEY` is **empty until an operator supplies a real one** — deliberately not `randAlphaNum`, because a generated string is a guaranteed-invalid key and the honest failure is "chat is not configured" (ADR-022).

**Data that leaves the cluster (updated by F3):** chat text goes to the configured LLM provider, and attached chat images now go to the SAME provider (they are expanded into vision parts of the LLM call server-side — the model never sees base64 text). Uploads are validated (magic bytes only: png/jpeg/webp, 5 MB cap, 4096 px per side, Pillow re-encode strips EXIF/GPS), stored in `chat_uploads` for 15 minutes, and never sent to Woo as raw bytes — woo-mcp forwards them to WordPress in-cluster. See THREAT_MODEL.md "Chat Image Uploads".

Apply a key. The recommended way asks for it with echo off, so it stays out of the shell history, any process list and any file:

```bash
printf 'Gemini API key (hidden): ' >&2
read -rs LLM_KEY
echo
kubectl -n urumi create secret generic gateway-llm --from-literal=OPENAI_API_KEY="$LLM_KEY" --dry-run=client -o yaml | kubectl apply -f -
unset LLM_KEY

# afterwards check the length, never the value:
kubectl get secret gateway-llm -n urumi -o jsonpath='{.data.OPENAI_API_KEY}' | base64 -d | wc -c
```

Rotating is the same command with a new key. In a script or CI, where the key already lives in a variable, skip the prompt:

```bash
kubectl -n urumi create secret generic gateway-llm --from-literal=OPENAI_API_KEY="$LLM_KEY" --dry-run=client -o yaml | kubectl apply -f -
```

**An upgrade never wipes the key.** Only the Secret's *existence* is unconditional; its *value* is `lookup`-guarded, so `helm upgrade` / `make helm-local` re-renders `gateway-llm` with the `OPENAI_API_KEY` already in the cluster instead of the empty default (ADR-016/022). Consequences worth knowing:

- A no-op upgrade is really a no-op: the value is unchanged, so `urumi.io/llm-secret-checksum` is unchanged, so the gateway pod is **not** restarted.
- `helm.sh/resource-policy: keep` means the Secret (and your key) survives `helm uninstall` and rollbacks.
- Only applying a *different* key changes the checksum, and that is what rolls the pod to pick up the new value.
- Nothing in `values.yaml` ever holds the key, so `git diff` and `helm get values` stay key-free; the chart's own file (`helm/templates/secrets.yaml`) says the same.

```bash
make verify-llm        # prove the live key: chat streams, multi-step tool loop, wrong-key error
```

Point `gateway.llm.existingSecret` at your own pre-created Secret (key `OPENAI_API_KEY`) to skip the chart-rendered one entirely.

## Tool permissions — restrict what members may call (ADR-033)

By default every member may use every tool of every enabled server (default
allow-all). Admins can restrict individual tools for the whole MEMBER role; admins
always have all tools.

**In the dashboard:** Servers → **Permissions** → tools grouped by server, one Member
toggle per tool (Admin is locked on for everyone) → **Save**. The restricted count is
shown in the panel head. Members see no permission UI; a restricted tool is simply
absent from their tools list, the Servers page and the member Overview "Tools I can use".

**With the API** (admin session cookie; the PUT is CSRF-protected, so grab the token
from `GET /api/auth/me`'s `csrf_token`):

```bash
TOKEN=$(curl -s -c /tmp/c.txt -X POST https://dashboard.<domain>/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@urumi.local","password":"..."}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["csrf_token"])')

# deny example: members keep woo__list_orders + woo__get_order, lose the write tools
curl -s -X PUT https://dashboard.<domain>/api/permissions \
  -b /tmp/c -H "X-CSRF-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"rules":[{"server_slug":"woo","tool_name":"woo__create_product"},
                {"server_slug":"woo","tool_name":"woo__update_order_status"}]}'

# allow everything again: empty rules list (or make demo-reset CONFIRM=yes)
curl -s -X PUT .../api/permissions -H "X-CSRF-Token: $CSRF" -d '{"rules":[]}'
```

Behaviour, in one paragraph: a denied tool disappears from `tools/list` for members and
a direct call to it is rejected with the standard unknown-tool error **before** any
upstream is contacted — the same enforcement core covers the external `/mcp` endpoint
and the chat agent, so a prompt-injection attempt that talks the model into naming a
denied tool is rejected too. Every denial is audited with outcome `permission_denied`.
Unknown server or tool names are rejected by the API (422); policy changes take effect
on the very next call (no cache). `make demo-reset` clears the table back to allow-all.

## Demo reset — `make demo-reset`

Between demo takes the cluster should be put back into a known state. `make demo-reset` does
that through official APIs only (Woo REST + the gateway's own models), it is **dry-run by
default**, and it refuses to run against anything but the local kind cluster.

```bash
make demo-reset                                # DRY RUN: prints what WOULD be deleted, changes nothing
make demo-reset CONFIRM=yes                    # performs the reset, then verifies 3 upstreams Connected + tools/list = 11
make demo-reset CONFIRM=yes ARGS=--with-demo-users   # additionally creates demo users A (admin) + B (member)
scripts/demo-reset.sh --check-only             # only the safety guard (exits 2 when it refuses)
```

The seed set (the products that survive) is an auditable file, not a hidden rule:
`scripts/demo-seeds.json` (the 12 SKUs of `store/products.json`). Everything not
matched there is test data.

| deletes | keeps |
|---|---|
| every WooCommerce product that is not a seed product (REST `force=true`) | the 12 seed products, store settings, COD, tax/shipping |
| every WooCommerce order (all statuses, incl. checkout drafts) | all Kubernetes Secrets and PVCs, and the Helm release (the script never runs `helm`) |
| every orphan media attachment (anything that is not a seed product's image; runs in the wordpress pod, ADR-040) | the seed product images |
| every row in `audit_logs` (ids restart at 1) | the gateway admin user `admin@urumi.local` and its API keys |
| every `tool_permissions` deny rule (back to default allow-all) | the 3 seeded upstreams `woo`/`time`/`notes`, their encrypted credentials, the Fernet state |
| every non-admin user + their API keys | any non-seeded server you added — it is listed in the summary, never deleted |
| all notes (in-memory store → `rollout restart` + `rollout status` of `urumi-demo-notes`) | |

Safety guarantees (ADR-032): refuses unless `kubectl config current-context` is a `kind-*`
cluster whose API server is on loopback and the namespace is `urumi`; the only cluster
object it mutates is the `urumi-demo-notes` Deployment; no credential is ever printed —
except the demo-user passwords/keys that `--with-demo-users` shows exactly once on the
terminal (never written to a file or log). A dry run only ever issues `kubectl get` /
`config` / `exec`; that invariant is pinned by `src/gateway/tests/test_demo_reset_safety.py`.

After a confirmed run the script prints a deleted/kept summary and verifies the demo
contract live: 3 upstreams `Connected` and `tools/list` returning 13 tools (woo 8, time 2,
notes 3).

## Storefront (urumi-store theme)

The public store at `http://store.127.0.0.1.nip.io` is a standalone block theme
(`store/theme/urumi-store/`, ADR-037) with a 12-product catalog defined in
`store/products.json`, the single source of truth for names, SKUs, prices, copy and
image alt text. Key properties:

- **Zero third-party requests.** Fonts (Instrument Serif + Inter, both OFL) are
  self-hosted woff2 inside the theme; emoji script, gravatar, oEmbed and resource
  hints are removed. `scripts/verify-store.mjs` asserts same-origin only, in a real
  browser.
- **Delivery.** Theme + catalog + images ship in a static `store-assets` image
  (`make store-assets-image`) that an initContainer copies onto the wp-content
  volume on every pod start (the official WordPress image never refreshes an
  existing wp-content volume; ADR-038).
- **Seeding.** The wp-setup Job seeds BY SKU from `products.json`, idempotently and
  without overwriting admin edits (`wpSetup.seedForce: "1"` forces back to the
  catalog; ADR-039). Product images are generated original illustrations
  (`scripts/gen-store-images.py`) that live in `store/images/` as
  `<sku>.png` + `<sku>-cutout.png`.
- **Swapping product photos.** Drop a new `<sku>.png` (same filename) into
  `store/images/`, rebuild the store-assets image and restart the WordPress pod.
  No code changes: the generator keeps existing files, and the seeder attaches
  what the catalog references. To push new copy/prices, edit `store/products.json`,
  then either re-run seeding (new/changed SKUs are created) or set
  `wpSetup.seedForce: "1"` for one upgrade to overwrite everything.
- **Payments.** Cash on delivery is the only enabled gateway and the checkout
  default; product reviews are off; guest checkout is allowed.
- **Verification.** `node scripts/verify-store.mjs` (pages, 12-tile grid, image
  loads, fonts, hero geometry, mobile overflow + overlay menu, add-to-cart,
  third-party + console, 12 screenshots into `artifacts/store/`) and
  `node scripts/verify-store-contrast.mjs` (WCAG rest/hover/focus, zero failures).

## Security posture (hardening pass, ADR-041..047)

Short version; the full model lives in `THREAT_MODEL.md` and the decisions in
`docs/DECISIONS.md` (ADR-041..047).

- **No root anywhere.** Every container and init container runs non-root with an
  explicit uid, all capabilities dropped, no privilege escalation, seccomp
  RuntimeDefault (one shared Helm helper, `podSecurity.workloads` values).
  WordPress runs as www-data (33) on unprivileged 8080 via the hardened image
  (`src/wordpress`); MariaDB runs as 999; the wp-setup hook runs as 33.
- **No tokens in pods.** One dedicated ServiceAccount per workload,
  `automountServiceAccountToken: false` everywhere except the wp-setup hook
  (secrets-only Role — it writes `woo-secrets` via the K8s API).
- **Default-deny NetworkPolicies**, ports values-driven; a throwaway pod is
  blocked from every private tier port while the gateway reaches its upstreams.
  Gateway egress is open to public 443 only (the LLM provider), RFC1918/metadata
  excluded.
- **Login lockout** (per username + per client IP, 5 fails/300s, 429, audited),
  session cookie HttpOnly/SameSite=lax with a prod `Secure` setting, and
  security headers with a strict CSP (no inline scripts) on both the dashboard
  nginx and the gateway API.
- **SSRF guard** on admin-added upstream URLs: validated at save AND resolved +
  re-checked at connect time, redirects never followed.
- **No secrets in git, values, or logs**: chart Secrets are generated on install
  (or operator-provided); the log scan in `scripts/verify-hardening.sh` checks
  pod logs for key-shaped strings and reports 0.

`bash scripts/verify-hardening.sh` prints the per-workload security table and
re-runs the live probes (uid/caps/ro-root/token + NetworkPolicy + lockout +
headers + pod-log scan).

## Landing page (apex host)

`src/landing/` is a one-page static site (plain HTML/CSS/vanilla JS, no build step) served at the
APEX domain by the `landing` component (ADR-080/083). Dark-first with a light toggle; zero external
requests, strict CSP, nginx non-root uid 101 on 8080.

```bash
make landing-image                              # build + import into the kind node
helm template urumi ./helm -n urumi -f helm/values-local.yaml | grep -c landing   # 22 lines when on
```

Enabling it in prod takes three things, in this order:

1. **The apex A record must point at this server BEFORE enabling** (e.g. `example.com -> <server IP>`;
   `www` is not used by the component).
2. Set `landing.host` to the bare domain (`--set landing.host=example.com` or an uncommitted
   overlay) and `landing.enabled=true` (values-prod only; `values.yaml` ships the flag OFF and
   `values-local.yaml` turns it on for kind at `127.0.0.1.nip.io`).
3. Upgrade: the chart renders a dedicated `landing` Deployment/Service/Ingress/NetworkPolicy
   (templates/landing-*.yaml). The apex certificate uses its OWN Secret (`landing.tlsSecret`,
   default `urumi-landing-tls`) because cert-manager issues one Certificate per Ingress.

**Flipping "Beyond the brief" items.** `src/landing/features.js` is the single config file: every
item ships `enabled: false`, and only `enabled: true` items render in the "Beyond the brief"
section (all-off hides the section). Flip an item ONLY after its branch actually merges, then
rebuild: `make landing-image` + restart `deployment/urumi-landing`. The same file also holds
`repoUrl` (announcement bar + nav), `gatewayUrl` (the hero MCP config; empty = derived from the
page host as `dashboard.<apex>/mcp`), `storeProductCount` (the store claim, so a count correction
never touches prose), and `videoUrl` (the demo video block stays hidden while empty; it renders
as a link out, never an embed, so the page keeps making zero external requests).

## Submission (when ready)

- Demo video (chapters: design, K8s, MCP internals, security, chat, local→VPS) + GitHub repo → https://forms.gle/nftwgyNeenSDmiRb6

## Next Step

`git add -A && git commit -m "Day 0-2: store on kind"`, then start `docs/08_IMPLEMENTATION_ROADMAP.md` Day 3-4 (`src/woo-mcp`). Core first, bonus only after Day 12 DoD passes twice.
