#!/usr/bin/env node
// Motion proof (dark mode + motion pass, requirement 9):
//   - a stat number sampled at ~100ms and again at 1s ends on the API value
//     (700ms count-up, exact real value at the end);
//   - with prefers-reduced-motion it shows the final value at 0ms;
//   - no console errors on the overview page.
// Run: node scripts/verify-motion.mjs (needs the live dashboard at
// DASHBOARD_URL, default http://dashboard.127.0.0.1.nip.io).
import { createRequire } from "node:module";
import * as browserAuth from "./lib/browser-auth.mjs";

const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");

const DASHBOARD_URL = process.env.DASHBOARD_URL || "http://dashboard.127.0.0.1.nip.io";

async function statProbe({ reducedMotion }) {
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  try {
    const admin = await browserAuth.adminLogin(DASHBOARD_URL);
    const ctx = await browser.newContext({ reducedMotion: reducedMotion ? "reduce" : "no-preference" });
    await ctx.addCookies(browserAuth.cookiePair(admin.cookie, DASHBOARD_URL));
    const page = await ctx.newPage();
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(`${DASHBOARD_URL}/overview?expanded=1`, { waitUntil: "networkidle" });
    // API truth for the first stat tile (total calls in range).
    const apiCalls = await page.evaluate(async () => {
      const r = await fetch("/api/stats?range=week", { credentials: "include" });
      const j = await r.json();
      return j?.audit?.calls ?? null;
    });
    // Sample the rendered stat number early (~100ms) and late (1s).
    await page.waitForTimeout(100);
    const early = await page.evaluate(() => {
      const el = document.querySelector('[aria-label="Total tool calls"] .stat-num');
      return el ? el.textContent.trim() : null;
    });
    await page.waitForTimeout(900);
    const late = await page.evaluate(() => {
      const el = document.querySelector('[aria-label="Total tool calls"] .stat-num');
      return el ? el.textContent.trim() : null;
    });
    await ctx.close();
    return { apiCalls, early, late, errors };
  } finally {
    await browser.close();
  }
}

function num(s) {
  if (s == null) return null;
  const m = String(s).replace(/,/g, "").match(/-?[\d.]+/);
  return m ? parseFloat(m[0]) : null;
}

/* F1 item 3: hover motion proof.
   - normal motion: hovering a card changes its computed transform, a
     transition on transform exists, the hero gradient overlay glides, and
     pressing a button scales it to 0.97;
   - reduced motion: hovering/pressing leaves transform at none. */
async function hoverProbe({ reducedMotion }) {
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  try {
    const admin = await browserAuth.adminLogin(DASHBOARD_URL);
    const ctx = await browser.newContext({ reducedMotion: reducedMotion ? "reduce" : "no-preference" });
    await ctx.addCookies(browserAuth.cookiePair(admin.cookie, DASHBOARD_URL));
    const page = await ctx.newPage();
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(`${DASHBOARD_URL}/overview?expanded=1`, { waitUntil: "networkidle" });
    await page.waitForSelector(".card.stat");
    const card = await page.$(".card.stat");
    const before = await card.evaluate((el) => getComputedStyle(el).transform);
    const transition = await card.evaluate((el) => getComputedStyle(el).transitionProperty);
    await card.hover();
    await page.waitForTimeout(450);
    const after = await card.evaluate((el) => getComputedStyle(el).transform);
    const shadow = await card.evaluate((el) => getComputedStyle(el).boxShadow);
    // hero gradient drift overlay
    const hero = await page.$(".stat.hero");
    let heroBefore = null, heroAfter = null;
    if (hero) {
      heroBefore = await hero.evaluate((el) => getComputedStyle(el, "::after").transform);
      await hero.hover();
      await page.waitForTimeout(800);
      heroAfter = await hero.evaluate((el) => getComputedStyle(el, "::after").transform);
    }
    // button press scale
    const btn = await page.$(".seg button:not(.on)");
    let btnRest = null, btnActive = null;
    if (btn) {
      btnRest = await btn.evaluate((el) => getComputedStyle(el).transform);
      const box = await btn.boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.waitForTimeout(350);
      btnActive = await btn.evaluate((el) => getComputedStyle(el).transform);
      await page.mouse.up();
    }
    await ctx.close();
    return { before, after, transition, shadow, heroBefore, heroAfter, btnRest, btnActive, errors };
  } finally {
    await browser.close();
  }
}

