#!/usr/bin/env node
// Landing page verification (ADR-080). Run against the dockerised page:
//   docker run -d --rm --name urumi-landing-test --user 101 \
//     --tmpfs /tmp:mode=1777 --tmpfs /var/cache/nginx:mode=1777 --tmpfs /var/run:mode=1777 \
//     -p 127.0.0.1:8090:8080 urumi/landing:0.1.0
//   LANDING_URL=http://127.0.0.1:8090 node scripts/landing-verify.mjs
//
// Gates, per the landing brief:
//   1. screenshots at 1440 and 390, light AND dark, into artifacts/landing/
//   2. ZERO external requests (every network request stays on the page origin)
//   3. no horizontal scroll at 390 or 1440, no overflowing element
//   4. AA text contrast on the key text elements in BOTH themes
//   5. zero console errors / page errors (a CSP violation would show here)
//   6. with features.js defaults: "Beyond the brief" and the video block stay hidden
// Screenshots are gitignored (artifacts/). This session cannot view images, so
// the geometry/contrast probes are the review; the PNGs are for a human.
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
const __dirname = dirname(fileURLToPath(import.meta.url));
const URL_BASE = process.env.LANDING_URL || "http://127.0.0.1:8090";
const OUT = join(__dirname, "..", "artifacts", "landing");
mkdirSync(OUT, { recursive: true });

const CASES = [
  { name: "desktop-dark", width: 1440, height: 900, theme: "dark" },
  { name: "desktop-light", width: 1440, height: 900, theme: "light" },
  { name: "mobile-dark", width: 390, height: 844, theme: "dark" },
  { name: "mobile-light", width: 390, height: 844, theme: "light" },
];

// In-page evaluator: WCAG ratio against the first OPAQUE ancestor background.
// Decorative SVG flow labels are excluded from the automated gate (the audible
// flow is described by the diagram's role="img" aria-label).
const EVAL_SRC = `
function parse(c) {
  let m = /rgba?\\(\\s*([\\d.]+)[,\\s]+([\\d.]+)[,\\s]+([\\d.]+)(?:[,\\s/]+([\\d.]+))?/.exec(String(c || ""));
  if (m) return [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3]), m[4] == null || m[4] === "" ? 1 : parseFloat(m[4])];
  m = /^#([0-9a-f]{3,8})$/i.exec(String(c || "").trim());
  if (m) {
    let h = m[1];
    if (h.length === 3) h = h.split("").map(x => x + x).join("");
    if (h.length === 6) return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16), 1];
  }
  return null;
}
function lum(r, g, b) {
  const f = (c) => { const s = c / 255; return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function ratio(a, b) {
  const x = lum(a[0], a[1], a[2]), y = lum(b[0], b[1], b[2]);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}
function effBg(el) {
  let node = el;
  while (node) {
    const c = parse(getComputedStyle(node).backgroundColor);
    if (c && c[3] === 1) return c;
    node = node.parentElement;
  }
  return [20, 22, 27, 1];
}
window.__check = (sels) => sels.map((s) => {
  const el = document.querySelector(s);
  if (!el) return { sel: s, missing: true, pass: true };
  const cs = getComputedStyle(el);
  const fg = parse(cs.color);
  if (!fg) return { sel: s, pass: true, note: "no color" };
  const bg = effBg(el);
  const r = ratio(fg, bg);
  const px = parseFloat(cs.fontSize);
  const large = (parseFloat(cs.fontWeight) >= 700 && px >= 18.66) || px >= 24;
  const need = large ? 3 : 4.5;
  return { sel: s, ratio: Math.round(r * 100) / 100, need, pass: r >= need };
});
`;

const CONTRAST_SELECTS = [
  ".announce p", ".hero h1", ".hero-sub", ".hero-note",
  ".code-title", ".code-block", ".tool-chips li", ".chip-sample",
  ".feature h3", ".feature-list li", ".steps h3", ".steps p",
  ".stat-label", ".stat-num", ".panel-title", ".panel-note",
  ".mock-table th", ".mock-table td", ".badge-ok", ".badge-deny",
  ".allow-card h3", ".mini h4", ".mini p", ".cta h2", ".cta p",
  ".footer-brand p", ".footer nav a", ".footer-base p",
  ".node-title", ".node-sub", ".diagram-note", ".k8s-line",
];

