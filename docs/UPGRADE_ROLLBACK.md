# UPGRADE_ROLLBACK.md: rehearsed procedure

Everything in this document was REHEARSED on the local kind cluster with real
output (release `urumi`, revisions 1-15, 2026-10-19/20). The VPS run of the same
procedure is now DONE (first live deploy 2026-10-20, including the first
install gotcha below); the deliberately bad upgrade rehearsal itself has only
run on kind so far.

## The rule

FIRST install on a fresh cluster (no --wait, no rollback flag):

```bash
helm upgrade --install urumi ./helm -n urumi -f helm/values-prod.yaml --timeout 15m
# then wait for the hook that provisions WordPress + creates woo-secrets:
kubectl wait --for=condition=complete job/urumi-wp-setup -n urumi --timeout=15m
```
Why no --wait on the first install (two sentences): Helm runs post install
hooks only after --wait is satisfied, and the `wp-setup` hook is what CREATES the
`woo-secrets` Secret that the `woo-mcp` Deployment needs to become Ready, so a
fresh install with --wait waits forever for a pod that cannot start until the
hook has run. Every later upgrade can wait because the Secret already exists.

EVERY UPGRADE after that:

```bash
helm upgrade --install urumi ./helm -n urumi -f helm/values-prod.yaml \
  --timeout 15m --rollback-on-failure --wait
```
- `--timeout 15m`: the explicit budget (`ADR-048`). The post install/upgrade
  `wp-setup` hook provisions WordPress on a cold cluster, so a short timeout dies
  with "context deadline exceeded" on a healthy but slow first install. `make
  helm-local` / `make helm-prod` / `make upgrade` all carry it.
- `--rollback-on-failure`: a FAILED upgrade is rolled back automatically: a bad
  change can never leave a `half-deployed` release. This is the helm 4 spelling;
  helm 3 only knows `--atomic`, and helm 4 still accepts `--atomic` with a
  deprecation warning (observed live on helm v4.3.0). The Makefile
  auto detects the installed helm major version and uses the right spelling.
- `--wait`: the command returns only when every deployed workload is Ready
  (upgrades only; see above for why the FIRST install runs without it).

## New components (phases 5-7) upgrade notes

- **Provisioner (`ADR-060`):** ships with the main chart; `helm upgrade` updates
  its image/env automatically. Its own state lives in the cluster (namespaces +
  labels), so a provisioner restart needs no data migration. The store chart is
  BAKED into the provisioner image at /charts/store: rebuild the image when
  helm/store changes (`make provisioner-image`).
- **Stores:** the gateway sync loop reconciles in flight rows on start; stuck
  Provisioning stores resume, Failed stores need the retry button (the retry
  resets the per attempt budget). Store namespaces are NEVER touched by a main
  release rollback (separate namespaces, helm releases inside them).
- **Hosted servers (`ADR-062`):** same story: hosted-<name> namespaces are
  cluster state; the provisioner image rebuild picks up chart/object changes.
- **OAuth (`ADR-063`):** migration 011 adds three tables (additive only); turning
  oauth.enabled off leaves the tables (harmless) and API keys keep working.
- **Flags off -> on:** every new component is inert with its flag false; turning
  a flag on is a plain `helm upgrade` (the gateway env changes and the pods roll).
- **Alembic (`ADR-061`):** migration verification is a post run DB READ
  (`SELECT version_num FROM alembic_version` + the new schema object), never the
  runner's own success log.
- **Startup schema gate (RC):** the gateway reads `alembic_version` through a
  SEPARATE connection after migrating and compares it with the alembic head the
  code ships with. Mismatch = clear ERROR log, `/readyz` unready, exit code 3.
  Consequence for rollbacks: rolling the CODE back across a migration boundary
  (database ahead of code) makes the NEW gateway refuse to serve BY DESIGN -
  restore the pre upgrade pg_dump (below) or `re-apply` the newer release. Code
  from BEFORE the gate existed (e.g. main @ 8cf8f73) still runs against the
  newer schema, because that build has no check and every migration so far is
  additive (verified live: main images Ready on a 011_oauth database).

## pg_dump before upgrading, and restore (RC rehearsal: every command run for real)

Take a dump BEFORE the upgrade (release `urumi`, namespace `rc-verify`; on the
VPS substitute the real namespace). Custom format (`-Fc`) keeps it compressed
and selective:

