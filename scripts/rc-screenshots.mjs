#!/usr/bin/env node
// RC-VERIFY UI evidence: Stores, Metrics, Hosted servers, Permissions dialog and
// (when OAUTH_URL is set) the OAuth consent page, at 1440 and 390, light + dark.
// Console errors are collected per screenshot and printed in a summary.
// Output: artifacts/screenshots/rc-verify/ (gitignored). Never prints credentials.
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
import { mkdirSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { adminLogin, cookiePair } from "./lib/browser-auth.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DASHBOARD_URL = process.env.DASHBOARD_URL || "http://dashboard.rc.127.0.0.1.nip.io";
const OAUTH_URL = process.env.OAUTH_URL || ""; // full /oauth/authorize?... URL when enabled
const OUT = join(__dirname, "..", "artifacts", "screenshots", "rc-verify");

const VIEWPORTS = [
  { name: "1440", width: 1440, height: 900 },
  { name: "390", width: 390, height: 844 },
];
const THEMES = ["light", "dark"];

const DASHBOARD_PAGES = [
  { path: "/stores", label: "stores" },
  { path: "/metrics", label: "metrics" },
  { path: "/hosted", label: "hosted-servers" },
  { path: "/servers", label: "permissions", openPermissions: true },
];

const consoleIssues = [];

async function shot(browser, cookies, { url, label, viewport, theme, openPermissions }) {
  const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height } });
  if (cookies) await context.addCookies(cookies);
  const page = await context.newPage();
  const issues = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") issues.push(`console.error: ${msg.text().slice(0, 300)}`);
  });
  page.on("pageerror", (err) => issues.push(`pageerror: ${String(err).slice(0, 300)}`));
  page.on("requestfailed", (req) => issues.push(`requestfailed: ${req.method()} ${req.url().slice(0, 200)} ${req.failure()?.errorText}`));
  // theme before any app script runs
  await page.addInitScript((t) => { try { localStorage.setItem("theme", t); } catch {} }, theme);
  const resp = await page.goto(url, { waitUntil: "networkidle", timeout: 45000 });
  if (openPermissions) {
    const btn = page.locator('button:has-text("Permissions")').first();
    await btn.waitFor({ state: "visible", timeout: 15000 });
    await btn.click();
    await page.waitForTimeout(800); // dialog render + focus
  }
  await page.waitForTimeout(600); // fonts/sparklines settle
  const file = join(OUT, `${label}-${viewport.name}-${theme}.png`);
  await page.screenshot({ path: file, fullPage: false });
  for (const i of issues) consoleIssues.push({ shot: `${label}-${viewport.name}-${theme}`, issue: i });
  console.log(`shot ${label}-${viewport.name}-${theme} -> ${resp ? resp.status() : "?"} ${issues.length === 0 ? "(no console issues)" : `(${issues.length} issues)`}`);
  await context.close();
}

(async () => {
  mkdirSync(OUT, { recursive: true });
  const admin = await adminLogin(DASHBOARD_URL);
  const cookies = cookiePair(admin.cookie, DASHBOARD_URL);
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of VIEWPORTS) {
      for (const theme of THEMES) {
        for (const pg of DASHBOARD_PAGES) {
          await shot(browser, cookies, { url: DASHBOARD_URL + pg.path, label: pg.label, viewport, theme, openPermissions: pg.openPermissions });
        }
        if (OAUTH_URL) {
          await shot(browser, cookies, { url: OAUTH_URL, label: "oauth-consent", viewport, theme });
        }
      }
    }
  } finally {
    await browser.close();
  }
  writeFileSync(join(OUT, "console-issues.json"), JSON.stringify(consoleIssues, null, 2));
  console.log(`DONE: ${consoleIssues.length} console issues in total (details in console-issues.json)`);
})().catch((e) => { console.error("FATAL", e); process.exit(1); });
