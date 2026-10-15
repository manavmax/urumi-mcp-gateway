#!/usr/bin/env node
// Fix 3 verification (Audit filters): typing in a filter field must NOT refetch
// the audit page (one request per keystroke was the bug), Apply must send
// exactly one request carrying the typed filters, and Apply while paged deep
// into a filtered result set must reset offset to 0 (a stale offset produced
// empty pages).
//
//   node scripts/verify-audit-filters.mjs
//
// The pagination half needs >100 audit rows; seed them first with:
//   kubectl exec -n urumi urumi-postgres-0 -- psql -U urumi -d urumi -c \
//     "insert into audit_logs (ts, server_slug, tool_exposed_name, tool_upstream_name, request_id, duration_ms, outcome)
//      select now(), 'seedtest', 'seed_tool', 'seed_tool', gen_random_uuid(), 10, 'success' from generate_series(1,120);"
// and clean up afterwards with:
//   kubectl exec -n urumi urumi-postgres-0 -- psql -U urumi -d urumi -c \
//     "delete from audit_logs where server_slug = 'seedtest';"
//
// Uses the shared login helpers in scripts/lib/browser-auth.mjs. Never reads .env.

import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
import { adminLogin, cookiePair } from "./lib/browser-auth.mjs";

const DASHBOARD_URL = process.env.DASHBOARD_URL || "http://dashboard.127.0.0.1.nip.io";
const AUDIT_URL = `${DASHBOARD_URL}/audit`;

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok, detail });
  console.log(`   ${ok ? "PASS" : "FAIL"} ${name}${detail ? `: ${detail}` : ""}`);
}

async function waitForAuditRequest(getCount, timeout = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const c = getCount();
    if (c > 0) return c;
    await new Promise((r) => setTimeout(r, 100));
  }
  return getCount();
}

async function run() {
  const browser = await chromium.launch({ headless: true });
  try {
    const admin = await adminLogin(DASHBOARD_URL);
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await ctx.addCookies(cookiePair(admin.cookie, DASHBOARD_URL));
    const page = await ctx.newPage();

    let requests = [];
    page.on("request", (r) => {
      if (r.url().includes("/api/audit")) requests.push(r.url());
    });

    await page.goto(AUDIT_URL, { waitUntil: "networkidle" });
    check("initial page load fetches the audit table", await waitForAuditRequest(() => requests.length) > 0, `${requests.length} request(s)`);
    requests = [];
    await page.waitForSelector("#f-tool");

    /* 1. typing must not refetch */
    await page.fill("#f-tool", "seed_to");
    await page.waitForTimeout(250);
    await page.fill("#f-tool", "seed_tool");
    await page.waitForTimeout(700);
    check("typing in a filter field issues zero audit requests", requests.length === 0, `${requests.length} request(s)`);

    /* 2. Apply sends exactly one request with the typed filters, offset reset */
    await page.click("form.filters button[type=submit]");
    const applied = await waitForAuditRequest(() => requests.length);
    await page.waitForTimeout(300);
    check("Apply issues exactly one audit request", requests.length === 1, `${requests.length} request(s)`);
    check("Apply sends the typed filter and offset=0", applied === 1 && requests[0].includes("tool=seed_tool") && /[?&]offset=0/.test(requests[0]), requests[0]);

    /* 3. pagination still pages */
    const next = page.locator(".pager .row .btn-secondary").nth(1);
    if (await next.isEnabled()) {
      requests = [];
      await next.click();
      await waitForAuditRequest(() => requests.length);
      await page.waitForTimeout(300);
      check("Next pages to offset=100", requests.length === 1 && /[?&]offset=100/.test(requests[0]), requests[0]);

      /* 4. changing a filter while paged must reset the offset */
      requests = [];
      await page.fill("#f-server", "seedtest");
      await page.click("form.filters button[type=submit]");
      const after = await waitForAuditRequest(() => requests.length);
      await page.waitForTimeout(300);
      check(
        "Apply after paging resets offset to 0 and keeps the other filters",
        after === 1 && /[?&]offset=0/.test(requests[0]) && requests[0].includes("tool=seed_tool") && requests[0].includes("server=seedtest"),
        requests[0],
      );
      const rowsNow = await page.locator("table tbody tr").count();
      check("filtered page still renders rows (not an empty offset)", rowsNow > 0, `${rowsNow} row(s)`);

      /* 5. CSV export mirrors the table's committed params (Fix 6): same filters
            and range window, no page limit/offset */
      requests = [];
      await page.click(".seg button:has-text('Week')");
      await waitForAuditRequest(() => requests.length);
      await page.waitForTimeout(300);
      requests = [];
      await page.click("button.btn-secondary:has-text('CSV export')");
      const exported = await waitForAuditRequest(() => requests.length);
      await page.waitForTimeout(300);
      const first = requests[0] || "(no request)";
      check("CSV export sends exactly one request", exported === 1 && requests.length === 1, first);
      check(
        "CSV export carries the table's filters and range window, not a fresh re-derivation",
        first.includes("/api/audit/export") && /[?&]tool=seed_tool/.test(first) && /[?&]server=seedtest/.test(first) && /[?&]from=/.test(first) && /[?&]to=/.test(first),
        first,
      );
      check("CSV export omits the table page limit/offset", !/[?&]limit=/.test(first) && !/[?&]offset=/.test(first), first);
    } else {
      check("pagination checks (needs >100 audit rows)", true, "SKIPPED: fewer than 100 audit rows (see header to seed)");
    }

    await ctx.close();
  } finally {
    await browser.close();
  }

  const failed = results.filter((r) => !r.ok);
  check("summary", failed.length === 0, failed.length ? `${failed.length} check(s) FAIL` : `${results.length}/${results.length} checks pass`);
  if (failed.length) process.exit(1);
  console.log("\nAUDIT FILTER CHECKS PASSED");
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