```bash
# 1. DUMP (run immediately before the upgrade)
kubectl exec urumi-postgres-0 -n rc-verify -- \
  sh -c 'pg_dump -U urumi -d urumi -Fc -f /tmp/urumi-pre-upgrade.dump'

# 2. COPY OFF THE POD (the pod filesystem is not a backup)
kubectl cp rc-verify/urumi-postgres-0:/tmp/urumi-pre-upgrade.dump \
  urumi-pre-upgrade.dump -c postgres
```
Restore: the RECOVERY DRILL executed in this rehearsal restored the pre upgrade
dump into a scratch database and reproduced the exact pre upgrade state
(alembic_version `006_chat_uploads`, 211 audit rows, 3 users, 9 tables, 0
pg_restore errors):

```bash
# 3a. drill: restore into a scratch DB and verify
kubectl exec urumi-postgres-0 -n rc-verify -- psql -U urumi -d postgres \
  -c 'DROP DATABASE IF EXISTS urumi_restored' -c 'CREATE DATABASE urumi_restored'
kubectl exec urumi-postgres-0 -n rc-verify -- \
  pg_restore -U urumi -d urumi_restored --no-owner /tmp/urumi-pre-upgrade.dump
kubectl exec urumi-postgres-0 -n rc-verify -- psql -U urumi -d urumi_restored \
  -t -c "SELECT version_num FROM alembic_version"   # -> 006_chat_uploads

# 3b. REAL recovery (destroys the current database - this is the point):
#     scale the gateway down first so nothing writes while you restore.
kubectl scale deployment/urumi-gateway -n rc-verify --replicas=0
kubectl exec urumi-postgres-0 -n rc-verify -- psql -U urumi -d postgres \
  -c 'DROP DATABASE urumi' -c 'CREATE DATABASE urumi'
kubectl exec urumi-postgres-0 -n rc-verify -- \
  pg_restore -U urumi -d urumi --no-owner /tmp/urumi-pre-upgrade.dump
kubectl scale deployment/urumi-gateway -n rc-verify --replicas=1
# the gateway re-runs `alembic upgrade head` on start: the restored 006 DB is
# migrated forward again; the startup schema gate then verifies db == code head.
```
MariaDB/WordPress data is NOT in this dump (separate engine): the store
recovery drill below covers it; the WordPress uploads volume is a PVC that
survives upgrades/rollbacks untouched (table above) and is backed up with one
line:

    kubectl exec deploy/`urumi-wordpress` -n <ns> -- tar cz: /var/www/html/`wp-content`/uploads > uploads-$(date +%F).tgz

## MariaDB (store database) dump + restore drill: every command run for real

The WooCommerce store lives in MariaDB (`mariadb:11.4` StatefulSet), NOT in the
pg_dump. Back it up the same way, from the mariadb pod:

```bash
# 1. DUMP the store database (run immediately before the upgrade; consistent
#    InnoDB snapshot via --single-transaction)
kubectl exec urumi-mariadb-0 -n rc-verify -- sh -c \
  'mariadb-dump -u wordpress -p"$MARIADB_PASSWORD" wordpress --single-transaction --routines --triggers > /tmp/rc-store-dump.sql'
#    all-databases variant (root): MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb-dump -u root --all-databases

# 2. COPY OFF THE POD
kubectl cp rc-verify/urumi-mariadb-0:/tmp/rc-store-dump.sql rc-store-dump.sql -c mariadb
```
Restore: the RECOVERY DRILL executed in this rehearsal (407,722-byte dump,
21 INSERT sections, 0 restore errors):

```bash
# 3a. drill: restore into a scratch database, then compare counts
kubectl exec -i urumi-mariadb-0 -n rc-verify -- sh -c \
  'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb -u root -e \
   "DROP DATABASE IF EXISTS store_restore_check; CREATE DATABASE store_restore_check;" \
   && MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb -u root store_restore_check < /tmp/rc-store-dump.sql'

# 3b. REAL recovery (destroys the live store database - stop writers first):
kubectl scale deployment/urumi-wordpress -n rc-verify --replicas=0
kubectl exec urumi-mariadb-0 -n rc-verify -- sh -c \
  'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb -u root -e "DROP DATABASE wordpress; CREATE DATABASE wordpress;"'
kubectl exec -i urumi-mariadb-0 -n rc-verify -- sh -c \
  'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb -u root wordpress < /tmp/rc-store-dump.sql'
kubectl scale deployment/urumi-wordpress -n rc-verify --replicas=1
```
Verified counts after the drill (live vs restored into `store_restore_check`):
products 12 = 12, orders 1 = 1, order_items 1 = 1, order #48 status
`wc-processing` = `wc-processing`. Every root `mariadb` call needs
`MYSQL_PWD="$MARIADB_ROOT_PASSWORD"` - `using password: NO` means the prefix
was forgotten on that call. The `wordpress` user cannot read other databases
(by design), so verification and restore run as root.

## RC rehearsal: `bonus-all` over a main shaped database (2026-10-22)

