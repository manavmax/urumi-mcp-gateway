# REVIEW NEEDED (Manav)

Anything security or architecture related to confirm. Newest last.

- 2026-10-21 (env quirk): the local kind node container runs under the **colima**
  docker context; the default docker context is `desktop-linux` (Docker Desktop)
  and shows no containers. All image build/import in this run used
  `docker --context colima`. Confirm which context should be the default, or
  whether the Makefile image targets should gain a DOCKER_CONTEXT variable.
- 2026-10-21 (ADR-054): chat "today" now resolves in `gateway.defaultTimezone`
  (Asia/Kolkata in values-local) when the browser sends no valid timezone. The
  stamp may therefore disagree with the real browser zone when the browser
  refuses to send one - confirm Asia/Kolkata is the wanted demo default and that
  values-prod should stay UTC (it is unset there today).
- 2026-10-21 (regress-core): the throwaway regress member/key material lives in
  /tmp/urumi-regress/state.json INSIDE the gateway pod for the duration of a
  regress run (deleted at cleanup, keys belong to a user the cleanup deletes).
  Acceptable ephemeral handling, but confirm you are happy with the pattern
  before it is reused by later phases.
- 2026-10-21 (ADR-056, /metrics protection): GET /metrics is in-cluster-only (default-deny NetworkPolicy + no Ingress route; proven live) and UNAUTHENTICATED by default; an optional METRICS_BEARER token can be put in the gateway-secrets Secret. Confirm whether you want a token set, and remember a future Prometheus scraper needs its own NetworkPolicy exception (none is rendered today because no Prometheus server is deployed).
- 2026-10-21 (ADR-056, audit classification): `protocol_error` was split out of `invalid_response` for unparseable upstream JSON-RPC responses, and CHAT tool-call failures (timeout/upstream) are now audited where they previously vanished. Confirm the audit semantics change is what you want shown in demos.
