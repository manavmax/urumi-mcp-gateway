#!/usr/bin/env node
// Graphics gate for the landing page band figures (this branch's brief).
// Serves nothing itself: point LANDING_URL at a running preview, e.g.
//   python3 -m http.server 8090 --directory src/landing
//   LANDING_URL=http://127.0.0.1:8090 node scripts/landing-graphics.mjs
//
// Per graphic, at 1440 and 390, dark AND light, it measures (never eyeballs):
//   1. rendered width as % of its section's content width
//      (fail under 50% desktop / 100% mobile, 0.5px tolerance)
//   2. smallest rendered text size
//      (SVG text is scaled by renderedWidth/viewBoxWidth; fail under 13px
//      desktop / 12px mobile)
//   3. text contrast >= 4.5:1 against the effective opaque background
//   4. meaningful stroke/shape contrast >= 3:1: SVG strokes on path, line,
//      circle, polyline and polygon shapes; HTML borders >= 1.5px; and any
//      element carrying data-ink (status dots etc). Rect strokes are read as
//      panel containers whose text carries the meaning, so they are exempt.
//      Elements inside [data-decor] are decorative washes and are exempt.
//   5. no horizontal overflow at 390/1440, no console errors, zero external
//      requests, every link resolves (anchors exist, repo paths exist on main)
//   6. no em/en dashes in any visible text (page text + document.title)
// It also writes full-page, per-section and per-graphic screenshots for both
// sizes and themes into artifacts/landing/, and a JSON report.
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { execSync } from "node:child_process";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
const __dirname = dirname(fileURLToPath(import.meta.url));
const URL_BASE = process.env.LANDING_URL || "http://127.0.0.1:8090";
const OUT = join(__dirname, "..", "artifacts", "landing");
for (const d of ["", "sections", "figs", "qa"]) mkdirSync(join(OUT, d), { recursive: true });

// The graphics under test. section = the section whose content width rules
// the size gate. Each id must be visible at the checkpoint it is listed for.
const FIGS = [
  { id: "heroVisual", section: "top", label: "hero flow graphic" },
  { id: "figLifecycle", section: "features", label: "lifecycle: servers, gateway, tools" },
  { id: "tourWide", section: "tour", label: "tour diagram (wide)" },
  { id: "tourTall", section: "tour", label: "tour diagram (compact)" },
  { id: "figAudit", section: "control", label: "audit row anatomy" },
  { id: "figZones", section: "kubernetes", label: "public/private/state zones" },
];

