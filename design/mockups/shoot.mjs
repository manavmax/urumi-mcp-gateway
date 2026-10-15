#!/usr/bin/env node
// STAGE 0 design mockups: render each static HTML to PNG at desktop (1440)
// and mobile (390) widths. Uses playwright-core from the dashboard devDeps
// (no new runtime dependency; no network access needed).
//
// Usage: node design/mockups/shoot.mjs
// Output: design/mockups/png/<name>-1440.png, <name>-390.png
//         (member variants: servers-member-*, members-member-*)
//         (login error state: login-error-1440/390.png)
//         (reduced motion: overview-reduced-1440.png)
//         (logo options: logo-options-1440.png)
// PNGs are gitignored: regenerate, never commit.

import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("../../src/dashboard/node_modules/playwright-core");

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT = join(__dirname, "png");

// file, query, settle time in ms (animations must finish before the shot)
const PAGES = [
  { name: "login", file: "login.html", query: "", settle: 900 },
  { name: "login-error", file: "login.html", query: "?error=1", settle: 900 },
  { name: "overview", file: "overview.html", query: "", settle: 1600 },
  { name: "overview-expanded", file: "overview.html", query: "?expanded=1", settle: 900 },
  { name: "overview-reduced", file: "overview.html", query: "?rm=1", settle: 500, reducedMotion: true },
  { name: "servers", file: "servers.html", query: "", settle: 1100 },
  { name: "servers-member", file: "servers.html", query: "?view=member", settle: 1100 },
  { name: "members", file: "members.html", query: "", settle: 1100 },
  { name: "members-member", file: "members.html", query: "?view=member", settle: 1100 },
  { name: "audit", file: "audit.html", query: "", settle: 1100 },
  { name: "chat", file: "chat.html", query: "", settle: 1400 },
  { name: "chat-thread", file: "chat.html", query: "?thread=1", settle: 1400 },
  { name: "palette-options", file: "palette-options.html", query: "", settle: 700 },
  { name: "logo-options", file: "logo-options.html", query: "", settle: 400 },
];

const VIEWPORTS = [
  { name: "1440", width: 1440, height: 960 },
  { name: "390", width: 390, height: 844 },
];

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
let failures = 0;
for (const page of PAGES) {
  const tab = await browser.newPage();
  if (page.reducedMotion) await tab.emulateMedia({ reducedMotion: "reduce" });
  const errors = [];
  tab.on("pageerror", (e) => errors.push(String(e)));
  tab.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  for (const vp of VIEWPORTS) {
    await tab.setViewportSize({ width: vp.width, height: vp.height });
    await tab.goto(`file://${join(__dirname, page.file)}${page.query}`, { waitUntil: "networkidle" });
    await tab.waitForTimeout(page.settle);
    const out = join(OUT, `${page.name}-${vp.name}.png`);
    await tab.screenshot({ path: out, fullPage: true });
    console.log(`wrote ${out}`);
  }
  if (errors.length) {
    failures++;
    console.error(`PAGE ERRORS in ${page.file}: ${errors.join(" | ")}`);
  }
  await tab.close();
}
await browser.close();
if (failures) {
  console.error(`${failures} page(s) reported console/page errors`);
  process.exit(1);
}
console.log("done: all pages rendered clean");
