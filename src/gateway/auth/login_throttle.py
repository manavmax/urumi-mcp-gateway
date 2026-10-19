"""Login lockout (hardening, ADR-044).

Per-username AND per-client-IP failure counting for the dashboard login. After
`login_lockout_attempts` failed attempts inside `login_lockout_window_seconds`
the key is locked: further attempts get 429 until the window drains (a sliding
window - each failure ages out independently).

The counter is IN-MEMORY, so it is PER REPLICA: with >1 gateway replicas an
attacker gets `attempts x replicas` tries. That is an accepted residual for this
single-replica demo (THREAT_MODEL.md); a shared store (Redis/PG) is the scaling
path and is deliberately NOT half-implemented here.

Nothing here touches the audit trail: routes/users.py records lockouts via
record_admin_event so the trail keeps its transaction semantics.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from config import get_settings

# (kind, key) -> deque of failure timestamps. kinds: "user", "ip".
_failures: dict[tuple[str, str], deque[float]] = defaultdict(deque)
# (kind, key) -> window start of the CURRENT lockout; used to audit-log a lockout
# exactly once per window instead of on every blocked attempt.
_lockouts: dict[tuple[str, str], float] = {}


def _window_seconds() -> int:
    try:
        value = int(get_settings().login_lockout_window_seconds)
    except (TypeError, ValueError):
        return 300
    return value if value > 0 else 300


def _attempts_allowed() -> int:
    try:
        value = int(get_settings().login_lockout_attempts)
    except (TypeError, ValueError):
        return 5
    return value if value > 0 else 5


def _prune(q: deque[float], now: float) -> None:
    window = _window_seconds()
    while q and q[0] <= now - window:
        q.popleft()


def is_locked(kind: str, key: str) -> bool:
    """True when this key has reached the failure cap inside the window."""
    now = time.monotonic()
    q = _failures[(kind, key)]
    _prune(q, now)
    return len(q) >= _attempts_allowed()


def record_failure(kind: str, key: str) -> bool:
    """Record one failure. Returns True when this failure JUST locked the key
    (i.e. the cap was crossed now) - the caller audits that transition once."""
    now = time.monotonic()
    q = _failures[(kind, key)]
    _prune(q, now)
    q.append(now)
    locked = len(q) >= _attempts_allowed()
    if locked:
        _lockouts.setdefault((kind, key), now)
    return locked and _lockouts[(kind, key)] == now


def record_success(kind: str, key: str) -> None:
    """A successful login clears that key's failures (both kinds for a user)."""
    _failures.pop((kind, key), None)
    _lockouts.pop((kind, key), None)


def reset_all() -> None:
    """Test hook: clear every counter."""
    _failures.clear()
    _lockouts.clear()
