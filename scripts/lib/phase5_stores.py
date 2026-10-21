"""Phase 5 store lifecycle helper: create stores, poll to Ready. Runs INSIDE
the gateway pod (env: GATEWAY_ADMIN_PASSWORD).

  create <display-name>     create a store; prints STATUS=<code> + body
  wait <slug> <seconds>     poll GET /api/stores until the store leaves
                            Provisioning; prints its status
  state                     one line per store
  id <slug>                 prints the stored store id (from create)
"""

from __future__ import annotations

import json
import os
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"
STATE_PATH = "/tmp/urumi-phase5-stores.json"


def _state() -> dict:
    try:
        with open(STATE_PATH) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as fh:
        json.dump(state, fh)
    os.chmod(STATE_PATH, 0o600)


class Gateway:
    def __init__(self) -> None:
        self.client = httpx.Client(base_url=BASE, timeout=60)
        r = self.client.post(
            "/api/auth/login",
            json={"email": "admin@urumi.local", "password": os.environ.get("GATEWAY_ADMIN_PASSWORD", "")},
        )
        if r.status_code != 200:
            raise SystemExit(f"login failed: {r.status_code}")
        from config import get_settings

        cname = get_settings().session_cookie_name
        value = ""
        for part in r.headers.get("set-cookie", "").split(";"):
            if "=" in part and part.strip().startswith(cname + "="):
                value = part.strip().split("=", 1)[1]
        self.headers = {
            "Cookie": f"{cname}={value}",
            "X-CSRF-Token": r.json()["csrf_token"],
            "Content-Type": "application/json",
        }

    def req(self, method: str, path: str, body: dict | None = None):
        return self.client.request(method, path, json=body, headers=self.headers)

    def row(self, slug: str) -> dict | None:
        r = self.req("GET", "/api/stores")
        return next((s for s in r.json().get("stores", []) if s["slug"] == slug), None)


def main(argv: list[str]) -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "create":
        gw = Gateway()
        r = gw.req("POST", "/api/stores", {"display_name": sys.argv[2]})
        print(f"STATUS={r.status_code}")
        print(r.text[:400])
        if r.status_code == 201:
            body = r.json()
            st = _state()
            st[body["slug"]] = {"id": body["id"], "slug": body["slug"]}
            _save_state(st)
        return 0 if r.status_code == 201 else 1
    if cmd in ("wait", "wait-ready"):
        slug, budget = sys.argv[2], int(sys.argv[3])
        gw = Gateway()
        deadline = time.monotonic() + budget
        while time.time() < deadline:
            r = gw.req("GET", "/api/stores")
            row = next((s for s in r.json().get("stores", []) if s["slug"] == slug), None)
            if row and row["status"] != "Provisioning":
                print(f"STATUS={row['status']}")
                print(f"REASON={row.get('failure_reason') or ''}")
                print(f"URL={row.get('url') or ''}")
                return 0 if row["status"] == "Ready" else 1
            time.sleep(10)
        print("STATUS=TIMEOUT")
        return 1
    if cmd == "state":
        gw = Gateway()
        r = gw.req("GET", "/api/stores")
        for s in r.json().get("stores", []):
            print(f"STORE {s['slug']} status={s['status']} ns={s['namespace']} reason={s.get('failure_reason') or ''}")
        return 0
    if cmd == "id":
        st = _state()
        print(st.get(sys.argv[2], {}).get("id", ""))
        return 0
    print("unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
