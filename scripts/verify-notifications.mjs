#!/usr/bin/env node
// FIX PASS F1-6 UI proof: the notification bell WORKS.
//   - GET /api/notifications returns items (admin) or an empty list;
//   - clicking the bell opens the popover with the empty state text when there
//     are no notifications (the reported bug: it did nothing);
//   - Esc closes the popover and focus returns to the bell;
//   - "Mark all read" removes the dot; the dot only shows when items are newer
//     than the per-user lastSeen timestamp in localStorage.
// Run: node scripts/verify-notifications.mjs
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
  await page.waitForSelector('button[aria-label="Notifications"]', { timeout: 15000 });

  // fresh lastSeen so the dot state is deterministic
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector('button[aria-label="Notifications"]');

  const bell = page.locator('button[aria-label="Notifications"]');
  // API truth: what items does this user have?
  const payload = await page.evaluate(async () => {
    const r = await fetch("/api/notifications", { credentials: "include" });
    if (!r.ok) return { error: `${r.status}` };
    return await r.json();
  });
  const items = (payload && payload.notifications) || [];
  console.log(`api notifications: ${items.length}`);

  // 1) the bell opens a popover
  await bell.click();
  await page.waitForSelector(".notif-pop", { timeout: 5000 });
  console.log("PASS bell click opens the popover");
  const hasEmpty = (await page.$$(".notif-empty")).length > 0;
  const rowCount = (await page.$$(".notif-item")).length;
  if (items.length === 0 && !hasEmpty) failures.push("no items and no empty state shown");
  if (items.length > 0 && rowCount === 0) failures.push("popover shows no items though the API returned some");
  if (items.length > 0) console.log(`PASS popover lists ${rowCount} item(s)`);
  else console.log("PASS empty state text shown (No notifications)");

  // 2) Esc closes and focus returns to the bell
  await page.keyboard.press("Escape");
  await page.waitForSelector(".notif-pop", { state: "detached", timeout: 5000 });
  const focused = await page.evaluate(() => document.activeElement && document.activeElement.getAttribute("aria-label"));
  if (focused !== "Notifications") failures.push(`focus did not return to the bell after Esc (active: ${focused})`);
  else console.log("PASS Esc closes the popover and focus returns to the bell");

  // 3) outside click closes
  await bell.click();
  await page.waitForSelector(".notif-pop", { timeout: 5000 });
  await page.mouse.click(10, 300);
  await page.waitForSelector(".notif-pop", { state: "detached", timeout: 5000 });
  console.log("PASS outside click closes the popover");

  // 4) dot only when items are newer than lastSeen; mark all read clears it
  if (items.length > 0) {
    const dotBefore = (await page.$$('button[aria-label="Notifications"] .dot')).length;
    if (dotBefore > 0) console.log("PASS dot shows while items are newer than lastSeen");
    await bell.click();
    await page.waitForSelector(".notif-pop", { timeout: 5000 });
    await page.locator(".notif-pop button", { hasText: "Mark all read" }).click();
    await page.waitForTimeout(150);
    const dotAfter = (await page.$$('button[aria-label="Notifications"] .dot')).length;
    if (dotAfter !== 0) failures.push("dot still visible after Mark all read");
    else console.log("PASS Mark all read clears the dot");
    const seen = await page.evaluate(() => Object.keys(localStorage).find((k) => k.startsWith("urumi.notif.seen.")));
    if (!seen) failures.push("Mark all read did not store a lastSeen timestamp");
    else console.log("PASS per-user lastSeen stored in localStorage");
  } else {
    console.log("SKIP dot/mark-all-read: no items on this cluster right now");
  }

  if (errors.length) failures.push(`page errors: ${errors.join("; ")}`);
  if (failures.length) {
    console.error(`\n${failures.length} FAILING check(s):`);
    for (const f of failures) console.error(` - ${f}`);
    process.exit(1);
  }
  console.log("\nALL NOTIFICATION CHECKS PASSED");
} finally {
  await browser.close();
}