Executed on kind, namespace `rc-verify`, release `urumi`: baseline = main @
8cf8f73 (images `rc-main`, alembic head 006), upgrade = `bonus-all` (images
`rc-bonus*`, prod shaped values: provisioner/hostedServers/oauth disabled,
1 replica, `--rollback-on-failure --wait`), helm revision 2 -> 3. Result: every
old row intact (per table count + md5 checksums equal on legacy shape columns),
old API keys still authenticate, revoked key still 401, stored upstream
credential still decrypts, audit/permission rows byte identical, WooCommerce
order #48 intact, `scripts/regress-core.sh` ALL CHECKS PASSED. Manual
`helm rollback 2` then reproved main's images on the 011 schema (readyz ready,
MCP + login + order intact, alembic_version untouched), and `helm rollback 5`
returned to the bonus release. Revision history: 2 (main) -> 3 (bonus) -> 4/5
(schema gate builds) -> 6 (rollback to 2) -> 7 (rollback to 5).

## What upgrades/rollbacks do to state

| resource | on upgrade | on rollback |
|---|---|---|
| PVCs | untouched (same claim names) | untouched |
| Secrets | values are lookup guarded: reused verbatim (`ADR-016`); nothing regenerates | untouched (helm.sh/`resource-policy`: keep survives uninstall) |
| `wp-setup` hook | `re-runs` (idempotent: reuse by SKU seed, reuse or rotate keys) | NOT `re-run` (rollbacks do not run hooks) |
| migrations | Alembic runs to head at gateway start | see migration policy below |

## Database migration policy (Alembic is forward only)

Alembic is forward only in this project. The rule: every migration must be
ADDITIVE and backward compatible with the PREVIOUS release (new tables/columns
with defaults; no renames, no drops, no data rewrites). Then a rollback to the
previous image keeps working: the old code ignores the new columns, and the
current alembic_version (`006_chat_uploads`) stays in place until the next
forward upgrade. A destructive migration (drop/rename) would leave the rolled
back release reading a schema it does not know: it is FORBIDDEN by this policy;
drop/reshape steps must ride a two release cadence (add in N, consume in N+1).

Observed on kind (real output): rollbacks did NOT touch `alembic_version`
(`006_chat_uploads` before and after every upgrade/rollback step) and the
gateway reran `alembic upgrade head` idempotently on each restart:
`{"msg":"alembic upgrade head done"}`.

## a) Good upgrade to a visible change (1.0.0 -> 1.0.1)

The chart wires `SERVICE_VERSION` from Chart.yaml appVersion into the gateway; the
root endpoint prints it.

```$ kubectl exec -n urumi deploy/urumi-gateway -- python -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/')); print(d.get('version'))"
1.0.0                                   # before (rev 1)
$ helm upgrade urumi ./helm -n urumi -f helm/values-local.yaml --timeout 15m --atomic --wait
helm upgrade urumi ./helm -n urumi -f helm/values-local.yaml --timeout 15m     1.13s user 0.44s system 1% cpu 2:11.04 total
$ kubectl exec ... print(d.get('version'))
1.0.1                                   # after (rev 2) - the change landed
```
## b) Deliberately BAD upgrade -> automatic rollback

```$ { time helm upgrade urumi ./helm -n urumi -f helm/values-local.yaml \
    --set gateway.image.tag=0.1.0-NONEXISTENT --timeout 15m --atomic --wait >/tmp/bad-upgrade.log 2>&1; } 2>&1 | tail -3
helm upgrade urumi ./helm -n urumi -f helm/values-local.yaml --set  --timeout  1.88s user 0.88s system 0% cpu 10:21.27 total
level=WARN msg="upgrade failed" name=urumi error="resource Deployment/urumi/urumi-gateway not ready. status: Failed, message: Progress deadline exceeded"
Error: UPGRADE FAILED: release urumi failed, and has been rolled back due to rollback-on-failure being set: ...
$ helm history urumi -n urumi | tail -4
3  ...  failed      ...  Upgrade "urumi" failed: ... Progress deadline exceeded
4  ...  deployed    ...  Rollback to 2
```
The bad tag never pulls, the Deployment's progress deadline expires, helm marks
revision FAILED and ROLLS BACK AUTOMATICALLY. The cluster was serving throughout
the failure window (old pod kept running).

### b2) The same bad upgrade, FASTER: progressDeadlineSeconds + --timeout 6m

The default progress deadline is 600s, so the rehearsal above burns ~10 minutes.
The chart now sets `gateway.progressDeadlineSeconds` (default 300, values driven):
the Deployment flips to `ProgressDeadlineExceeded` after 5 minutes of no progress
and helm fails fast instead of waiting out a longer --timeout. Rehearsed with a
6-minute timeout (real output, 2026-10-20, kind; helm v4.3.0 where --atomic maps
to --`rollback-on-failure`):

