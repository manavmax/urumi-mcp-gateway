#!/usr/bin/env node
/**
 * DOM-level verification against the live deployment (both themes):
 *   1. data-theme attribute + persisted theme choice,
 *   2. computed styles of real elements match the token set per theme,
 *   3. helper text is gone (forbidden strings) and required content exists,
 *   4. the redesigned Overview shows the real data cards.
 * Exits 1 on any failure.
 */
import { createRequire } from "node:module";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");

const BASE = "http://dashboard.127.0.0.1.nip.io";
const EMAIL = "admin@urumi.local";
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "artifacts", "dashboard");

const TOKENS = {
  dark: { bg: "rgb(4, 8, 4)", surface: "rgb(26, 28, 25)", text: "rgb(227, 229, 225)", muted: "rgb(168, 171, 166)", faint: "rgb(139, 142, 137)" },
  light: { bg: "rgb(236, 235, 231)", surface: "rgb(255, 255, 255)", text: "rgb(20, 23, 28)", muted: "rgb(95, 102, 115)", faint: "rgb(95, 102, 115)" },
};

/* helper text that must NOT appear anywhere (implementation explanations) */
const FORBIDDEN = [
  "Fernet", "POST /api/servers", "enforced server-side", "one namespace per",
  "via GET /api/", "from the audit table", "stored in this browser",
  "SHA-256", "bars = calls", "across enabled servers", "Security posture",
  "Static text, not a metric", "The gateway routes calls to enabled servers",
];

/* content that must exist per page (titles, labels, kept notices, controls) */
const REQUIRED = {
  overview: ["Tool calls", "Success rate", "p95 latency", "Errors", "Top tools",
    "Fleet status", "Account & team", "Recent activity", "Servers",
    "Manage keys", "time__get_current_time"],
  servers: ["All servers", "Add server", "Permissions", "Check now", "Status"],
  members: ["Users", "API keys", "Keys are shown once at creation.", "Create API key",
    "Limit/min"],
  audit: ["Tool calls", "Admin activity", "CSV export", "Filters", "sorted newest first"],
  metrics: ["Upstream tool calls, last", "Error rate", "p95", "Top failure reasons"],
  stores: [],  /* feature-flag gated: enabled content or the disabled panel */
  hosted: [],
  chat: ["Chat history", "New chat", "What would you like to do"],
};

let failures = 0;
const fail = (m) => { failures++; console.error(`FAIL ${m}`); };
const ok = (m) => console.log(`ok   ${m}`);

const browser = await chromium.launch();

