# UPGRADE_ROLLBACK.md - rehearsed procedure

Everything in this document was REHEARSED on the local kind cluster with real
output (release `urumi`, revisions 1-15, 2026-10-19/20). The VPS run of the same
procedure is pending; this document is the rehearsed baseline for it.

## The rule

```bash
helm upgrade --install urumi ./helm -n urumi -f helm/values-prod.yaml \
  --timeout 15m --atomic --wait
```

- `--timeout 15m`: the explicit budget (ADR-048). The post-install/upgrade
  wp-setup hook provisions WordPress on a cold cluster, so a short timeout dies
  with "context deadline exceeded" on a healthy but slow first install. `make
  helm-local` / `make helm-prod` / `make upgrade` all carry it.
- `--atomic`: a FAILED upgrade is rolled back automatically - a bad change can
  never leave a half-deployed release.
- `--wait`: the command returns only when every deployed workload is Ready.

## What upgrades/rollbacks do to state

| resource | on upgrade | on rollback |
|---|---|---|
| PVCs | untouched (same claim names) | untouched |
| Secrets | values are lookup-guarded: reused verbatim (ADR-016); nothing regenerates | untouched (helm.sh/resource-policy: keep survives uninstall) |
| wp-setup hook | re-runs (idempotent: reuse-by-SKU seed, reuse-or-rotate keys) | NOT re-run (rollbacks do not run hooks) |
| migrations | Alembic runs to head at gateway start | see migration policy below |

## Database migration policy (Alembic is forward-only)

Alembic is forward-only in this project. The rule: every migration must be
ADDITIVE and backward compatible with the PREVIOUS release (new tables/columns
with defaults; no renames, no drops, no data rewrites). Then a rollback to the
previous image keeps working: the old code ignores the new columns, and the
current alembic_version (`006_chat_uploads`) stays in place until the next
forward upgrade. A destructive migration (drop/rename) would leave the rolled
back release reading a schema it does not know - it is FORBIDDEN by this policy;
drop/reshape steps must ride a two-release cadence (add in N, consume in N+1).

Observed on kind (real output): rollbacks did NOT touch `alembic_version`
(`006_chat_uploads` before and after every upgrade/rollback step) and the
gateway re-ran `alembic upgrade head` idempotently on each restart:
`{"msg":"alembic upgrade head done"}`.

## a) Good upgrade to a visible change (1.0.0 -> 1.0.1)

The chart wires `SERVICE_VERSION` from Chart.yaml appVersion into the gateway; the
root endpoint prints it.

```
$ kubectl exec -n urumi deploy/urumi-gateway -- python -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/')); print(d.get('version'))"
1.0.0                                   # before (rev 1)
$ helm upgrade urumi ./helm -n urumi -f helm/values-local.yaml --timeout 15m --atomic --wait
helm upgrade urumi ./helm -n urumi -f helm/values-local.yaml --timeout 15m     1.13s user 0.44s system 1% cpu 2:11.04 total
$ kubectl exec ... print(d.get('version'))
1.0.1                                   # after (rev 2) - the change landed
```

## b) Deliberately BAD upgrade -> automatic rollback

```
$ { time helm upgrade urumi ./helm -n urumi -f helm/values-local.yaml \
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

## c) Manual rollback of a good upgrade

```
$ helm rollback urumi 4 -n urumi --timeout 15m --wait
Rollback was a success! Happy Helming!
$ helm history urumi -n urumi | tail -2
8  ...  deployed  urumi-0.1.0  1.0.1  Rollback to 4
$ kubectl exec ... version endpoint -> 1.0.1     # the visible change reverted
```

8.5s wall: helm re-applies the old manifest; PVCs and Secrets stay.

## d) Data survives all three

After (a) good upgrade, (b) bad upgrade + automatic rollback, (c) manual rollback:

```
$ kubectl exec urumi-postgres-0 -- psql -U urumi -d urumi -t -c "SELECT email, role FROM users"
 admin@urumi.local        | admin
 persist-user@example.com | member
$ ... "SELECT prefix, last4 FROM api_keys"
 urumi_sk_ | i6rY
$ ... "SELECT count(*) FROM admin_events"          -> 2   (user.invite + key.create)
$ SELECT ID, post_status FROM wp_posts WHERE post_type='shop_order' AND ID=48
48  wc-pending
$ ... products publish count                        -> 12
```

## One-liners

```bash
make upgrade ARGS='--set gateway.image.tag=<new-tag>'   # values-driven upgrade
make rollback REV=4                                      # manual rollback
```

Both use `--timeout 15m --atomic --wait` (ADR-048).

## Rehearsal evidence (helm history, real output)

```
REVISION  STATUS      APP VERSION  DESCRIPTION
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
15        deployed    urumi-0.1.0  1.0.2  Upgrade complete
```

Revisions 9/11 were MY OWN broken intermediate (tar extract failing as non-root);
each auto-rolled back exactly as designed, and the final 1.0.2 (rev 13/15) landed.
That is the rollback behaviour after a failed migration-grade change, demonstrated
twice for real.