let fail = 0;
const browser = await chromium.launch();
try {
  for (const c of CASES) {
    const ctx = await browser.newContext({
      viewport: { width: c.width, height: c.height },
      colorScheme: c.theme,
    });
    await ctx.addInitScript((t) => {
      try { localStorage.setItem("landing-theme", t); } catch (e) {}
    }, c.theme);
    const page = await ctx.newPage();
    const requests = [];
    const consoleErrors = [];
    page.on("request", (r) => requests.push(r.url()));
    page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
    page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));

    await page.goto(URL_BASE, { waitUntil: "networkidle" });

    let caseFails = 0;

    // 1. theme applied by the pre-paint script
    const applied = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
    if (applied !== c.theme) { console.log(`FAIL ${c.name}: data-theme=${applied}, expected ${c.theme}`); caseFails++; }

    // 2. zero external requests
    const external = requests.filter((u) => !u.startsWith(URL_BASE));
    if (external.length) { console.log(`FAIL ${c.name}: external requests: ${external.join(", ")}`); caseFails++; }

    // 3. no horizontal scroll, no overflowing element
    const overflow = await page.evaluate(() => {
      const vw = document.documentElement.clientWidth;
      const sw = document.documentElement.scrollWidth;
      const wide = [];
      const scrollable = (el) => {
        for (let n = el; n && n !== document.body; n = n.parentElement) {
          const ox = getComputedStyle(n).overflowX;
          if (ox === "auto" || ox === "scroll") return true;
        }
        return false;
      };
      document.querySelectorAll("body *").forEach((el) => {
        const b = el.getBoundingClientRect();
        if (b.width > 0 && b.right > vw + 1 && !scrollable(el)) wide.push(String(el.className || el.tagName) + "|" + Math.round(b.right));
      });
      return { vw, sw, wide: wide.slice(0, 6) };
    });
    if (overflow.sw > overflow.vw + 1 || overflow.wide.length) {
      console.log(`FAIL ${c.name}: scrollWidth ${overflow.sw} vs ${overflow.vw}; wide: ${overflow.wide.join(", ")}`);
      caseFails++;
    }

    // 5. console / page errors (CSP violations surface here)
    if (consoleErrors.length) { console.log(`FAIL ${c.name}: console: ${consoleErrors.slice(0, 5).join(" | ")}`); caseFails++; }

    // 6. default config: beyond-brief and video stay hidden
    const hidden = await page.evaluate(() => ({
      beyond: document.getElementById("beyond").hidden,
      video: document.getElementById("video").hidden,
    }));
    if (!hidden.beyond || !hidden.video) { console.log(`FAIL ${c.name}: beyond/video visibility wrong: ${JSON.stringify(hidden)}`); caseFails++; }

    // gateway URL derived by main.js: never the placeholder, always /mcp
    const gwUrl = await page.evaluate(() => document.querySelector("[data-gateway-url]").textContent);
    if (!gwUrl.endsWith("/mcp") || gwUrl.includes("example.com")) { console.log(`FAIL ${c.name}: gateway url wrong: ${gwUrl}`); caseFails++; }
    if (!gwUrl.startsWith("http://dashboard.") && !gwUrl.startsWith("https://dashboard.")) { console.log(`FAIL ${c.name}: gateway url not dashboard.<apex>: ${gwUrl}`); caseFails++; }

    // Authorization placeholder is VISIBLE text with escaped angle brackets
    const bearer = await page.evaluate(() => document.querySelector(".code-block").textContent);
    if (!bearer.includes("Bearer <your-api-key>")) { console.log(`FAIL ${c.name}: Bearer placeholder not visible in code block`); caseFails++; }

    // copy button + data-driven store claim
    const hasCopy = await page.evaluate(() => !!document.getElementById("copyConfig"));
    if (!hasCopy) { console.log(`FAIL ${c.name}: copy button missing`); caseFails++; }
    const catalog = await page.evaluate(() => document.querySelector("[data-store-catalog]").textContent);
    if (catalog !== "12-product") { console.log(`FAIL ${c.name}: store catalog claim = "${catalog}", expected "12-product"`); caseFails++; }

    // sticky nav: header must sit at the viewport top while scrolled
    await page.evaluate(() => window.scrollTo(0, 1600));
    await page.waitForTimeout(150);
    const sticky = await page.evaluate(() => {
      const h = document.querySelector(".nav");
      const r = h.getBoundingClientRect();
      return { top: r.top, pos: getComputedStyle(h).position, scrollY: window.scrollY };
    });
    if (sticky.scrollY > 0 && (sticky.pos !== "sticky" && sticky.pos !== "fixed" || Math.abs(sticky.top) > 1)) {
      console.log(`FAIL ${c.name}: nav not stuck at top while scrolled: pos=${sticky.pos} top=${sticky.top}`);
      caseFails++;
    }
    // nav-sticky evidence shot (viewport, mid-scroll)
    await page.screenshot({ path: join(OUT, `landing-${c.name}-scrolled.png`) });
    await page.evaluate(() => window.scrollTo(0, 0));

    // contrast gate
    const checked = await page.evaluate(`(() => { ${EVAL_SRC}; return window.__check(${JSON.stringify(CONTRAST_SELECTS)}); })()`);
    const bad = checked.filter((r) => !r.pass);
    if (bad.length) {
      console.log(`FAIL ${c.name} contrast: ${bad.map((b) => `${b.sel} ${b.ratio}<${b.need}`).join(", ")}`);
      caseFails++;
    }

    // screenshot (full page), after a settle pass
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(250);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: join(OUT, `landing-${c.name}.png`), fullPage: true });

    const status = caseFails === 0 ? "OK" : "FAIL";
    console.log(`${status} ${c.name}: theme=${applied} requests=${requests.length} external=${external.length} contrast=${checked.filter((r) => r.pass).length}/${checked.length} consoleErrors=${consoleErrors.length}`);
    fail += caseFails;
    await ctx.close();
  }
} finally {
  await browser.close();
}
writeFileSync(join(OUT, "summary.json"), JSON.stringify({ ok: fail === 0 }, null, 2));
if (fail) { console.log(`LANDING VERIFY FAILED (${fail} problems)`); process.exit(1); }
console.log("LANDING VERIFY PASSED (screenshots in artifacts/landing)");