for (const theme of ["light", "dark"]) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  await ctx.addInitScript((t) => {
    try { localStorage.setItem("theme", t); } catch { /* ignore */ }
  }, theme);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.fill("#email", EMAIL);
  await page.fill("#pw", process.env.GW_PASS);
  await page.click("button[type=submit]");
  await page.waitForURL("**/overview", { timeout: 15000 });
  await page.waitForTimeout(2000);

  ok(`[${theme}] logged in, theme attr = ${await page.getAttribute("html", "data-theme")}`);
  if ((await page.getAttribute("html", "data-theme")) !== theme) fail(`[${theme}] data-theme not applied`);

  for (const route of Object.keys(REQUIRED)) {
    await page.goto(`${BASE}/${route}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1200);

    /* theme still applied after client-side navigation (persistence) */
    if ((await page.getAttribute("html", "data-theme")) !== theme) {
      fail(`[${theme}/${route}] theme attr lost after navigation`);
    }

    /* computed styles of real elements (only selectors the page actually has) */
    const styles = await page.evaluate(() => {
      const pick = (sel, prop) => {
        const el = document.querySelector(sel);
        return el ? getComputedStyle(el)[prop] : null;
      };
      return {
        bodyBg: getComputedStyle(document.body).backgroundColor,
        cardBg: pick(".card:not(.stat\.hero)", "backgroundColor"),
        heroImg: pick(".stat.hero", "backgroundImage"),
        statNum: pick(".card.stat:not(.hero) .stat-num", "color"),
        statLabel: pick(".card.stat:not(.hero) .stat-label", "color"),
        title: pick(".card-title", "color"),
        chipOk: pick(".chip-ok", "backgroundColor"),
        btnPrimary: pick(".btn-primary", "backgroundColor"),
        disabled: !!document.querySelector(".feature-disabled"),
      };
    });
    const T = TOKENS[theme];
    const wantChipOk = theme === "dark" ? "rgb(20, 53, 47)" : "rgb(221, 237, 228)";
    const wantBtn = theme === "dark" ? "rgb(227, 229, 225)" : "rgb(20, 23, 28)";
    const checks = [["body bg", styles.bodyBg, T.bg], ["card bg", styles.cardBg, T.surface]];
    if (!styles.disabled) checks.push(["card-title text", styles.title, T.text]);
    if (styles.statNum !== null) checks.push(["stat-num text", styles.statNum, T.text], ["stat-label text", styles.statLabel, T.muted]);
    if (styles.chipOk !== null) checks.push(["chip-ok bg", styles.chipOk, wantChipOk]);
    if (styles.btnPrimary !== null) checks.push(["btn-primary bg", styles.btnPrimary, wantBtn]);
    for (const [name, got, want] of checks) {
      if (got === want) ok(`[${theme}/${route}] ${name}`);
      else fail(`[${theme}/${route}] ${name}: got ${got}, want ${want}`);
    }
    if (route === "overview" && styles.heroImg && styles.heroImg.includes("linear-gradient")) {
      ok(`[${theme}/overview] hero tile carries the gradient fill`);
    }

    /* text content: forbidden + required */
    const text = (await page.evaluate(() => document.body.innerText)).replace(/\s+/g, " ");
    for (const bad of FORBIDDEN) {
      if (text.toLowerCase().includes(bad.toLowerCase())) fail(`[${theme}/${route}] forbidden helper text present: "${bad}"`);
    }
    let required = REQUIRED[route];
    if ((route === "stores" || route === "hosted") && styles.disabled) {
      required = ["This feature is not enabled on this deployment"];
      ok(`[${theme}/${route}] feature-flag off: disabled panel shown (gating intact)`);
    }
    for (const need of required) {
      if (!text.toLowerCase().includes(need.toLowerCase())) fail(`[${theme}/${route}] required content missing: "${need}"`);
    }

    /* overview-specific structure */
    if (route === "overview") {
      const tt = await page.evaluate(() => ({
        rows: document.querySelectorAll(".tt-row").length,
        bars: document.querySelectorAll(".tt-bar").length,
        svg: document.querySelectorAll("svg").length,
        segButtons: document.querySelectorAll(".seg button").length,
        table: !!document.querySelector("table"),
        sparkCells: document.querySelectorAll("td svg").length,
      }));
      if (tt.rows >= 3 && tt.bars >= 3) ok(`[${theme}/overview] top tools rows: ${tt.rows}`);
      else fail(`[${theme}/overview] top tools rows=${tt.rows}`);
      if (tt.svg >= 4) ok(`[${theme}/overview] inline svgs: ${tt.svg}`);
      else fail(`[${theme}/overview] too few svgs: ${tt.svg}`);
      if (tt.segButtons === 3) ok(`[${theme}/overview] range selector present (3 buttons)`);
      else fail(`[${theme}/overview] range selector buttons=${tt.segButtons}`);
      if (tt.table) ok(`[${theme}/overview] servers table present`);
      else fail(`[${theme}/overview] servers table missing`);
      if (tt.sparkCells >= 1) ok(`[${theme}/overview] per-server sparklines: ${tt.sparkCells}`);
    }
  }
  await ctx.close();
}

await browser.close();
console.log(failures ? `\n${failures} FAILURES` : "\nALL DOM CHECKS PASSED");
process.exit(failures ? 1 : 0);
