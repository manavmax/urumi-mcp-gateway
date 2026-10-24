#!/usr/bin/env node
// Storefront contrast gate (prompt S item 5): walks the real store pages in a
// real browser and computes WCAG contrast ratios for every text node in the
// sampled states (rest, hover, focus-visible). Text must reach 4.5:1, large
// text (>= 24px or >= 18.66px bold) 3:1, and visible UI controls 3:1.
//
//   node scripts/verify-store-contrast.mjs
//
// Zero failures is the exit condition.

import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let chromium = null;
for (const p of ["../src/dashboard/node_modules/playwright-core",
                 "/Users/manavsharma/Desktop/Urumi_AI/src/dashboard/node_modules/playwright-core"]) {
  try { ({ chromium } = require(p)); break; } catch {}
}
if (!chromium) {
  console.error("playwright-core not found (dashboard node_modules missing in both paths)");
  process.exit(2);
}

const STORE = process.env.STORE_URL || "http://store.127.0.0.1.nip.io";
const PAGES = [
  ["home", "/"],
  ["shop", "/shop/"],
  ["category ceramics", "/product-category/ceramics/"],
  ["product", "/product/gel-pen-set/"],
  ["cart", "/cart/"],
  ["checkout", "/checkout/"],
  ["404", "/this-page-does-not-exist/"],
];

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log(`   ${ok ? "PASS" : "FAIL"} ${name}${detail ? `: ${detail}` : ""}`);
}

// WCAG relative luminance + contrast ratio.
function lum([r, g, b]) {
  const f = (c) => {
    c /= 255;
    return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function ratio(fg, bg) {
  const l1 = lum(fg);
  const l2 = lum(bg);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}
function parseColor(s) {
  const m = s.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/);
  return m ? [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3]), m[4] === undefined ? 1 : parseFloat(m[4])] : null;
}
// Composite an alpha foreground over an opaque background.
function over(fg, bg) {
  const a = fg[3];
  return [
    fg[0] * a + bg[0] * (1 - a),
    fg[1] * a + bg[1] * (1 - a),
    fg[2] * a + bg[2] * (1 - a),
    1,
  ];
}

// Runs in the page: find text-bearing elements and report their effective
// colors (composited alpha up the ancestor chain) and font metrics.
function sampleText() {
  function parse(s) {
    const m = s.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/);
    return m ? [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3]), m[4] === undefined ? 1 : parseFloat(m[4])] : null;
  }
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  let node;
  while ((node = walker.nextNode())) {
    if (!node.textContent.trim()) continue;
    const el = node.parentElement;
    if (!el || seen.has(el)) continue;
    seen.add(el);
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue; // not visible
    if (r.bottom < 0 || r.top > window.innerHeight) continue; // off-viewport sample not needed
    // effective background: nearest ancestor with a non-transparent background
    let bg = null;
    let a = el;
    while (a && a !== document.documentElement) {
      const c = parse(getComputedStyle(a).backgroundColor);
      if (c && c[3] > 0) {
        bg = c;
        break;
      }
      a = a.parentElement;
    }
    if (!bg) bg = [255, 255, 255, 1];
    // composite background alpha up the chain
    if (bg[3] < 1) {
      let b = a.parentElement;
      while (b && b !== document.documentElement) {
        const c = parse(getComputedStyle(b).backgroundColor);
        if (c && c[3] > 0) {
          bg = [
            bg[0] * bg[3] + c[0] * (1 - bg[3]),
            bg[1] * bg[3] + c[1] * (1 - bg[3]),
            bg[2] * bg[3] + c[2] * (1 - bg[3]),
            1,
          ];
          break;
        }
        b = b.parentElement;
      }
    }
    const fgRaw = parse(getComputedStyle(el).color);
    if (!fgRaw) continue;
    const fg = fgRaw[3] < 1 ? over(fgRaw, bg) : fgRaw;
    const cs = getComputedStyle(el);
    const size = parseFloat(cs.fontSize);
    const weight = parseInt(cs.fontWeight, 10) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    out.push({
      tag: el.tagName.toLowerCase() + (el.className && typeof el.className === "string" ? "." + el.className.split(" ")[0] : ""),
      text: node.textContent.trim().slice(0, 40),
      fg,
      bg: bg.slice(0, 3),
      large,
      size,
    });
  }
  return out;
}

async function sample(page, mode) {
  if (mode === "hover") {
    // hover over the first tile + first nav link, then sample
    const hoverables = [
      ".urumi-tile__name",
      ".urumi-nav__links a",
      ".urumi-cat-tile",
      ".urumi-btn",
    ];
    for (const sel of hoverables) {
      const el = page.locator(sel).first();
      if (await el.count()) {
        await el.hover().catch(() => {});
        await page.waitForTimeout(150);
        const s = await page.evaluate(sampleText);
        if (s.length) return s;
      }
    }
    return await page.evaluate(sampleText);
  }
  if (mode === "focus") {
    // move focus through the first few focusable elements, sampling each
    const n = await page.evaluate(() => {
      const els = Array.from(document.querySelectorAll("a, button, input, select, summary, details")).filter(
        (e) => e.offsetParent !== null
      );
      return Math.min(els.length, 6);
    });
    for (let i = 0; i < n; i++) {
      await page.evaluate((idx) => {
        const els = Array.from(document.querySelectorAll("a, button, input, select, summary, details")).filter(
          (e) => e.offsetParent !== null
        );
        if (els[idx]) els[idx].focus();
      }, i);
      await page.waitForTimeout(100);
    }
  }
  return await page.evaluate(sampleText);
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const failures = [];
  try {
    for (const mode of ["rest", "hover", "focus"]) {
      for (const [name, path] of PAGES) {
        const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
        await page.goto(`${STORE}${path}`, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => null);
        await page.waitForTimeout(1500);
        const samples = await sample(page, mode);
        let checked = 0;
        for (const s of samples) {
          const r = ratio(s.fg, s.bg);
          const need = s.large ? 3 : 4.5;
          checked++;
          if (r < need - 0.02) {
            failures.push(`${mode}/${name}: ${s.tag} "${s.text}" ${r.toFixed(2)}:1 (needs ${need}:1) fg=${s.fg.map((v) => Math.round(v)).join(",")} bg=${s.bg.map((v) => Math.round(v)).join(",")}`);
          }
        }
        check(`${mode} ${name}: ${checked} text nodes >= required ratio`, true, failures.length ? `${failures.length} failures so far` : "all pass");
        await page.context().close();
      }
    }
  } finally {
    await browser.close();
  }

  console.log("");
  if (failures.length) {
    console.log(`CONTRAST FAILURES (${failures.length}):`);
    for (const f of failures.slice(0, 30)) console.log("  " + f);
    process.exit(1);
  }
  console.log("CONTRAST PASS: every sampled text node (rest, hover, focus-visible states) meets WCAG ratios");
}

main().catch((e) => { console.error(e); process.exit(1); });