// In-page evaluator. Returns per-graphic measurements; every failure carries
// a reason string so the runner can fail loudly.
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
function blend(fg, alpha, bg) {
  return [fg[0]*alpha + bg[0]*(1-alpha), fg[1]*alpha + bg[1]*(1-alpha), fg[2]*alpha + bg[2]*(1-alpha), 1];
}
function lum(c) {
  const f = (v) => { const s = v/255; return s <= 0.03928 ? s/12.92 : Math.pow((s+0.055)/1.055, 2.4); };
  return 0.2126*f(c[0]) + 0.7152*f(c[1]) + 0.0722*f(c[2]);
}
function ratio(a, b) {
  const x = lum(a), y = lum(b);
  return (Math.max(x,y)+0.05)/(Math.min(x,y)+0.05);
}
function effBg(el) {
  for (let n = el; n; n = n.parentElement) {
    const c = parse(getComputedStyle(n).backgroundColor);
    if (c && c[3] === 1) return c;
  }
  return [4, 8, 4, 1];
}
function decor(n) {
  for (let e = n; e; e = e.parentElement) if (e.hasAttribute && e.hasAttribute("data-decor")) return true;
  return false;
}
function inSvg(el) {
  const svg = el.closest && el.closest("svg");
  if (!svg || !svg.viewBox || !svg.viewBox.baseVal || !svg.viewBox.baseVal.width) return 1;
  return svg.getBoundingClientRect().width / svg.viewBox.baseVal.width;
}
window.__measure = (rootId) => {
  const root = document.getElementById(rootId);
  if (!root) return { missing: true };
  const problems = [];
  const textStats = [];
  const section = root.closest("section") || document.body;
  const secCS = getComputedStyle(section);
  const contentW = section.getBoundingClientRect().width
    - parseFloat(secCS.paddingLeft) - parseFloat(secCS.paddingRight);
  const rootW = root.getBoundingClientRect().width;
  const widthPct = contentW > 0 ? (100 * rootW / contentW) : 0;

  const walker = (el) => {
    // hidden subtrees (e.g. the other hero variant, hidden diagrams) render
    // nothing and cannot be measured; skip them wholesale
    if (getComputedStyle(el).display === "none") return;
    for (const child of el.children) walker(child);
    if (decor(el)) return;
    // text nodes owned by this element
    const ownText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (ownText) {
      const cs = getComputedStyle(el);
      const isSvg = el instanceof SVGElement;
      const raw = parse(isSvg ? cs.fill : cs.color);
      if (raw) {
        const bg = effBg(el);
        const fg = raw[3] < 1 ? blend(raw, raw[3], bg) : raw;
        const r = ratio(fg, bg);
        const size = parseFloat(cs.fontSize) * (isSvg ? inSvg(el) : 1);
        textStats.push({ size, r });
        const snippet = el.textContent.trim().slice(0, 26);
        if (size < window.__minPx - 0.01)
          problems.push("text too small: " + size.toFixed(2) + "px < " + window.__minPx + "px: '" + snippet + "'");
        if (r < 4.5)
          problems.push("text contrast " + r.toFixed(2) + " < 4.5: '" + snippet + "'");
      }
    }
    // meaningful SVG strokes on shape primitives
    if (el instanceof SVGElement && decor(el) === false) {
      const tag = el.tagName.toLowerCase();
      const stroke = parse(getComputedStyle(el).stroke);
      if (["path","line","circle","polyline","polygon"].includes(tag) && stroke && stroke[3] > 0.02) {
        const bg = effBg(el);
        const sc = stroke[3] < 1 ? blend(stroke, stroke[3], bg) : stroke;
        const r = ratio(sc, bg);
        if (r < 3) problems.push("svg stroke contrast " + r.toFixed(2) + " < 3 on <" + tag + ">");
      }
      if (el.hasAttribute("data-ink")) {
        const bgc = parse(getComputedStyle(el).backgroundColor);
        const fill = parse(getComputedStyle(el).fill);
        const bg = effBg(el);
        // HTML ink shapes colour their background; SVG ink shapes their fill
        const col = (bgc && bgc[3] > 0.02) ? bgc : fill;
        if (col) {
          const cc = col[3] < 1 ? blend(col, col[3], bg) : col;
          const r = ratio(cc, bg);
          if (r < 3) problems.push("data-ink shape contrast " + r.toFixed(2) + " < 3");
        }
      }
    }
    // meaningful HTML borders (>= 1.5px)
    if (!(el instanceof SVGElement)) {
      const cs = getComputedStyle(el);
      for (const side of ["Top","Right","Bottom","Left"]) {
        const w = parseFloat(cs["border" + side + "Width"]);
        const style = cs["border" + side + "Style"];
        const col = parse(cs["border" + side + "Color"]);
        if (style !== "none" && col && col[3] > 0.02 && w >= 1.5) {
          const bg = effBg(el);
          const cc = col[3] < 1 ? blend(col, col[3], bg) : col;
          const r = ratio(cc, bg);
          if (r < 3) problems.push("border contrast " + r.toFixed(2) + " < 3 on " + (el.className || el.tagName));
        }
      }
    }
  };
  walker(root);
  return {
    missing: false,
    widthPct: Math.round(widthPct * 10) / 10,
    minText: textStats.length ? Math.min(...textStats.map(t => t.size)) : null,
    minTextRatio: textStats.length ? Math.min(...textStats.map(t => t.r)) : null,
    textCount: textStats.length,
    problems,
  };
};
window.__collectText = () => {
  const bad = [];
  const scan = (root) => {
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      const t = n.textContent;
      if (/[\\u2014\\u2013]/.test(t)) bad.push(t.trim().slice(0, 40));
    }
  };
  scan(document.body);
  const out = [...bad];
  if (/[\\u2014\\u2013]/.test(document.title)) out.push("title: " + document.title);
  return out;
};
`;

const WIDTHS = [
  { name: "1440", width: 1440, height: 900, minPx: 13, minPct: 50 },
  { name: "390", width: 390, height: 844, minPx: 12, minPct: 100 },
];
const THEMES = ["dark", "light"];

let fails = 0;
const fail = (msg) => { console.log("FAIL " + msg); fails++; };
const ok = (msg) => console.log("OK   " + msg);

const browser = await chromium.launch();
const report = { url: URL_BASE, cases: [], sizes: null };

// repo tree for data-repo-path link checks
const repoTree = new Set(
  execSync("git ls-tree -r main --name-only", { cwd: join(__dirname, ".."), encoding: "utf8" })
    .split("\n").filter(Boolean)
);
const REPO = "https://github.com/manavmax/urumi-mcp-gateway";

for (const theme of THEMES) {
  for (const c of WIDTHS) {
    const ctx = await browser.newContext({ viewport: { width: c.width, height: c.height }, colorScheme: theme });
    await ctx.addInitScript((t) => { try { localStorage.setItem("landing-theme", t); } catch (e) {} }, theme);
    const page = await ctx.newPage();
    const requests = [];
    const consoleErrors = [];
    page.on("request", (r) => requests.push(r.url()));
    page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
    page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));
    await page.goto(URL_BASE, { waitUntil: "networkidle" });
    await page.evaluate(() => document.fonts.ready);
    // reveal everything (instant jumps: html has smooth scroll-behavior)
    await page.evaluate(async () => {
      const step = window.innerHeight * 0.8;
      for (let y = 0; y <= document.body.scrollHeight; y += step) {
        window.scrollTo({ top: y, behavior: "instant" });
        await new Promise(r => setTimeout(r, 60));
      }
      window.scrollTo({ top: 0, behavior: "instant" });
    });
    await page.waitForTimeout(800);

    const caseName = `${c.name}-${theme}`;
    const caseReport = { case: caseName, figs: {}, checks: {} };

    // 1-4: per-graphic gates
    await page.evaluate(`(() => { ${EVAL_SRC}; window.__minPx = ${c.minPx}; })()`);
    for (const fig of FIGS) {
      const visible = await page.evaluate((id) => {
        const el = document.getElementById(id);
        return !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
      }, fig.id);
      if (!visible) { caseReport.figs[fig.id] = { skipped: "not visible at this width" }; continue; }
      const m = await page.evaluate(`window.__measure(${JSON.stringify(fig.id)})`);
      if (m.missing) { fail(`${caseName} ${fig.id}: element missing`); continue; }
      caseReport.figs[fig.id] = m;
      if (m.widthPct < c.minPct - 0.5)
        fail(`${caseName} ${fig.id}: width ${m.widthPct}% < ${c.minPct}% of section content`);
      if (m.minText === null)
        fail(`${caseName} ${fig.id}: no measurable text`);
      if (m.problems.length) m.problems.forEach((p) => fail(`${caseName} ${fig.id}: ${p}`));
    }
    const measured = Object.values(caseReport.figs).filter(f => f.widthPct !== undefined);
    const sizes = measured.filter(f => f.minText != null).map(f => f.minText);
    if (measured.length && !measured.some(f => f.problems?.length) && sizes.length)
      ok(`${caseName}: ${measured.length} graphics measured, minText ${Math.min(...sizes).toFixed(1)}px, widths ${measured.map(f => f.widthPct + "%").join(", ")}`);

    // 5a: horizontal overflow
    const overflow = await page.evaluate(() => {
      const vw = document.documentElement.clientWidth;
      const sw = document.documentElement.scrollWidth;
      return { vw, sw, bad: sw > vw + 1 };
    });
    if (overflow.bad) fail(`${caseName}: horizontal overflow scrollWidth ${overflow.sw} > ${overflow.vw}`);
    caseReport.checks.overflow = overflow.bad ? "FAIL" : "ok";

    // 5b: console errors
    if (consoleErrors.length) fail(`${caseName}: console errors: ${consoleErrors.slice(0, 4).join(" | ")}`);
    caseReport.checks.consoleErrors = consoleErrors.length;

    // 5c: external requests
    const external = requests.filter((u) => !u.startsWith(URL_BASE));
    if (external.length) fail(`${caseName}: external requests: ${external.join(", ")}`);

    // 5d: links resolve
    const linkState = await page.evaluate((repo) => {
      const out = { anchors: [], empties: [], nonRepo: [] };
      document.querySelectorAll("a[href]").forEach((a) => {
        const href = a.getAttribute("href");
        if (!href || !href.trim()) { out.empties.push(a.textContent.trim().slice(0, 24)); return; }
        if (href.startsWith("#")) {
          const id = href.slice(1);
          if (id && !document.getElementById(id)) out.anchors.push(href);
        } else if (href.includes("github.com") && !href.startsWith(repo)) {
          out.nonRepo.push(href);
        }
      });
      return out;
    }, REPO);
    if (linkState.anchors.length) fail(`${caseName}: anchors without targets: ${linkState.anchors.join(", ")}`);
    if (linkState.empties.length) fail(`${caseName}: empty hrefs: ${linkState.empties.join(", ")}`);
    if (linkState.nonRepo.length) fail(`${caseName}: non-repo external links: ${linkState.nonRepo.join(", ")}`);
    // repo blob paths exist on main
    const blobPaths = await page.evaluate(() => {
      const hrefs = [...document.querySelectorAll("a[href]")].map(a => a.getAttribute("href"));
      return [...new Set(hrefs)]
        .filter(h => h && h.includes("/blob/main/"))
        .map(h => h.split("/blob/main/")[1]);
    });
    const missingPaths = blobPaths.filter((p) => !repoTree.has(p));
    if (missingPaths.length) fail(`${caseName}: blob/main paths not on main: ${missingPaths.join(", ")}`);
    caseReport.checks.links = { anchors: linkState.anchors.length, empties: linkState.empties.length, blobPaths: blobPaths.length, missingPaths: missingPaths.length };

    // 6: dashes in visible text
    const dashes = await page.evaluate(`(() => { ${EVAL_SRC}; return window.__collectText(); })()`);
    if (dashes.length) fail(`${caseName}: em/en dash in visible text: ${JSON.stringify(dashes.slice(0, 4))}`);
    caseReport.checks.dashes = dashes.length;

    // screenshots: full page, per section, per graphic
    await page.screenshot({ path: join(OUT, `landing-${c.name}-${theme}-full.png`), fullPage: true });
    const secDir = join(OUT, "sections", caseName);
    mkdirSync(secDir, { recursive: true });
    const secs = await page.evaluate(() => {
      const els = [...document.querySelectorAll("main > section, main > .hero, footer")];
      return els.map((el, i) => ({
        i,
        id: el.id || "el" + i,
        visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
      }));
    });
    for (const s of secs) {
      if (!s.visible) continue;
      try {
        await page.locator("main > section, main > .hero, footer").nth(s.i)
          .screenshot({ path: join(secDir, `${String(s.i).padStart(2, "0")}-${s.id}.png`) });
      } catch (e) { console.log("section clip failed:", s.id); }
    }
    const figDir = join(OUT, "figs", caseName);
    mkdirSync(figDir, { recursive: true });
    for (const fig of FIGS) {
      const visible = await page.evaluate((id) => {
        const el = document.getElementById(id);
        return !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
      }, fig.id);
      if (!visible) continue;
      try {
        await page.locator("#" + fig.id).screenshot({ path: join(figDir, `${fig.id}.png`) });
      } catch (e) { console.log("fig clip failed:", fig.id); }
    }

    // bundle sizes (transfer bytes) once, on the first passing case
    if (!report.sizes) {
      const sizes = { css: 0, js: 0, images: 0, fonts: 0, html: 0, other: 0, total: 0 };
      for (const u of [...new Set(requests)]) {
        try {
          const res = await page.request.get(u);
          const n = (await res.body()).length;
          sizes.total += n;
          const path = u.split("?")[0];
          if (path.endsWith(".css")) sizes.css += n;
          else if (path.endsWith(".js")) sizes.js += n;
          else if (path.endsWith(".svg") || path.endsWith(".png") || path.endsWith(".jpg") || path.endsWith(".ico")) sizes.images += n;
          else if (path.endsWith(".woff2")) sizes.fonts += n;
          else if (path.endsWith("/") || path.endsWith(".html")) sizes.html += n;
          else sizes.other += n;
        } catch (e) {}
      }
      report.sizes = sizes;
    }

    report.cases.push(caseReport);
    await ctx.close();
  }
}

await browser.close();
writeFileSync(join(OUT, "qa", "graphics-report.json"), JSON.stringify(report, null, 1));
const s = report.sizes || {};
console.log(`sizes (transfer): total=${s.total}B css=${s.css}B js=${s.js}B images=${s.images}B fonts=${s.fonts}B html=${s.html}B`);
if (fails) { console.log(`GRAPHICS GATE FAILED (${fails} problems)`); process.exit(1); }
console.log("GRAPHICS GATE PASSED");
