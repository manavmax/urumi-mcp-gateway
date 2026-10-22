# VPS upgrade checklist — first upgrade to the RC build (rc-verify branch)

One page, exact order, placeholders for private values. Everything here was
rehearsed on kind (see docs/UPGRADE_ROLLBACK.md "RC rehearsal"); the VPS steps
are the same commands with the private values filled in. Run from a machine
with `kubectl`/`helm` pointed at the VPS k3s and `docker login` to ghcr.io.
Safety: never paste secrets into the shell history or this file.

Assumptions: release name `urumi`, namespace `urumi`, current release deployed
from the old build (bonus-all base). Adjust `NAMESPACE`/`RELEASE` if different.

## 0. Preconditions (5 min)
- [ ] VPS reachable only via SSH; `kubectl config current-context` shows the
      VPS context (NOT kind-*). All commands below run against it.
- [ ] Disk has >= 2x the database size free (for the dumps).
- [ ] Note the current release state: `helm history urumi -n urumi | tail -3`.

## 1. Take BOTH dumps (Postgres + MariaDB) and the uploads volume
```bash
# Postgres (gateway: users, keys, servers, audit, oauth, ...)
kubectl exec urumi-postgres-0 -n urumi -- \
  sh -c 'pg_dump -U urumi -d urumi -Fc -f /tmp/urumi-pre-upgrade.dump'
kubectl cp urumi/urumi-postgres-0:/tmp/urumi-pre-upgrade.dump \
  urumi-pre-upgrade-$(date +%F).dump -c postgres

# MariaDB (store database)
kubectl exec urumi-mariadb-0 -n urumi -- sh -c \
  'mariadb-dump -u wordpress -p"$MARIADB_PASSWORD" wordpress --single-transaction --routines --triggers > /tmp/store-dump.sql'
kubectl cp urumi/urumi-mariadb-0:/tmp/store-dump.sql store-dump.sql -c mariadb

# WordPress uploads volume (files, not in either dump)
kubectl exec deploy/urumi-wordpress -n urumi -- \
  tar cz - /var/www/html/wp-content/uploads > uploads-$(date +%F).tgz

# Record the pre-upgrade state for the post-upgrade comparison:
kubectl exec urumi-postgres-0 -n urumi -- psql -U urumi -d urumi -t -A -c \
  "SELECT version_num FROM alembic_version"          # -> <pre-upgrade head>
kubectl exec urumi-mariadb-0 -n urumi -- sh -c \
  'MYSQL_PWD="$MARIADB_PASSWORD" mariadb -u wordpress -N -e \
   "SELECT COUNT(*) FROM wp_posts WHERE post_type=\"product\"; \
    SELECT COUNT(*) FROM wp_posts WHERE post_type=\"shop_order\" AND post_status NOT IN (\"trash\");"'
```
Keep `urumi-pre-upgrade.dump`, `store-dump.sql`, `uploads-*.tgz` somewhere off
the VPS (scp them to your machine).

## 2. Build + push images with NEW tags (never :latest)
From your machine (linux/amd64 via buildx; the push script verifies the
registry platform and fails otherwise):
```bash
NEW_TAG=<yyyy-mm-dd-rcN>            # placeholder, e.g. 2026-10-23-rc1
GHCR_OWNER=<your-ghcr-user>         # placeholder
# build + push every CHANGED image (at minimum gateway + dashboard for this
# build; demo-mcp-time changed between main and bonus-all; check with
# git diff --stat <old-tag>..rc-verify -- src/):
DOCKER_CONTEXT=default bash scripts/push-images.sh   # prompts for the GHCR token on stdin
# the script ends with the imagetools inspect verification per image; a push
# without linux/amd64 exits non-zero. Then pin the tag (never :latest).
```

## 3. Update the private values file
```yaml
# values-vps.yaml (private, never committed) - placeholders only
gateway:
  image:
    tag: "<NEW_TAG>"          # was the old build tag
dashboard:
  image:
    tag: "<NEW_TAG>"
demoTime:
  image:
    tag: "<NEW_TAG>"
# Woo MCP / demo-notes / wordpress / wp-cli / store-assets: leave at their
# current tags unless those images changed too.
# RC shape for the FIRST upgrade to this build - every new flag FALSE:
provisioner:
  enabled: false
hostedServers:
  enabled: false
oauth:
  enabled: false
gateway:
  replicas: 1                 # stateful pods stay at 1; raise gateway later if wanted
```
Only the tags and the (already false) flags change; domains, storageClass and
Secrets stay as they are in the private file.

## 4. Upgrade
```bash
helm upgrade urumi ./helm -n urumi -f values-vps.yaml \
  --timeout 15m --rollback-on-failure --wait
```
- Flags stay FALSE on the first upgrade: no provisioner/hosted/oauth components
  render; only the gateway + dashboard roll and migrations 007→011 run.
- If the upgrade fails, helm rolls back automatically — check
  `helm history urumi -n urumi` and the gateway logs before retrying.

## 5. Post-upgrade checks (in this order)
1. **Schema version line in the gateway logs** (the ADR-061 gate):
   `kubectl logs -n urumi -l app=gateway --tail=50 | grep "schema version verified"`
   → expect `schema version verified: db=011_oauth code=011_oauth (separate connection)`.
   If instead you see `SCHEMA VERSION CHECK FAILED` — STOP, do not retry
   blindly; the DB is behind or ahead of the code (docs/UPGRADE_ROLLBACK.md).
2. **readyz**: `kubectl exec -n urumi deploy/urumi-gateway -c gateway -- \
   python3 -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/readyz').read().decode())"`
   → `{"status":"ready"}`.
3. **Login**: dashboard sign-in works (admin user, wrong password → 401).
4. **Old API key still works**: one MCP tools/call with an existing key → 200;
   a previously revoked key → 401.
5. **Stored upstream credential still works**: call one tool on the
   credentialed upstream (e.g. notes__list_notes) → 200.
6. **Order still visible**: the storefront shows the last order / admin sees it
   in WooCommerce; `mariadb` count check as in step 1 (same numbers).
7. **regress-core on the VPS**: `NAMESPACE=urumi bash scripts/regress-core.sh`
   → ALL CHECKS PASSED (it needs the pods Ready and kills the demo-time pod
   briefly; run it during a quiet minute).

## 5. If anything fails
- Upgrade failed → `--rollback-on-failure` already restored the previous
  revision; pods run the OLD images; database stays at the NEW schema
  (forward-only). Old code works on it (all migrations additive - proven).
- Need the old DATA back: restore the pg_dump + mariadb-dump per
  docs/UPGRADE_ROLLBACK.md (gateway scaled to 0 during the restore).
- The gateway refuses to start with "SCHEMA VERSION CHECK FAILED"?  The DB is
  behind or ahead of the code head - that is the gate doing its job; restore
  the matching dump or re-apply the newer release.

## One-line summary
dumps (pg + mariadb + uploads) → build/push new tags (platform-verified) →
values file with flags false → `helm upgrade --rollback-on-failure --wait` →
schema-verified log line + readyz + login + key + order + regress-core.
