#!/usr/bin/env node
// Computed-style snapshot for the storefront: dumps the resolved styles of a
// battery of selectors on the real pages so a stylesheet refactor can be
// diffed (before vs after) instead of eyeballed.
//
//   node scripts/css-snapshot.mjs artifacts/store-polish/css-before.json
//   node scripts/css-snapshot.mjs artifacts/store-polish/css-after.json --diff artifacts/store-polish/css-before.json
//
// STORE_URL defaults to the local kind store.

import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
// playwright-core lives in the dashboard devDependencies; in a fresh worktree
// node_modules is absent, so fall back to the main checkout (read-only).
let chromium = null;
for (const p of ["../src/dashboard/node_modules/playwright-core",
                 "/Users/manavsharma/Desktop/Urumi_AI/src/dashboard/node_modules/playwright-core"]) {
  try { ({ chromium } = require(p)); break; } catch {}
}
if (!chromium) {
  console.error("playwright-core not found (dashboard node_modules missing in both paths)");
  process.exit(2);
}
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const STORE = process.env.STORE_URL || "http://store.127.0.0.1.nip.io";
const PROPS = [
  "font-family", "font-size", "font-weight", "letter-spacing", "text-transform",
  "color", "background-color", "border-radius", "box-shadow", "padding", "margin",
  "min-height", "text-decoration", "text-align", "line-height", "border-top-width",
  "border-bottom-width", "border-left-width", "border-right-width", "background-image",
];

const PAGES = [
  ["home", "/"],
  ["shop", "/shop/"],
  ["category", "/product-category/ceramics/"],
  ["product", "/product/gel-pen-set/"],
  ["cart", "/cart/"],
  ["checkout", "/checkout/"],
  ["404", "/this-page-does-not-exist/"],
];

const SELECTORS = [
  "body", "h1", "h2", "h3", "a", "label",
  ".urumi-site-header", ".urumi-nav", ".urumi-nav__logo", ".urumi-nav__links > a",
  ".urumi-nav__dropdown summary", ".urumi-nav__dropdown-menu", ".urumi-nav__dropdown-menu a",
  ".urumi-nav__search input", ".urumi-nav__icon",
  ".wc-block-mini-cart__button", ".wc-block-mini-cart__badge",
  ".urumi-menu-button", ".urumi-menu-overlay", ".urumi-menu-overlay a",
  ".urumi-hero", ".urumi-hero__title", ".urumi-hero__sub", ".urumi-btn--invert",
  ".urumi-intro__text", ".urumi-btn-text",
  ".urumi-cat-grid", ".urumi-cat-tile", ".urumi-cat-tile__media", ".urumi-cat-tile__label",
  ".urumi-strip", ".urumi-strip__title", ".urumi-strip__note",
  ".urumi-grid", ".urumi-tile", ".urumi-tile__media", ".urumi-tile__name",
  ".urumi-tile__price", ".urumi-tile__add .button", ".urumi-flags", ".urumi-flag--sale",
  ".urumi-editorial", ".urumi-editorial__heading", ".urumi-editorial__body",
  ".urumi-footer", ".urumi-footer__col a", ".urumi-footer__title", ".urumi-footer__demo",
  ".urumi-archive-head h1", ".urumi-filter-pills .urumi-pill", ".urumi-sort-row",
  ".urumi-sort-row select", ".woocommerce-result-count",
  ".urumi-collection", ".urumi-tile-media", ".urumi-tile-name", ".urumi-tile-desc", ".urumi-tile-price",
  ".woocommerce-breadcrumb", ".urumi-pdp__title", ".urumi-pdp__price", ".urumi-stock",
  ".quantity .qty", ".urumi-accordion summary", ".urumi-accordion__body",
  ".urumi-404", ".urumi-404 h1", ".urumi-404__search input",
  ".cart_totals", ".wc-block-cart__totals", ".wc-block-cart__submit-button",
  "input[type=text]", "input[type=search]", "select",
  ".wc-block-components-button", ".urumi-btn", ".wp-block-button__link",
  ".woocommerce-message", ".urumi-related", ".urumi-details",
];

async function main() {
  const outIdx = process.argv.indexOf("--diff");
  const diffPath = outIdx >= 0 ? process.argv[outIdx + 1] : null;
  const outPath = process.argv[2] || "artifacts/store-polish/css-snapshot.json";
  mkdirSync(path.dirname(outPath), { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const snap = {};
  try {
    for (const [name, url] of PAGES) {
      const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      const page = await ctx.newPage();
      await page.goto(`${STORE}${url}`, { waitUntil: "domcontentloaded", timeout: 45000 }).catch(() => null);
      await page.waitForTimeout(1500);
      snap[name] = await page.evaluate(
        ({ selectors, props }) => {
          const out = {};
          for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (!el) continue;
            const cs = getComputedStyle(el);
            const row = {};
            for (const p of props) row[p] = cs.getPropertyValue(p);
            out[sel] = row;
          }
          return out;
        },
        { selectors: SELECTORS, props: PROPS }
      );
      await ctx.close();
    }
  } finally {
    await browser.close();
  }

  if (diffPath) {
    const before = JSON.parse(readFileSync(diffPath, "utf8"));
    const diffs = [];
    for (const page of Object.keys(before)) {
      for (const sel of Object.keys(before[page])) {
        const a = before[page][sel];
        const b = snap[page]?.[sel];
        if (!b) {
          diffs.push(`${page} ${sel}: selector missing after`);
          continue;
        }
        for (const p of Object.keys(a)) {
          if (a[p] !== b[p]) {
            diffs.push(`${page} ${sel} ${p}: "${a[p]}" -> "${b[p]}"`);
          }
        }
      }
    }
    console.log(diffs.length ? `COMPUTED-STYLE DIFFS (${diffs.length}):` : "COMPUTED-STYLE DIFF: none");
    for (const d of diffs.slice(0, 80)) console.log("  " + d);
    process.exit(diffs.length ? 1 : 0);
  } else {
    writeFileSync(outPath, JSON.stringify(snap, null, 1));
    const count = Object.values(snap).reduce((n, p) => n + Object.keys(p).length, 0);
    console.log(`wrote ${outPath} (${count} selector snapshots across ${Object.keys(snap).length} pages)`);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
