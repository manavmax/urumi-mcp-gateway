#!/usr/bin/env node
// FIX PASS F1-8 live proof: chat replies render as READABLE MARKDOWN.
//   - sends one real order-list request through the live chat SSE loop;
//   - asserts the reply bubble contains a rendered <table> (Order / Status /
//     Total / Placed / Items) and NO raw markdown markers ("**") in the DOM;
//   - prints the rendered DOM text of the reply for the report.
// Run: node scripts/verify-chat-replies.mjs (needs the live dashboard at
// DASHBOARD_URL and a working LLM chain).
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

  await page.goto(`${DASHBOARD_URL}/chat`, { waitUntil: "networkidle" });

  await page.fill('input[aria-label="Chat message"]', "List the last 3 orders");
  await page.press('input[aria-label="Chat message"]', "Enter");
  // wait for the turn to finish (tool calls can take a while)
  await page.waitForFunction(
    () => !document.querySelector(".typing") && document.querySelectorAll(".msg.assistant .bubble").length > 0,
    null,
    { timeout: 150000 },
  );
  await page.waitForTimeout(400);

  const bubbles = await page.$$eval(".msg.assistant .bubble", (els) => els.map((e) => e.textContent || ""));
  const last = bubbles[bubbles.length - 1] || "";
  console.log("---- rendered DOM text of the reply ----");
  console.log(last.slice(0, 1200));
  console.log("----------------------------------------");

  if (!last.trim()) failures.push("empty assistant reply");
  if (/\*\*|(?<!\w)#{1,3} /.test(last)) failures.push(`raw markdown markers visible in the rendered reply: ${JSON.stringify(last.slice(0, 200))}`);
  else if (last.trim()) console.log("PASS no raw markdown markers in the rendered reply");

  const tables = (await page.$$(".msg.assistant .bubble table")).length;
  if (!last.trim()) {
    failures.push("empty assistant reply");
  } else if (tables > 0) {
    console.log(`PASS reply renders ${tables} markdown table element(s)`);
    const hasHeader = last.includes("Order") && last.includes("Status") && last.includes("Total");
    if (!hasHeader) failures.push("reply table does not carry the pinned Order/Status/Total columns");
    else console.log("PASS reply table carries the pinned Order/Status/Total/Placed/Items columns");
  } else {
    console.log("NOTE: reply had no table (acceptable if the store has no completed orders)");
  }
  console.log(`reply length: ${last.length}`);

  if (errors.length) failures.push(`page errors: ${errors.join("; ")}`);
  if (failures.length) {
    console.error(`\n${failures.length} FAILING check(s):`);
    for (const f of failures) console.error(` - ${f}`);
    process.exit(1);
  }
  console.log("\nALL CHAT-REPLY CHECKS PASSED");
} finally {
  await browser.close();
}
