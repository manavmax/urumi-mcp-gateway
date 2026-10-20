# EXPLAINER (3-5 lines per component)

One short section per new component: what it does, why this approach, main failure mode, how a request flows.


## scripts/regress-core.sh (Phase 0)
What: automates the core Definition of Done on the local kind cluster with two users: a real storefront COD order via the WooCommerce Store API, tools/list counts for admin and member, the orders question via MCP, revoked-key rejection, disabled-upstream hiding (MCP + chat tool load), kill-an-upstream-pod resilience, audit attribution.
Why: the brief's regression gate after every phase; a phase is not done until this passes.
Main failure mode: a stale image in the kind node (pods keep the old image until restarted) - always `make deploy` (or the image targets + rollout restart) before the gate.
Request flow: bash orchestrator -> in-pod python (scripts/lib/regress_store_order.py in woo-mcp pod, scripts/lib/regress_gw.py in gateway pod, state in /tmp inside the pod, deleted at cleanup). Refuses any kubectl context that does not start with kind-.

## Timezone fallback (gateway + demo-time, ADR-054)
What: the chat system prompt always stamps a concrete local date/time; missing/invalid client tz falls back to gateway.defaultTimezone (values-local: Asia/Kolkata). demo-mcp-time answers get_current_time in demoTime.defaultTimezone when the caller omits one.
Why: "today" in order questions must resolve somewhere concrete; a missing browser tz must not leave the prompt dateless.
Main failure mode: an invalid configured zone surfaces the time tool's normal Unknown-timezone error; the prompt falls back to no stamp only if BOTH client and configured zones are invalid.
Request flow: browser sends tz with the chat body -> route validates with zoneinfo -> build_system_prompt stamps local time (client tz, else configured default) -> model resolves "today" against that stamp.