async function run() {
  const failures = [];
  const full = await statProbe({ reducedMotion: false });
  console.log(`motion full: api=${full.apiCalls} early=${JSON.stringify(full.early)} late=${JSON.stringify(full.late)}`);
  if (full.apiCalls == null) failures.push("could not read /api/stats audit.calls");
  else if (num(full.late) !== full.apiCalls) failures.push(`count-up did not end on API value: late=${full.late} api=${full.apiCalls}`);
  else console.log("PASS count-up ends on the API value at 1s");
  if (full.errors.length) failures.push(`console errors (full motion): ${full.errors.join("; ")}`);
  else console.log("PASS no console errors (full motion)");

  const rm = await statProbe({ reducedMotion: true });
  console.log(`motion reduced: api=${rm.apiCalls} early=${JSON.stringify(rm.early)} late=${JSON.stringify(rm.late)}`);
  // With reduced motion the tile must show the final value immediately.
  const earlyProbe = await (async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const admin = await browserAuth.adminLogin(DASHBOARD_URL);
      const ctx = await browser.newContext({ reducedMotion: "reduce" });
      await ctx.addCookies(browserAuth.cookiePair(admin.cookie, DASHBOARD_URL));
      const page = await ctx.newPage();
      await page.goto(`${DASHBOARD_URL}/overview?expanded=1`, { waitUntil: "domcontentloaded" });
      // 0ms: read as soon as the stat tile exists.
      await page.waitForSelector('[aria-label="Total tool calls"] .stat-num');
      const v = await page.evaluate(() => document.querySelector('[aria-label="Total tool calls"] .stat-num').textContent.trim());
      await ctx.close();
      return v;
    } finally { await browser.close(); }
  })();
  console.log(`motion reduced @0ms: ${JSON.stringify(earlyProbe)}`);
  if (rm.apiCalls != null && num(earlyProbe) !== rm.apiCalls) failures.push(`reduced motion did not show final at 0ms: got=${earlyProbe} api=${rm.apiCalls}`);
  else console.log("PASS reduced motion shows the final value at 0ms");
  if (rm.errors.length) failures.push(`console errors (reduced motion): ${rm.errors.join("; ")}`);
  else console.log("PASS no console errors (reduced motion)");

  /* F1 item 3: hover motion */
  const hm = await hoverProbe({ reducedMotion: false });
  console.log(`hover full: card ${hm.before} -> ${hm.after} transition=${hm.transition} shadow=${hm.shadow}`);
  console.log(`hover full: hero ::after ${hm.heroBefore} -> ${hm.heroAfter}; button ${hm.btnRest} -> ${hm.btnActive}`);
  if (!String(hm.transition).includes("transform")) failures.push(`card has no transform transition (got ${hm.transition})`);
  else console.log("PASS card has a transform transition");
  if (hm.before === hm.after || hm.after === "none") failures.push(`card hover did not change transform (${hm.before} -> ${hm.after})`);
  else console.log("PASS card hover changes transform");
  if (hm.shadow === "none" || hm.shadow === "") failures.push("card hover did not deepen the shadow");
  else console.log("PASS card hover deepens the shadow");
  if (hm.heroBefore !== null && hm.heroBefore === hm.heroAfter) failures.push(`hero gradient overlay did not drift (${hm.heroBefore})`);
  else if (hm.heroBefore !== null) console.log("PASS hero gradient overlay drifts on hover");
  if (hm.btnActive !== null) {
    const m = /matrix\(([^)]+)\)/.exec(hm.btnActive || "");
    const scale = m ? parseFloat(m[1].split(",")[3]) : null;
    if (scale == null || Math.abs(scale - 0.97) > 0.02) failures.push(`button press did not scale to 0.97 (got ${hm.btnActive})`);
    else console.log("PASS button press scales to 0.97");
  }
  if (hm.errors.length) failures.push(`console errors (hover motion): ${hm.errors.join("; ")}`);
  else console.log("PASS no console errors (hover motion)");

  const hr = await hoverProbe({ reducedMotion: true });
  console.log(`hover reduced: card ${hr.before} -> ${hr.after}; hero ${hr.heroBefore} -> ${hr.heroAfter}; button ${hr.btnRest} -> ${hr.btnActive}`);
  if (hr.after !== "none") failures.push(`reduced motion: card hover transform is ${hr.after}, expected none`);
  else console.log("PASS reduced motion: card hover transform stays none");
  if (hr.heroAfter !== hr.heroBefore) failures.push(`reduced motion: hero ::after moved (${hr.heroBefore} -> ${hr.heroAfter})`);
  else console.log("PASS reduced motion: hero overlay does not drift");
  if (hr.btnActive !== "none" && hr.btnActive !== null && !/matrix\(1[,)]/.test(hr.btnActive || "")) failures.push(`reduced motion: button press transform is ${hr.btnActive}`);
  else console.log("PASS reduced motion: button press has no scale");
  if (hr.errors.length) failures.push(`console errors (reduced hover): ${hr.errors.join("; ")}`);
  else console.log("PASS no console errors (reduced hover)");

  if (failures.length) {
    console.error(`\n${failures.length} FAILING check(s):`);
    for (const f of failures) console.error(` - ${f}`);
    process.exit(1);
  }
  console.log("\nALL MOTION CHECKS PASSED");
}

run().catch((e) => { console.error(e); process.exit(1); });
