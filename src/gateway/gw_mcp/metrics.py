"""Prometheus metrics for the gateway (Phase 1 observability, ADR-056).

Endpoint: GET /metrics (routes/metrics.py) - NOT routed through the Ingress
(the dashboard host has no /metrics path to the gateway) and, at the pod level,
reachable only in-cluster behind the default-deny NetworkPolicy (only the
ingress-nginx namespace may enter the gateway's public port, and the Ingress
never routes /metrics). An optional bearer token (env METRICS_BEARER) adds an
application-level guard for in-cluster scrapers.

Counters/gauges:
  tool_calls_total{server,tool,outcome}        every routed tool call (/mcp + chat)
  tool_call_duration_seconds{server}           per-server call duration histogram
  upstream_up{server}                          1 = Connected, 0 = not (health loop)
  rate_limited_total{scope}                    rate-limit rejections (scope: key|user)

prometheus_client is the ONE new runtime dependency the brief allows. Every
helper fails safe: a metrics problem must never break a tool call or the audit
row, so all writes are wrapped and swallowed with a warning.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("gateway.metrics")

try:
    from prometheus_client import Counter, Gauge, Histogram

    TOOL_CALLS = Counter(
        "tool_calls_total",
        "Routed tool calls by server, tool and outcome",
        ["server", "tool", "outcome"],
    )
    DURATION = Histogram(
        "tool_call_duration_seconds",
        "Upstream tool call duration in seconds",
        ["server"],
    )
    UPSTREAM_UP = Gauge(
        "upstream_up",
        "1 when the gateway last saw the upstream as Connected, else 0",
        ["server"],
    )
    RATE_LIMITED = Counter(
        "rate_limited_total",
        "Calls rejected by a rate limit",
        ["scope"],
    )
    _AVAILABLE = True
except ImportError:  # pragma: no cover - package always installed via requirements
    TOOL_CALLS = DURATION = UPSTREAM_UP = RATE_LIMITED = None
    _AVAILABLE = False


def observe_tool_call(server: str, tool: str, outcome: str, duration_ms: int) -> None:
    """Record one routed tool call (both /mcp and the chat agent go through the
    same audit semantics, so both call this). Never raises."""
    try:
        TOOL_CALLS.labels(server=server, tool=tool, outcome=outcome).inc()
        if outcome not in ("permission_denied", "validation_error", "rate_limited"):
            # caller mistakes carry no upstream duration signal; everything else
            # is a real upstream round-trip worth the histogram
            DURATION.labels(server=server).observe(max(0, duration_ms) / 1000.0)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("metrics observe failed: %s", exc)


def set_upstream_up(server: str, up: bool) -> None:
    try:
        UPSTREAM_UP.labels(server=server).set(1 if up else 0)
    except Exception as exc:  # pragma: no cover
        logger.warning("metrics gauge failed: %s", exc)


def inc_rate_limited(scope: str = "key") -> None:
    try:
        RATE_LIMITED.labels(scope=scope).inc()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("metrics counter failed: %s", exc)


def render() -> tuple[bytes, str]:
    """The Prometheus exposition payload + content type. Never raises on metric
    collection; import problems surface at startup, not here."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return generate_latest(), CONTENT_TYPE_LATEST
