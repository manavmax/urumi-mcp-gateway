#!/usr/bin/env node
/**
 * Screenshot every dashboard page in dark and light at 1440 (Overview also at
 * 390) against the LIVE kind deployment. Playwright-core from the dashboard's
 * existing devDependencies; chromium from the local playwright cache. No new
 * dependencies.
 *
 * Usage: GW_PASS=<admin password> node shoot-dashboard.mjs
 * Output: artifacts/dashboard/<page>-<theme>-<width>.png (full page)
 */
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");

const BASE = "http://dashboard.127.0.0.1.nip.io";
const EMAIL = "admin@urumi.local";
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "artifacts", "dashboard");

const PAGES = ["overview", "servers", "members", "audit", "metrics", "stores", "hosted", "chat"];
const THEMES = ["light", "dark"];

mkdirSync(OUT, { recursive: true });

const password = process.env.GW_PASS;
if (!password) {
  console.error("GW_PASS not set");
  process.exit(1);
}

const browser = await chromium.launch();
let failures = 0;

// one shared context per theme: login once, then visit every page
for (const theme of THEMES) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  await context.addInitScript((t) => {
    try { localStorage.setItem("theme", t); } catch { /* ignore */ }
  }, theme);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

  // login (the SPA starts on /login without a session)
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.fill("#email", EMAIL);
  await page.fill("#pw", password);
  await page.click("button[type=submit]");
  await page.waitForURL("**/overview", { timeout: 15000 });
  await page.waitForTimeout(2200); // data fetches + count-up + entrance settle

  for (const route of PAGES) {
    await page.goto(`${BASE}/${route}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(route === "chat" ? 1400 : 1800);
    const out = join(OUT, `${route}-${theme}-1440.png`);
    await page.screenshot({ path: out, fullPage: true });
    console.log(`wrote ${out}`);
    if (route === "overview") {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(700);
      const mOut = join(OUT, `${route}-${theme}-390.png`);
      await page.screenshot({ path: mOut, fullPage: true });
      console.log(`wrote ${mOut}`);
      await page.setViewportSize({ width: 1440, height: 960 });
    }
  }
  if (errors.length) {
    failures += 1;
    console.error(`THEME ${theme} page errors: ${errors.slice(0, 5).join(" | ")}`);
  }
  await context.close();
}

// login page in both themes (no session): fresh contexts, no init beyond theme
for (const theme of THEMES) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  await context.addInitScript((t) => {
    try { localStorage.setItem("theme", t); } catch { /* ignore */ }
  }, theme);
  const page = await context.newPage();
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.waitForTimeout(900);
  const out = join(OUT, `login-${theme}-1440.png`);
  await page.screenshot({ path: out, fullPage: true });
  console.log(`wrote ${out}`);
  await context.close();
}

await browser.close();
if (failures) {
  console.error(`${failures} theme(s) reported console/page errors`);
  process.exit(1);
}
console.log("done: screenshots captured, no console/page errors");
