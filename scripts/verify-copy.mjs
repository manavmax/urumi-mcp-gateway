#!/usr/bin/env node
// F1 item 5 proof: copy works on the insecure http://*.nip.io origin.
// For every copy button (Members key reveal, member Overview MCP URL):
// click Copy, focus an input, press Control+V, assert the pasted value
// equals the key/URL. Also asserts the button shows "Copied" (not the
// manual hint) so the execCommand fallback really ran.
//   node scripts/verify-copy.mjs
import { createRequire } from "node:module";
import * as browserAuth from "./lib/browser-auth.mjs";

const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");

const DASHBOARD_URL = process.env.DASHBOARD_URL || "http://dashboard.127.0.0.1.nip.io";

async function run() {
  const failures = [];
  const browser = await chromium.launch({ headless: true });
  try {
    const admin = await browserAuth.adminLogin(DASHBOARD_URL);
    const member = await browserAuth.createThrowawayMember(DASHBOARD_URL, admin.cookie, admin.csrf, "copy-");
    let memberSession = null;
    try {
      /* ---- admin: new key reveal copy on /members ---- */
      {
        const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
        await ctx.addCookies(browserAuth.cookiePair(admin.cookie, DASHBOARD_URL));
        const page = await ctx.newPage();
        await page.goto(`${DASHBOARD_URL}/members`, { waitUntil: "networkidle" });
        await page.click('button:has-text("Create API key"), button:has-text("Create key for me")');
        await page.waitForSelector(".reveal .keybox code");
        const key = (await page.textContent(".reveal .keybox code")).trim();
        await page.click('.reveal button:has-text("Copy")');
        await page.waitForFunction(() => {
          const b = document.querySelector(".reveal button");
          return b && b.textContent.includes("Copied");
        }, { timeout: 3000 }).catch(() => { failures.push("key reveal: button did not show Copied"); });
        const label = (await page.textContent(".reveal button")).trim();
        if (label.includes("Ctrl")) failures.push(`key reveal: got manual fallback hint (${label})`);
        // Paste into an input and compare.
        await page.click("#iv-email").catch(() => {});
        await page.focus("#iv-email");
        await page.keyboard.press(process.platform === "darwin" ? "Meta+V" : "Control+V");
        await page.waitForTimeout(200);
        const pasted = await page.inputValue("#iv-email").catch(() => null);
        if (pasted !== key) failures.push(`key reveal: pasted != key (pasted=${JSON.stringify(pasted)} key=${JSON.stringify(key)})`);
        else console.log(`PASS key reveal copy: pasted ${key.slice(0, 12)}... equals the created key`);
        await ctx.close();
      }

      /* ---- member: MCP URL copy on /overview ---- */
      {
        memberSession = await browserAuth.loginAs(DASHBOARD_URL, member.email, member.password);
        const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
        await ctx.addCookies(browserAuth.cookiePair(memberSession.cookie, DASHBOARD_URL));
        const page = await ctx.newPage();
        await page.goto(`${DASHBOARD_URL}/overview`, { waitUntil: "networkidle" });
        await page.waitForSelector('[aria-label="Connect your client"] .keybox code');
        const url = (await page.textContent('[aria-label="Connect your client"] .keybox code')).trim();
        await page.click('[aria-label="Connect your client"] button:has-text("Copy")');
        await page.waitForFunction(() => {
          const b = document.querySelector('[aria-label="Connect your client"] button');
          return b && b.textContent.includes("Copied");
        }, { timeout: 3000 }).catch(() => { failures.push("MCP URL: button did not show Copied"); });
        const label = (await page.textContent('[aria-label="Connect your client"] button')).trim();
        if (label.includes("Ctrl")) failures.push(`MCP URL: got manual fallback hint (${label})`);
        await page.click('input[aria-label="Search"]').catch(() => {});
        await page.focus('input[aria-label="Search"]');
        await page.keyboard.press(process.platform === "darwin" ? "Meta+V" : "Control+V");
        await page.waitForTimeout(200);
        const pasted = await page.inputValue('input[aria-label="Search"]').catch(() => null);
        if (pasted !== url) failures.push(`MCP URL: pasted != url (pasted=${JSON.stringify(pasted)} url=${JSON.stringify(url)})`);
        else console.log(`PASS MCP URL copy: pasted ${pasted} equals the rendered URL`);
        await ctx.close();
      }
    } finally {
      if (memberSession) await browserAuth.deleteMember(DASHBOARD_URL, admin.cookie, admin.csrf, member.id);
    }
  } finally {
    await browser.close();
  }
  if (failures.length) {
    console.error(`\n${failures.length} COPY FAILURES:`);
    for (const f of failures) console.error(` - ${f}`);
    process.exit(1);
  }
  console.log("\nALL COPY CHECKS PASSED");
}

run().catch((e) => { console.error(e); process.exit(1); });
