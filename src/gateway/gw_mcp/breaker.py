"""Circuit breaker per upstream server (docs/04 §6.2 / docs/02 §3.3)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class CircuitState:
    failures: int = 0
    opened_at: float | None = None
    last_failure: float | None = None


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, reset_seconds: int = 60):
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._states: dict[uuid.UUID, CircuitState] = {}

    def _get(self, server_id: uuid.UUID) -> CircuitState:
        if server_id not in self._states:
            self._states[server_id] = CircuitState()
        return self._states[server_id]

    def is_open(self, server_id: uuid.UUID) -> bool:
        st = self._get(server_id)
        if st.opened_at is None:
            return False
        if time.monotonic() - st.opened_at >= self.reset_seconds:
            # half-open: allow one probe
            st.opened_at = None
            st.failures = 0
            return False
        return True

    def record_success(self, server_id: uuid.UUID):
        st = self._get(server_id)
        st.failures = 0
        st.opened_at = None
        st.last_failure = None

    def record_failure(self, server_id: uuid.UUID):
        st = self._get(server_id)
        st.failures += 1
        st.last_failure = time.monotonic()
        if st.failures >= self.failure_threshold:
            st.opened_at = time.monotonic()

    def state_for(self, server_id: uuid.UUID) -> str:
        if self.is_open(server_id):
            return "open"
        st = self._get(server_id)
        if st.failures > 0:
            return "half_open" if st.opened_at is None else "open"
        return "closed"


# global singleton (lifespan can replace)
breaker = CircuitBreaker()
