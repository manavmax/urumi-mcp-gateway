#!/usr/bin/env node
// FIX PASS F1-7 proof: clicking "Show tools" on ONE server row shows ONLY that
// server's tools, and toggling one row never opens or closes another row.
// Root cause (fixed): toggleTools stored the whole grouped tool map, so every
// row with a key in the map rendered expanded.
// Run: node scripts/verify-server-tools.mjs (needs the live dashboard at
// DASHBOARD_URL, default http://dashboard.127.0.0.1.nip.io).
import { createRequire } from "node:module";
import * as browserAuth from "./lib/browser-auth.mjs";

const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");

const DASHBOARD_URL = process.env.DASHBOARD_URL || "http://dashboard.127.0.0.1.nip.io";
const failures = [];

const browser = await chromium.launch({ headless: true });
try {
  const admin = await browserAuth.adminLogin(DASHBOARD_URL);
  const ctx = await browser.newContext();
  await ctx.addCookies(browserAuth.cookiePair(admin.cookie, DASHBOARD_URL));
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));

  await page.goto(`${DASHBOARD_URL}/servers`, { waitUntil: "networkidle" });
  await page.waitForSelector("tbody tr .slug", { timeout: 15000 });

  const slugs = await page.$$eval("tbody tr .slug", (els) => els.map((e) => (e.textContent || "").trim()));
  if (slugs.length < 2) {
    console.error(`need at least 2 servers to prove isolation, found ${slugs.length}`);
    process.exit(1);
  }
  console.log(`servers on page: ${slugs.length} -> ${JSON.stringify(slugs.slice(0, 8))}`);

  // 1) open the FIRST row's tools. Note: the first row may legitimately have
  // zero tools (e.g. an unreachable live-proof server); the point is that ONLY
  // this row expands and every listed tool belongs to THIS server.
  const firstRow = page.locator("tbody tr").first();
  const firstSlug = ((await firstRow.locator(".slug").first().textContent()) || "").trim();
  await firstRow.locator("details.tools > summary").first().click();
  await page.waitForFunction(
    (prev) => {
      const s = document.querySelector("tbody tr details.tools > summary");
      return s && !s.textContent.trim().startsWith("Show tools");
    },
    null,
    { timeout: 15000 },
  );
  console.log("PASS first row expanded its tool list");

  const firstTools = await page.$$eval("tbody tr details.tools[open] .tool-item .mono", (els) =>
    els.map((e) => (e.textContent || "").trim()));
  const foreignFirst = firstTools.filter((n) => !n.startsWith(`${firstSlug}__`));
  if (firstTools.length === 0) console.log(`NOTE ${firstSlug} has no tools; expansion state still proven`);
  else if (foreignFirst.length) failures.push(`tools listed for ${firstSlug} include foreign tools: ${JSON.stringify(foreignFirst.slice(0, 5))}`);
  else console.log(`PASS ${firstSlug} lists ${firstTools.length} tools, all names start with "${firstSlug}__"`);

  // 2) exactly ONE expanded details row; the others still show "Show tools"
  const expanded = await page.$$eval("tbody tr details.tools[open]", (els) => els.length);
  if (expanded !== 1) failures.push(`expected exactly 1 expanded tools row, got ${expanded}`);
  else console.log("PASS only the clicked row is expanded");
  const collapsed = await page.$$eval("tbody tr details.tools > summary", (els) =>
    els.map((e) => (e.textContent || "").trim()).filter((t) => t.startsWith("Show tools")).length);
  if (collapsed !== slugs.length - 1) failures.push(`expected ${slugs.length - 1} other rows still collapsed, found ${collapsed}`);
  else console.log(`PASS the other ${collapsed} row(s) still show "Show tools"`);

  // 3) close row 1, open a row WITH tools (prefer "woo", else row 2)
  await firstRow.locator("details.tools > summary").first().click();
  await page.waitForFunction(() => !document.querySelector("tbody tr details.tools[open]"), null, { timeout: 10000 });
  console.log("PASS toggling the first row closed works");

  let targetIdx = slugs.findIndex((s) => s !== firstSlug && s === "woo");
  if (targetIdx < 0) targetIdx = 1;
  const targetRow = page.locator("tbody tr").nth(targetIdx);
  const targetSlug = ((await targetRow.locator(".slug").first().textContent()) || "").trim();
  await targetRow.locator("details.tools > summary").first().click();
  await page.waitForSelector("tbody tr details.tools[open] .tool-item", { timeout: 15000 });
  const secondTools = await page.$$eval("tbody tr details.tools[open] .tool-item .mono", (els) =>
    els.map((e) => (e.textContent || "").trim()));
  const foreign2 = secondTools.filter((n) => !n.startsWith(`${targetSlug}__`));
  if (!secondTools.length) failures.push(`server ${targetSlug} shows no tools`);
  else if (foreign2.length) failures.push(`${targetSlug} shows foreign tools: ${JSON.stringify(foreign2.slice(0, 5))}`);
  else console.log(`PASS ${targetSlug} lists ${secondTools.length} of its own tools`);
  const expandedAfter = await page.$$eval("tbody tr details.tools[open]", (els) => els.length);
  if (expandedAfter !== 1) failures.push(`after opening row 2, ${expandedAfter} rows are expanded (expected 1)`);
  else console.log("PASS opening the second row did not open any other row");

  if (errors.length) failures.push(`page errors: ${errors.join("; ")}`);

  if (failures.length) {
    console.error(`\n${failures.length} FAILING check(s):`);
    for (const f of failures) console.error(` - ${f}`);
    process.exit(1);
  }
  console.log("\nALL SERVER-TOOLS CHECKS PASSED");
} finally {
  await browser.close();
}
