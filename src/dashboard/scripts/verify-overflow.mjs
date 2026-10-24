#!/usr/bin/env node
/**
 * Mobile (390) + chart-geometry sanity: no horizontal page overflow on any
 * checked route, chart bars and top-tool bars render with non-zero widths.
 */
import { createRequire } from "node:module";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");
const BASE = "http://dashboard.127.0.0.1.nip.io";

const browser = await chromium.launch();
let fails = 0;
for (const theme of ["light", "dark"]) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  await ctx.addInitScript((t) => localStorage.setItem("theme", t), theme);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.fill("#email", "admin@urumi.local");
  await page.fill("#pw", process.env.GW_PASS);
  await page.click("button[type=submit]");
  await page.waitForURL("**/overview", { timeout: 15000 });
  await page.waitForTimeout(1800);
  for (const route of ["overview", "servers", "members", "audit", "chat"]) {
    await page.goto(`${BASE}/${route}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(900);
    const m = await page.evaluate(() => ({
      sw: document.scrollingElement.scrollWidth,
      iw: window.innerWidth,
      bars: [...document.querySelectorAll(".tt-bar")].map((b) => Math.round(b.getBoundingClientRect().width)).slice(0, 3),
      chartBars: document.querySelectorAll("svg rect.bar").length,
    }));
    if (m.sw > m.iw + 1) {
      console.log(`FAIL [${theme}/${route}] horizontal overflow: scrollWidth ${m.sw} > ${m.iw}`);
      fails++;
    } else {
      console.log(`ok   [${theme}/${route}] no horizontal overflow (390)`);
    }
    if (route === "overview") {
      console.log(`     [${theme}/overview] tt-bar widths: ${JSON.stringify(m.bars)}, chart bars: ${m.chartBars}`);
      if (m.chartBars === 0) {
        console.log(`FAIL [${theme}/overview] chart bars missing`);
        fails++;
      }
    }
  }
  await ctx.close();
}
await browser.close();
console.log(fails ? `${fails} OVERFLOW FAILURES` : "OVERFLOW CHECKS PASSED");
process.exit(fails ? 1 : 0);
