"""Gateway-side demo reset worker (runs INSIDE the gateway pod via kubectl exec).

Why this runs in the gateway pod: it needs DATABASE_URL + FERNET_KEY from the pod
environment and the gateway's own ORM models on /app, exactly like
scripts/verify-gateway.py. audit_logs has no HTTP API, so the truncation is done
through the same SQLAlchemy models the app itself uses - never raw SQL written by
hand against WordPress tables (that part of the reset goes through the Woo REST API,
see scripts/demo-reset-woo.py).

Modes
-----
--dry-run            read-only: print what WOULD change, change nothing
--reset              truncate audit_logs and tool_permissions (default allow-all
                     policy); delete every non-admin user (their API keys
                      cascade); optionally --with-demo-users
--verify             force a health probe, assert the 3 seeded upstreams are Connected
                     and tools/list returns 11 tools (woo 6 / time 2 / notes 3)

Contract with scripts/demo-reset.sh
----------------------------------
  stdout   human-readable sections with PASS/FAIL lines
  last line SUMMARY_JSON {...}   machine-readable counts, no secrets
  exit     0 = ok, 5 = verification failed, 6 = gateway env/DB problem

Secrets (GATEWAY_ADMIN_PASSWORD, NOTES_API_TOKEN, FERNET_KEY, DATABASE_URL) are read
from the pod environment and never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets as pysecrets
from urllib.parse import urlsplit

import httpx
from auth.keys import create_api_key, hash_key, revoke_api_key
from auth.rbac import hash_password
from config import get_settings
from db.models import AdminEvent, ApiKey, AuditLog, Server, ToolPermission, User
from db.session import get_session_factory
from gw_mcp.health import probe_once
from registry.crud import INTERNAL_DEFAULTS
from sqlalchemy import func, select, text

SUMMARY_PREFIX = "SUMMARY_JSON "
BASE = "http://127.0.0.1:8000"
SEED_SLUGS = [d["slug"] for d in INTERNAL_DEFAULTS]
# INTERNAL_DEFAULTS stores the full mount URL (http://urumi-demo-notes:8000/mcp);
# split it so httpx gets base_url + path instead of a doubled /mcp/mcp.
_notes_url = urlsplit(next(d["url"] for d in INTERNAL_DEFAULTS if d["slug"] == "notes"))
NOTES_BASE = f"{_notes_url.scheme}://{_notes_url.netloc}"
NOTES_PATH = _notes_url.path or "/mcp"
# The demo contract verified live: 6 woo-mcp tools + 2 time tools + 3 notes tools
# (src/woo-mcp/tools.py, src/demo-mcp-time/tools.py, src/demo-mcp-notes/tools.py).
EXPECTED_TOOLS = {"total": 11, "woo": 6, "time": 2, "notes": 3}
DEMO_USERS = (("demo-a@urumi.local", "admin"), ("demo-b@urumi.local", "member"))
MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-03-26",
}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Gateway demo-data reset (in-pod worker)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--reset", action="store_true")
    mode.add_argument("--verify", action="store_true")
    ap.add_argument("--with-demo-users", action="store_true", help="only with --reset")
    return ap.parse_args()


def emit(summary: dict) -> None:
    print(SUMMARY_PREFIX + json.dumps(summary, separators=(",", ":")))


# ---------------------------------------------------------------- read-only state
async def gateway_state() -> dict:
    """Counts and rows the reset decision is based on (never mutates)."""
    factory = get_session_factory()
    async with factory() as db:
        audit_rows = (await db.execute(select(func.count()).select_from(AuditLog))).scalar() or 0
        admin_events = (await db.execute(select(func.count()).select_from(AdminEvent))).scalar() or 0
        perm_rules = (await db.execute(select(func.count()).select_from(ToolPermission))).scalar() or 0
        users = list((await db.execute(select(User).order_by(User.created_at))).scalars().all())
        keys = list((await db.execute(select(ApiKey))).scalars().all())
        servers = list((await db.execute(select(Server).order_by(Server.slug))).scalars().all())

    admins = [u for u in users if u.role == "admin"]
    members = [u for u in users if u.role != "admin"]
    member_ids = {u.id for u in members}
    admin_ids = {u.id for u in admins}
    keys_by_owner: dict = {}
    for k in keys:
        keys_by_owner[k.user_id] = keys_by_owner.get(k.user_id, 0) + 1
    return {
        "audit_rows": audit_rows,
        "admin_events": admin_events,
        "perm_rules": perm_rules,
        "admins": admins,
        "members": members,
        "keys_by_owner": keys_by_owner,
        "member_key_count": sum(keys_by_owner.get(u.id, 0) for u in members),
        "admin_key_count": sum(keys_by_owner.get(u.id, 0) for u in admins),
        "orphan_key_count": sum(1 for k in keys if k.user_id not in member_ids | admin_ids),
        "revoked_key_count": sum(1 for k in keys if k.revoked_at is not None),
        "servers": servers,
        "seeded_servers": [s for s in servers if s.slug in SEED_SLUGS],
        "extra_servers": [s for s in servers if s.slug not in SEED_SLUGS],
    }


async def count_notes() -> tuple[int | None, str]:
    """Count notes through the notes upstream itself (in-memory store, source of truth).

    The bearer token comes from the gateway pod env and is only ever placed in an
    Authorization header - never printed, never logged.
    """
    token = os.environ.get("NOTES_API_TOKEN", "")
    if not token:
        return None, "NOTES_API_TOKEN is not set in the gateway pod env"
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(base_url=NOTES_BASE, timeout=httpx.Timeout(20.0)) as client:
            await client.post(
                NOTES_PATH,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "demo-reset", "version": "1"},
                    },
                },
                headers=headers,
            )
            await client.post(
                NOTES_PATH,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=headers,
            )
            resp = await client.post(
                NOTES_PATH,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "list_notes", "arguments": {}},
                },
                headers=headers,
            )
        payload = json.loads(resp.json()["result"]["content"][0]["text"])
        return int(payload.get("count", 0)), ""
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        return None, f"notes upstream unreachable ({exc.__class__.__name__})"


# ---------------------------------------------------------------------- dry run
async def dry_run() -> int:
    state = await gateway_state()
    notes_count, notes_err = await count_notes()

    print("== Gateway (audit_logs / admin_events / tool_permissions / users / api_keys / servers) ==")
    print(
        f"audit_logs: {state['audit_rows']} rows -> would be TRUNCATEd (ids restart at 1)"
    )
    print(f"admin_events: {state['admin_events']} rows -> would be TRUNCATEd (admin action trail, ADR-034)")
    print(f"tool_permissions: {state['perm_rules']} deny rule(s) -> would be TRUNCATEd (default allow-all)")
    print(
        f"users: {len(state['admins']) + len(state['members'])} total | "
        f"KEEP {len(state['admins'])} admin | DELETE {len(state['members'])} non-admin"
    )
    for u in state["admins"]:
        print(f"  KEEP    user {u.email} (role=admin)")
    for u in state["members"]:
        print(
            f"  DELETE  user {u.email} (role={u.role}, "
            f"{state['keys_by_owner'].get(u.id, 0)} api keys cascade)"
        )
    print(
        f"api_keys: {state['member_key_count'] + state['admin_key_count'] + state['orphan_key_count']} total | "
        f"DELETE {state['member_key_count']} (owned by non-admins) | "
        f"KEEP {state['admin_key_count']} (owned by admins, "
        f"{state['revoked_key_count']} of them already revoked)"
    )
    print("servers: never deleted or modified")
    for s in state["servers"]:
        tag = "KEEP (seeded)" if s.slug in SEED_SLUGS else "KEEP (added during testing)"
        print(
            f"  {tag} server {s.slug} status={s.status} enabled={s.enabled} "
            f"credential={'encrypted' if s.credential_encrypted else 'none'}"
        )
    if state["extra_servers"]:
        print(f"  note: {len(state['extra_servers'])} non-seeded server(s) kept and listed above")
    if notes_count is None:
        print(f"notes upstream: {notes_err} (all notes would still be cleared by the restart)")
    else:
        print(f"notes upstream: {notes_count} note(s) -> cleared by restarting deployment urumi-demo-notes")

    print("DRY RUN: nothing was changed.")
    emit(
        {
            "mode": "dry-run",
            "audit_rows_planned": state["audit_rows"],
            "admin_events_planned": state["admin_events"],
            "users_planned": [u.email for u in state["members"]],
            "member_keys_planned": state["member_key_count"],
            "admin_keys_kept": state["admin_key_count"],
            "revoked_keys_kept": state["revoked_key_count"],
            "admins_kept": [u.email for u in state["admins"]],
            "servers": [
                {"slug": s.slug, "status": s.status, "enabled": s.enabled} for s in state["servers"]
            ],
            "extra_servers": [s.slug for s in state["extra_servers"]],
            "notes_count": notes_count,
        }
    )
    return 0


# ----------------------------------------------------------------------- reset
async def create_demo_user(db, email: str, role: str) -> dict:
    """Create one demo user with a fresh password + API key.

    Both values are printed ONCE, here, and nowhere else: not written to a file, not
    logged, not part of any SUMMARY_JSON. Re-running is idempotent because the caller
    deletes a previous demo user with the same address first.
    """
    password = pysecrets.token_urlsafe(12)
    user = User(email=email, password_hash=await hash_password(password), role=role)
    db.add(user)
    await db.flush()
    _row, raw_key = await create_api_key(db, user.id)
    await db.commit()
    print(f"  created {email} role={role}")
    print(f"    password (shown once, never stored): {password}")
    print(f"    api key  (shown once, never stored): {raw_key}")
    return {"email": email, "role": role}


async def reset(with_demo_users: bool) -> int:
    print("== Gateway reset ==")
    factory = get_session_factory()
    demo_created: list[dict] = []
    async with factory() as db:
        audit_rows = (await db.execute(select(func.count()).select_from(AuditLog))).scalar() or 0
        admin_events_rows = (await db.execute(select(func.count()).select_from(AdminEvent))).scalar() or 0
        member_rows = (
            await db.execute(
                select(User, func.count(ApiKey.id))
                .outerjoin(ApiKey, ApiKey.user_id == User.id)
                .where(User.role != "admin")
                .group_by(User.id)
                .order_by(User.created_at)
            )
        ).all()
        admin_emails = [
            email
            for (email,) in (await db.execute(select(User.email).where(User.role == "admin"))).all()
        ]
        member_key_count = sum(count for _user, count in member_rows)

        # 1. audit_logs: TRUNCATE (transactional in Postgres) so ids restart at 1.
        print(f"audit_logs: truncating {audit_rows} rows")
        await db.execute(text("TRUNCATE TABLE audit_logs RESTART IDENTITY"))
        remaining = (await db.execute(select(func.count()).select_from(AuditLog))).scalar() or 0
        print(f"audit_logs: {remaining} rows remain")

        # 1a. admin_events (ADR-034): same sanctioned wipe as audit_logs - the
        # demo starts with an empty admin action trail.
        print(f"admin_events: truncating {admin_events_rows} rows")
        await db.execute(text("TRUNCATE TABLE admin_events RESTART IDENTITY"))
        remaining_events = (await db.execute(select(func.count()).select_from(AdminEvent))).scalar() or 0
        print(f"admin_events: {remaining_events} rows remain")

        # 1b. tool_permissions: back to the default allow-all policy (ADR-033). The
        # demo applies the example member deny policy live; the reset clears it.
        perm_rows = (await db.execute(select(func.count()).select_from(ToolPermission))).scalar() or 0
        print(f"tool_permissions: deleting {perm_rows} deny rule(s) (default allow-all)")
        await db.execute(text("TRUNCATE TABLE tool_permissions"))
        remaining_perm = (await db.execute(select(func.count()).select_from(ToolPermission))).scalar() or 0
        print(f"tool_permissions: {remaining_perm} rules remain")

        # 2. non-admin users; api_keys cascade, exactly like DELETE /api/users/{id}
        print(f"users: deleting {len(member_rows)} non-admin user(s) (+ {member_key_count} api keys)")
        for user, key_count in member_rows:
            print(f"  deleted user {user.email} (role={user.role}, {key_count} api keys)")
            await db.delete(user)
        await db.commit()

        if with_demo_users:
            print("--with-demo-users: creating demo A (admin) + B (member)")
            for email, role in DEMO_USERS:
                stale = (
                    await db.execute(select(User).where(User.email == email))
                ).scalars().first()
                if stale is not None:
                    print(f"  removed previous {email} (idempotent re-run)")
                    await db.delete(stale)
                    await db.commit()
                demo_created.append(await create_demo_user(db, email, role))

    after = await gateway_state()
    print(
        f"gateway now: {len(after['admins'])} admin user(s), "
        f"{len(after['members'])} non-admin user(s), "
        f"{after['member_key_count'] + after['admin_key_count']} api keys, 0 audit rows"
    )
    emit(
        {
            "mode": "reset",
            "audit_rows_deleted": audit_rows,
            "admin_events_deleted": admin_events_rows,
            "perm_rules_deleted": perm_rows,
            "users_deleted": [user.email for user, _count in member_rows],
            "keys_deleted": member_key_count,
            "admins_kept": admin_emails,
            "admin_keys_kept": after["admin_key_count"],
            "servers_kept": [s.slug for s in after["servers"]],
            "demo_users_created": [d["email"] for d in demo_created],
        }
    )
    return 0


# ---------------------------------------------------------------------- verify
async def list_tools_via_gateway() -> tuple[list[str], str, bool]:
    """Mint a temporary admin key, tools/list through /mcp, revoke the key again.

    Returns (tool names, error, key_was_revoked). The raw key never leaves this
    function and is never printed.
    """
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as db:
        admin = (
            await db.execute(select(User).where(User.email == settings.admin_email))
        ).scalars().first()
        if admin is None:
            return [], f"admin user {settings.admin_email} not found", False
        _row, raw_key = await create_api_key(db, admin.id)
        await db.commit()

    names: list[str] = []
    err = ""
    try:
        headers = {**MCP_HEADERS, "Authorization": f"Bearer {raw_key}"}
        async with httpx.AsyncClient(base_url=BASE, timeout=httpx.Timeout(30.0)) as client:
            resp = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                headers=headers,
            )
        body = resp.json()
        names = [str(t.get("name")) for t in body.get("result", {}).get("tools", [])]
    except (httpx.HTTPError, ValueError) as exc:
        err = f"tools/list failed ({exc.__class__.__name__})"

    revoked = False
    async with factory() as db:
        row = (
            await db.execute(select(ApiKey).where(ApiKey.sha256 == hash_key(raw_key)))
        ).scalars().first()
        if row is not None:
            revoked = await revoke_api_key(db, row.id)
            await db.commit()
    return names, err, revoked


async def verify() -> int:
    print("== post-reset verification ==")
    failures: list[str] = []

    # Force an immediate health probe so the just-restarted notes upstream is re-checked
    # now, instead of waiting for the background loop's interval.
    # Blind except on purpose: report, then let the per-server checks speak.
    try:
        await probe_once()
        print("health probe: forced run done")
    except Exception as exc:
        print(f"health probe: forced run failed ({exc.__class__.__name__}: {exc})")

    state = await gateway_state()
    by_slug = {s.slug: s for s in state["servers"]}
    for slug in SEED_SLUGS:
        srv = by_slug.get(slug)
        if srv is None:
            failures.append(f"seeded server {slug} missing")
            print(f"FAIL  server {slug} missing")
            continue
        ok = srv.status == "Connected" and srv.enabled
        print(f"{'PASS' if ok else 'FAIL'}  server {slug} status={srv.status} enabled={srv.enabled}")
        if not ok:
            failures.append(f"server {slug} status={srv.status}")
    for srv in state["extra_servers"]:
        print(f"INFO  non-seeded server {srv.slug} kept (status={srv.status})")

    names, err, temp_key_revoked = await list_tools_via_gateway()
    if err:
        failures.append(err)
        print(f"FAIL  tools/list via gateway: {err}")
        tools_by_prefix: dict[str, int] = {}
    else:
        tools_by_prefix = {
            p: sum(1 for n in names if n.startswith(f"{p}__"))
            for p in EXPECTED_TOOLS
            if p != "total"
        }
        total_ok = len(names) == EXPECTED_TOOLS["total"]
        prefix_ok = all(
            tools_by_prefix.get(p) == c for p, c in EXPECTED_TOOLS.items() if p != "total"
        )
        print(
            f"{'PASS' if total_ok else 'FAIL'}  tools/list returned {len(names)} tools "
            f"(expected {EXPECTED_TOOLS['total']}) by prefix={tools_by_prefix}"
        )
        if not total_ok:
            failures.append(f"tools/list total {len(names)}")
        if not prefix_ok:
            failures.append(f"tools/list per-prefix {tools_by_prefix}")
        print(f"{'PASS' if temp_key_revoked else 'FAIL'}  temporary verification key revoked")
        if not temp_key_revoked:
            failures.append("temporary verification key not revoked")

    ok = not failures
    print(f"== verification {'PASS' if ok else 'FAIL'} ==")
    connected = sum(
        1 for slug in SEED_SLUGS if by_slug.get(slug) is not None and by_slug[slug].status == "Connected"
    )
    emit(
        {
            "mode": "verify",
            "ok": ok,
            "servers_connected": connected,
            "servers_expected": len(SEED_SLUGS),
            "tools_listed": len(names),
            "tools_expected": EXPECTED_TOOLS["total"],
            "tools_by_prefix": tools_by_prefix,
            "failures": failures,
        }
    )
    return 0 if ok else 5


async def main() -> int:
    args = parse_args()
    if args.with_demo_users and not args.reset:
        print("ERROR: --with-demo-users only applies to --reset")
        return 6
    if args.dry_run:
        return await dry_run()
    if args.reset:
        return await reset(args.with_demo_users)
    return await verify()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
