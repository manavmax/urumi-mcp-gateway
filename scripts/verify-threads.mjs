#!/usr/bin/env node
// FIX PASS F1-4 proof: chat THREADS, not one history entry per message.
//   - send two messages in one page session -> exactly ONE thread with 4
//     messages, and the second answer proves the first message's context was
//     used (the model echoes the planted word);
//   - "New chat" starts a second thread;
//   - reload keeps both threads; clicking the first restores the conversation.
// Run: node scripts/verify-threads.mjs (needs the live dashboard at
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

  await page.goto(`${DASHBOARD_URL}/chat`, { waitUntil: "networkidle" });

  // fresh history for this user so the thread count is deterministic
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: "networkidle" });

  const storedThreads = () =>
    page.evaluate(() => {
      const key = Object.keys(localStorage).find((k) => k.startsWith("urumi.chat."));
      return key ? JSON.parse(localStorage.getItem(key) || "[]") : [];
    });

  async function send(text) {
    await page.fill('input[aria-label="Chat message"]', text);
    await page.press('input[aria-label="Chat message"]', "Enter");
    await page.waitForFunction(
      () => !document.querySelector(".typing") && document.querySelectorAll(".msg.assistant .bubble").length > 0,
      null,
      { timeout: 120000 },
    );
    await page.waitForTimeout(300);
  }

  // 1) two messages in ONE chat page session -> ONE thread
  await send("Remember the word BANANA. Reply with just: OK");
  await page.fill('input[aria-label="Chat message"]', "What word did I ask you to remember? Reply with just the word.");
  await page.locator('button[aria-label="Send"]').click();
  await page.waitForFunction(() => document.querySelectorAll(".msg").length >= 4 && !document.querySelector(".typing"), null, { timeout: 120000 });
  await page.waitForTimeout(300);

  const bubbleTexts = await page.$$eval(".msg.assistant .bubble", (els) => els.map((e) => e.textContent || ""));
  if (!/BANANA/i.test(bubbleTexts.join(" "))) {
    failures.push(`second answer did not use the first message's context: ${JSON.stringify(bubbleTexts)}`);
  } else console.log("PASS second answer used the first message's context (BANANA echoed)");

  const msgs = await page.$$eval(".msg", (els) => els.length);
  if (msgs !== 4) failures.push(`expected 4 messages in the open thread, got ${msgs}`);
  else console.log("PASS one conversation shows 4 messages (2 user + 2 assistant)");

  let threads = await storedThreads();
  if (threads.length !== 1) failures.push(`expected exactly 1 thread after two sends, got ${threads.length}`);
  else {
    const t = threads[0];
    if (t.count !== 4) failures.push(`thread count should be 4, got ${t.count}`);
    else console.log("PASS history has ONE thread with 4 messages");
    if (!/Remember the word BANANA/i.test(t.title || "")) failures.push(`thread title is not the first user message: ${JSON.stringify(t.title)}`);
    else console.log("PASS thread title is the first user message");
  }

  // 2) New chat starts a second thread
  await page.locator("button", { hasText: "New chat" }).click();
  await page.waitForSelector('input[aria-label="Chat message"]');
  await page.fill('input[aria-label="Chat message"]', "Reply with just: PING");
  await page.press('input[aria-label="Chat message"]', "Enter");
  await page.waitForFunction(() => document.querySelectorAll(".msg").length >= 2, null, { timeout: 120000 });
  await page.waitForFunction(() => !document.querySelector(".typing"), null, { timeout: 120000 });
  await page.waitForTimeout(300);
  threads = await storedThreads();
  if (threads.length !== 2) failures.push(`expected 2 threads after New chat, got ${threads.length}`);
  else console.log("PASS New chat created a second thread (history has 2)");
  if (threads.some((t) => t.count === 4)) console.log("PASS first thread kept 4 messages after the second thread started");
  else failures.push(`first thread did not keep 4 messages: ${JSON.stringify(threads.map((t) => t.count))}`);

  // 3) reload keeps both threads; clicking restores the conversation
  await page.reload({ waitUntil: "networkidle" });
  threads = await storedThreads();
  if (threads.length !== 2) failures.push(`reload lost threads: ${threads.length}`);
  else console.log("PASS reload keeps both threads");
  // open the first (most recent is the second thread); open the OLDEST thread
  await page.$$eval(".hist-item", (els) => els[els.length - 1].click());
  await page.waitForTimeout(200);
  const restored = await page.$$eval(".msg", (els) => els.length);
  if (restored !== 4) failures.push(`clicking the first thread did not restore 4 messages, got ${restored}`);
  else console.log("PASS clicking a thread restores the whole conversation (4 messages)");

  if (errors.length) failures.push(`page errors: ${errors.join("; ")}`);

  if (failures.length) {
    console.error(`\n${failures.length} FAILING check(s):`);
    for (const f of failures) console.error(` - ${f}`);
    process.exit(1);
  }
  console.log("\nALL THREAD CHECKS PASSED");
} finally {
  await browser.close();
}
