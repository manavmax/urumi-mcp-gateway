#!/usr/bin/env node
// RC: Permissions dialog Close must look like a proper secondary button
// (btn-secondary: surface bg + hairline inset shadow), not ghost/sm.
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
import { adminLogin, cookiePair } from "./lib/browser-auth.mjs";

const D = process.env.DASHBOARD_URL || "http://dashboard.rcr.127.0.0.1.nip.io";
const admin = await adminLogin(D);
const cookies = cookiePair(admin.cookie, D);
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await ctx.addCookies(cookies);
const page = await ctx.newPage();
await page.goto(D + "/servers", { waitUntil: "networkidle", timeout: 45000 });
const btn = page.locator('button:has-text("Permissions")').first();
await btn.waitFor({ state: "visible", timeout: 15000 });
await btn.click();
await page.waitForTimeout(800);
const audit = await page.evaluate(() => {
  const close = [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Close");
  if (!close) return { present: false };
  const cs = getComputedStyle(close);
  const dialogVisible = !!close.closest(".modal-card, .modal, [role=dialog], .perm-modal, .modal") || !!document.querySelector(".modal-body");
  return {
    present: true,
    cls: close.className,
    bg: cs.backgroundColor,
    border: cs.borderStyle !== "none" || cs.boxShadow !== "none",
    inDialog: dialogVisible,
    radius: cs.borderRadius,
    padding: cs.padding,
  };
});
console.log(JSON.stringify(audit));
await page.screenshot({ path: "/Users/manavsharma/Desktop/Urumi_AI/artifacts/screenshots/rc-verify/permissions-1440-light.png" });
await browser.close();
if (audit.present && audit.cls.includes("btn-secondary") && audit.inDialog) {
  console.log("PASS permissions Close = btn-secondary inside dialog");
  process.exit(0);
}
console.log("FAIL permissions dialog Close styling");
process.exit(1);
