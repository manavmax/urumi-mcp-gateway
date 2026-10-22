#!/usr/bin/env node
// RC-VERIFY layout audit (programmatic, honest): per page/viewport/theme check
//   - horizontal overflow (scrollWidth > innerWidth)
//   - elements extending past the right edge (layout bugs, not taste)
//   - permissions dialog: Save reachable (visible or dialog scrolls to it, ADR-053)
// Output: artifacts/screenshots/rc-verify/layout-audit.json + console lines.
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
import { mkdirSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { adminLogin, cookiePair } from "./lib/browser-auth.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DASHBOARD_URL = process.env.DASHBOARD_URL || "http://dashboard.rc.127.0.0.1.nip.io";
const OUT = join(__dirname, "..", "artifacts", "screenshots", "rc-verify");

const VIEWPORTS = [{ name: "1440", width: 1440, height: 900 }, { name: "390", width: 390, height: 844 }];
const THEMES = ["light", "dark"];
const PAGES = [
  { path: "/stores", label: "stores" },
  { path: "/metrics", label: "metrics" },
  { path: "/hosted", label: "hosted-servers" },
  { path: "/servers", label: "permissions", dialog: true },
];

const results = [];

async function audit(browser, cookies, { path, label, viewport, theme, dialog }) {
  const ctx = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height } });
  await ctx.addCookies(cookies);
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 120)); });
  await page.addInitScript((t) => { try { localStorage.setItem("theme", t); } catch {} }, theme);
  await page.goto(DASHBOARD_URL + path, { waitUntil: "networkidle", timeout: 45000 });
  if (dialog) {
    const btn = page.locator('button:has-text("Permissions")').first();
    await btn.waitFor({ state: "visible", timeout: 15000 });
    await btn.click();
    await page.waitForTimeout(800);
  }
  await page.waitForTimeout(500);
  const audit = await page.evaluate(() => {
    const vw = window.innerWidth;
    const overflow = document.documentElement.scrollWidth - vw;
    const offenders = [];
    for (const el of document.querySelectorAll("body *")) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.right > vw + 8 && r.left < vw) {
        offenders.push(`${el.tagName.toLowerCase()}.${String(el.className).split(" ")[0]} right=${Math.round(r.right)} vw=${vw}`);
        if (offenders.length >= 5) break;
      }
    }
    const textLen = (document.body.innerText || "").trim().length;
    return { vw, overflow, offenders, textLen };
  });
  let dialogCheck = null;
  if (dialog) {
    dialogCheck = await page.evaluate(() => {
      const save = [...document.querySelectorAll("button")].find((b) => b.textContent.trim().toLowerCase() === "save");
      if (!save) return { savePresent: false };
      const r = save.getBoundingClientRect();
      const vh = window.innerHeight;
      const visible = r.top >= 0 && r.bottom <= vh && r.left >= 0 && r.right <= window.innerWidth;
      // can we scroll the dialog body to reach Save?
      let reachable = visible;
      if (!visible) {
        save.scrollIntoView({ block: "center" });
        const r2 = save.getBoundingClientRect();
        reachable = r2.top >= 0 && r2.bottom <= vh;
      }
      return { savePresent: true, saveInitiallyVisible: visible, saveReachableByScroll: reachable };
    });
  }
  results.push({ shot: `${label}-${viewport.name}-${theme}`, ...audit, dialogCheck, consoleErrors: [...new Set(errors)] });
  const flag = audit.overflow > 2 ? ` OVERFLOW ${audit.overflow}px` : "";
  console.log(`${label}-${viewport.name}-${theme}: text=${audit.textLen} chars${flag}${audit.offenders.length ? ` offenders=${audit.offenders.length}` : ""}${dialogCheck ? ` save=${JSON.stringify(dialogCheck)}` : ""}`);
  await ctx.close();
}

(async () => {
  mkdirSync(OUT, { recursive: true });
  const admin = await adminLogin(DASHBOARD_URL);
  const cookies = cookiePair(admin.cookie, DASHBOARD_URL);
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of VIEWPORTS)
      for (const theme of THEMES)
        for (const pg of PAGES)
          await audit(browser, cookies, { ...pg, viewport, theme });
  } finally {
    await browser.close();
  }
  writeFileSync(join(OUT, "layout-audit.json"), JSON.stringify(results, null, 2));
  const bad = results.filter((r) => r.overflow > 2 || (r.dialogCheck && r.dialogCheck.savePresent && !r.dialogCheck.saveReachableByScroll));
  console.log(`AUDIT DONE: ${results.length} combos, ${bad.length} with layout problems`);
})().catch((e) => { console.error("FATAL", e); process.exit(1); });
