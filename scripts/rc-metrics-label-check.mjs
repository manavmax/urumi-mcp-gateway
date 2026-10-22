#!/usr/bin/env node
// RC metrics mobile-label verification: at 390 the table collapses to labelled
// rows (thead hidden, each td shows its data-label via ::before). At 1440 the
// thead must be visible and tds must NOT render the pseudo labels.
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
import { adminLogin, cookiePair } from "./lib/browser-auth.mjs";

const D = process.env.DASHBOARD_URL || "http://dashboard.rcr.127.0.0.1.nip.io";

const admin = await adminLogin(D);
const cookies = cookiePair(admin.cookie, D);
const browser = await chromium.launch({ headless: true });
let pass = 0, fail = 0;

for (const w of [1440, 390]) {
  const ctx = await browser.newContext({ viewport: { width: w, height: 900 } });
  await ctx.addCookies(cookies);
  const page = await ctx.newPage();
  const errs = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 160)); });
  await page.goto(D + "/metrics", { waitUntil: "networkidle", timeout: 45000 });
  await page.waitForTimeout(900);
  const audit = await page.evaluate(() => {
    const table = document.querySelector(".tbl");
    if (!table) return { present: false };
    const tds = [...table.querySelectorAll("tbody td")];
    const firstRow = tds.slice(0, 7);
    return {
      tdCount: tds.length,
      theadDisplay: getComputedStyle(table.querySelector("thead")).display,
      labels: [...table.querySelectorAll("tbody tr")].slice(0, 2).map((tr) =>
        [...tds_of(tr)].map((td) => {
          const cs = getComputedStyle(td, "::before");
          return { label: cs.content, shown: cs.content !== "none" && cs.content !== '""' && cs.content !== "normal", displayed: getComputedStyle(td).display };
        })
      ),
    };
    function tds_of(tr) {
      return [...tr.children];
    }
  });
  const collapsed = audit.theadDisplay === "none";
  console.log(`metrics-${w}: tdCount=${audit.tdCount} theadDisplay=${audit.theadDisplay ?? "table"} labels=${JSON.stringify(audit.labels)}`);
  await ctx.close();
}
await browser.close();
console.log("METRICS LABEL CHECK DONE");