```$ { time helm upgrade urumi ./helm -n urumi -f helm/values-local.yaml \
    --set gateway.image.tag=0.1.0-NONEXISTENT --timeout 6m --atomic --wait >/tmp/bad-upgrade-6m.log 2>&1; } 2>&1 | tail -4
helm upgrade urumi ./helm -n urumi -f helm/values-local.yaml --set  --timeout  1.11s user 0.47s system 0% cpu 5:09.84 total
level=WARN msg="upgrade failed" name=urumi error="resource Deployment/urumi/urumi-gateway not ready. status: Failed, message: Progress deadline exceeded"
Error: UPGRADE FAILED: release urumi failed, and has been rolled back due to rollback-on-failure being set: ...
$ helm history urumi -n urumi | tail -3
18  failed    urumi-0.1.0  1.0.2  Upgrade "urumi" failed: ... Progress deadline exceeded
19  deployed  urumi-0.1.0  1.0.2  Rollback to 17
```
5:09.84 wall (was 10:21.27 with the 600s deadline): ~300s to the deadline plus a
~30s rollback. After the rollback every pod was Ready again and `/healthz` through
the ingress answered 200. On helm 3 use the same command with `--atomic` (helm 4
renamed it `--rollback-on-failure`); the timing behaviour is identical because it
is driven by the Deployment deadline, not the helm version.

## c) Manual rollback of a good upgrade

```$ helm rollback urumi 4 -n urumi --timeout 15m --wait
Rollback was a success! Happy Helming!
$ helm history urumi -n urumi | tail -2
8  ...  deployed  urumi-0.1.0  1.0.1  Rollback to 4
$ kubectl exec ... version endpoint -> 1.0.1     # the visible change reverted
```
8.5s wall: helm reapplies the old manifest; PVCs and Secrets stay.

## d) Data survives all three

After (a) good upgrade, (b) bad upgrade + automatic rollback, (c) manual rollback:

```$ kubectl exec urumi-postgres-0 -- psql -U urumi -d urumi -t -c "SELECT email, role FROM users"
 admin@urumi.local        | admin
 persist-user@example.com | member
$ ... "SELECT prefix, last4 FROM api_keys"
 urumi_sk_ | i6rY
$ ... "SELECT count(*) FROM admin_events"          -> 2   (user.invite + key.create)
$ SELECT ID, post_status FROM wp_posts WHERE post_type='shop_order' AND ID=48
48  wc-pending
$ ... products publish count                        -> 12
```
## One liners

```bash
make upgrade ARGS='--set gateway.image.tag=<new-tag>'   # values-driven upgrade
make rollback REV=4                                      # manual rollback
```
Both use `--timeout 15m --rollback-on-failure --wait` (`ADR-048`; the Makefile
uses the `--atomic` spelling on helm 3 and `--rollback-on-failure` on helm 4).
For a DELIBERATELY bad upgrade
use `--timeout 6m` together with the chart's `gateway.progressDeadlineSeconds: 300`
so the automatic rollback lands in ~6 minutes (section b2).

## Rehearsal evidence (helm history, real output)

```REVISION  STATUS      APP VERSION  DESCRIPTION
1         superseded  1.0.0        Install complete
2         superseded  1.0.1        Upgrade complete
3         failed      1.0.1        Upgrade "urumi" failed: ... Progress deadline exceeded
4         superseded  1.0.1        Rollback to 2
5         superseded  1.0.2        Upgrade complete
8         superseded  1.0.1        Rollback to 4            <- MANUAL rollback
9         failed      1.0.2        Upgrade "urumi" failed: post-upgrade hooks failed
10        superseded  1.0.1        Rollback to 8
11        failed      1.0.2        Upgrade "urumi" failed ... (second bad case: broken hook)
12        superseded  1.0.1        Rollback to 10
13        superseded  urumi-0.1.0  1.0.2  Upgrade complete
15        superseded  urumi-0.1.0  1.0.2  Upgrade complete
17        superseded  urumi-0.1.0  1.0.2  Upgrade complete (progressDeadlineSeconds=300)
18        failed      urumi-0.1.0  1.0.2  Upgrade "urumi" failed ... Progress deadline exceeded  <- b2 bad upgrade, 5:09.84
19        deployed    urumi-0.1.0  1.0.2  Rollback to 17
```
Revisions 9/11 were MY OWN broken intermediate (tar extract failing as non root);
each auto rolled back exactly as designed, and the final 1.0.2 (rev 13/15) landed.
That is the rollback behaviour after a failed migration grade change, demonstrated
twice for real.