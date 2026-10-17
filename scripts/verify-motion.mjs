#!/usr/bin/env node
// Motion proof (dark mode + motion pass, requirement 9):
//   - a stat number sampled at ~100ms and again at 1s ends on the API value
//     (700ms count-up, exact real value at the end);
//   - with prefers-reduced-motion it shows the final value at 0ms;
//   - no console errors on the overview page.
// Run: node scripts/verify-motion.mjs (needs the live dashboard at
// DASHBOARD_URL, default http://dashboard.127.0.0.1.nip.io).
import { createRequire } from "node:module";
import * as browserAuth from "./lib/browser-auth.mjs";

const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");

const DASHBOARD_URL = process.env.DASHBOARD_URL || "http://dashboard.127.0.0.1.nip.io";

async function statProbe({ reducedMotion }) {
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  try {
    const admin = await browserAuth.adminLogin(DASHBOARD_URL);
    const ctx = await browser.newContext({ reducedMotion: reducedMotion ? "reduce" : "no-preference" });
    await ctx.addCookies(browserAuth.cookiePair(admin.cookie, DASHBOARD_URL));
    const page = await ctx.newPage();
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(`${DASHBOARD_URL}/overview?expanded=1`, { waitUntil: "networkidle" });
    // API truth for the first stat tile (total calls in range).
    const apiCalls = await page.evaluate(async () => {
      const r = await fetch("/api/stats?range=week", { credentials: "include" });
      const j = await r.json();
      return j?.audit?.calls ?? null;
    });
    // Sample the rendered stat number early (~100ms) and late (1s).
    await page.waitForTimeout(100);
    const early = await page.evaluate(() => {
      const el = document.querySelector('[aria-label="Total tool calls"] .stat-num');
      return el ? el.textContent.trim() : null;
    });
    await page.waitForTimeout(900);
    const late = await page.evaluate(() => {
      const el = document.querySelector('[aria-label="Total tool calls"] .stat-num');
      return el ? el.textContent.trim() : null;
    });
    await ctx.close();
    return { apiCalls, early, late, errors };
  } finally {
    await browser.close();
  }
}

function num(s) {
  if (s == null) return null;
  const m = String(s).replace(/,/g, "").match(/-?[\d.]+/);
  return m ? parseFloat(m[0]) : null;
}

async function run() {
  const failures = [];
  const full = await statProbe({ reducedMotion: false });
  console.log(`motion full: api=${full.apiCalls} early=${JSON.stringify(full.early)} late=${JSON.stringify(full.late)}`);
  if (full.apiCalls == null) failures.push("could not read /api/stats audit.calls");
  else if (num(full.late) !== full.apiCalls) failures.push(`count-up did not end on API value: late=${full.late} api=${full.apiCalls}`);
  else console.log("PASS count-up ends on the API value at 1s");
  if (full.errors.length) failures.push(`console errors (full motion): ${full.errors.join("; ")}`);
  else console.log("PASS no console errors (full motion)");

  const rm = await statProbe({ reducedMotion: true });
  console.log(`motion reduced: api=${rm.apiCalls} early=${JSON.stringify(rm.early)} late=${JSON.stringify(rm.late)}`);
  // With reduced motion the tile must show the final value immediately.
  const earlyProbe = await (async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const admin = await browserAuth.adminLogin(DASHBOARD_URL);
      const ctx = await browser.newContext({ reducedMotion: "reduce" });
      await ctx.addCookies(browserAuth.cookiePair(admin.cookie, DASHBOARD_URL));
      const page = await ctx.newPage();
      await page.goto(`${DASHBOARD_URL}/overview?expanded=1`, { waitUntil: "domcontentloaded" });
      // 0ms: read as soon as the stat tile exists.
      await page.waitForSelector('[aria-label="Total tool calls"] .stat-num');
      const v = await page.evaluate(() => document.querySelector('[aria-label="Total tool calls"] .stat-num').textContent.trim());
      await ctx.close();
      return v;
    } finally { await browser.close(); }
  })();
  console.log(`motion reduced @0ms: ${JSON.stringify(earlyProbe)}`);
  if (rm.apiCalls != null && num(earlyProbe) !== rm.apiCalls) failures.push(`reduced motion did not show final at 0ms: got=${earlyProbe} api=${rm.apiCalls}`);
  else console.log("PASS reduced motion shows the final value at 0ms");
  if (rm.errors.length) failures.push(`console errors (reduced motion): ${rm.errors.join("; ")}`);
  else console.log("PASS no console errors (reduced motion)");

  if (failures.length) {
    console.error(`\n${failures.length} FAILING check(s):`);
    for (const f of failures) console.error(` - ${f}`);
    process.exit(1);
  }
  console.log("\nALL MOTION CHECKS PASSED");
}

run().catch((e) => { console.error(e); process.exit(1); });
