#!/usr/bin/env node
// REAL storefront verification (prompt S item 5): drives the actual storefront in a
// real browser (playwright-core from the dashboard devDependencies) and checks:
//   - home, shop, one category, one product, cart, checkout, 404 and search return
//     200 and render
//   - 12 products in the shop grid, every image loaded (naturalWidth > 0), prices
//     formatted $X.XX
//   - ZERO third-party requests (every request is logged; anything off-origin fails)
//   - no console errors
//   - both self-hosted fonts actually load (document.fonts.check + computed
//     font-family on h1 and body)
//   - hero geometry at 1440 (container radius 40px, h1 font-size >= 56px)
//   - at 390: no horizontal overflow, and the mobile nav overlay opens and closes
//   - add to cart updates the mini-cart count; category + sort links work
//   - saves 12 screenshots into artifacts/store/ (6 pages x 1440 + 390)
//
//   node scripts/verify-store.mjs
//
// The storefront pages need no credentials; output is URLs, statuses, check results.

import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
import { mkdirSync } from "node:fs";
import path from "node:path";

const STORE = process.env.STORE_URL || "http://store.127.0.0.1.nip.io";
const ART = process.env.ARTIFACTS_DIR || "artifacts/store";
const STORE_ORIGIN = new URL(STORE).origin;

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log(`   ${ok ? "PASS" : "FAIL"} ${name}${detail ? `: ${detail}` : ""}`);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const SHOTS = [
  ["home", "/"],
  ["shop", "/shop/"],
  ["category-apparel", "/product-category/apparel/"],
  ["product", "/product/urumi-classic-tee/"],
  ["cart", "/cart/"],
  ["checkout", "/checkout/"],
];
const PAGES = [
  ["home", "/"],
  ["shop", "/shop/"],
  ["category apparel", "/product-category/apparel/"],
  ["product tee", "/product/urumi-classic-tee/"],
  ["cart", "/cart/"],
  ["checkout", "/checkout/"],
  ["search", "/?s=tee"],
];

function attachWatchers(page, thirdParty, consoleErrors) {
  page.on("request", (r) => {
    try { if (new URL(r.url()).origin !== STORE_ORIGIN) thirdParty.push(r.url()); } catch {}
  });
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
}

async function miniCartCount(page) {
  const btn = page.locator(".wc-block-mini-cart__button").first();
  if (!(await btn.count())) return -1;
  const label = (await btn.getAttribute("aria-label")) || (await btn.innerText()) || "";
  const m = label.match(/(\d+)/);
  return m ? parseInt(m[1], 10) : 0;
}

async function firstTileName(page) {
  const el = page.locator(".urumi-collection .urumi-tile-name, .wc-block-components-product-title").first();
  if (!(await el.count())) return "";
  return (await el.innerText()).trim();
}

async function gotoPage(page, url, settle = 2000) {
  await page.goto(`${STORE}${url}`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await sleep(settle);
}

async function main() {
  mkdirSync(ART, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const thirdParty = [];
  const consoleErrors = [];

  try {
    // ============================ desktop pass (1440) ============================
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    attachWatchers(page, thirdParty, consoleErrors);

    // 1. every page returns 200 and renders a main element (404 is checked separately)
    for (const [name, url] of PAGES) {
      const res = await page.goto(`${STORE}${url}`, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => null);
      await sleep(1200);
      const status = res ? res.status() : 0;
      const hasMain = (await page.locator("main").count()) > 0;
      check(`${name} returns 200 and renders`, status === 200 && hasMain, `status=${status} main=${hasMain}`);
    }

    // 404 page: right status + copy. Chromium logs a console error for the 404
    // document load itself, so reset the console errors after this check.
    const r404 = await page.goto(`${STORE}/this-page-does-not-exist/`, { waitUntil: "domcontentloaded" });
    await sleep(800);
    const notFoundText = (await page.locator("text=Page not found").count()) > 0;
    check("404 returns 404 with Page not found", r404.status() === 404 && notFoundText, `status=${r404.status()}`);
    consoleErrors.length = 0;

    // 2. hero geometry at 1440
    await gotoPage(page, "/", 1500);
    const heroRadius = await page.locator(".urumi-hero").first().evaluate((el) => getComputedStyle(el).borderRadius).catch(() => "");
    check("hero container radius 40px at 1440", String(heroRadius).startsWith("40"), `radius=${heroRadius}`);
    const h1Size = await page.locator("main h1").first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize)).catch(() => 0);
    check("hero h1 >= 56px at 1440", h1Size >= 56, `font-size=${h1Size}px`);

    // 3. fonts actually loaded + applied
    const fonts = await page.evaluate(async () => {
      await document.fonts.ready;
      const h1 = document.querySelector("h1");
      return {
        serif: document.fonts.check('16px "Instrument Serif"'),
        inter: document.fonts.check("16px Inter"),
        h1ff: h1 ? getComputedStyle(h1).fontFamily : "",
        bodyff: getComputedStyle(document.body).fontFamily,
      };
    }).catch(() => null);
    check("Instrument Serif loaded", !!fonts?.serif, String(fonts?.serif));
    check("Inter loaded", !!fonts?.inter, String(fonts?.inter));
    check("h1 computed font is Instrument Serif", /instrument serif/i.test(fonts?.h1ff || ""), fonts?.h1ff || "");
    check("body computed font is Inter", /\binter\b/i.test(fonts?.bodyff || ""), fonts?.bodyff || "");

    // 4. category tiles
    const catTiles = await page.locator(".urumi-cat-tile").count();
    check("4 category tiles on home", catTiles === 4, `count=${catTiles}`);

    // 5. shop grid: 12 products, images loaded, prices formatted
    await gotoPage(page, "/shop/", 2500);
    const tileCount = await page.locator(".urumi-collection li, .urumi-grid li").count();
    check("shop grid shows 12 products", tileCount === 12, `tiles=${tileCount}`);
    const badImages = await page.evaluate(() =>
      Array.from(document.querySelectorAll("img")).filter((i) => i.src && i.naturalWidth === 0).map((i) => i.src)
    ).catch(() => ["(evaluate failed)"]);
    check("every image on shop loaded (naturalWidth > 0)", badImages.length === 0, badImages.slice(0, 3).join(", "));
    const priceNodes = await page.locator(".urumi-tile-price, .wc-block-components-product-price").allInnerTexts();
    const nonEmpty = priceNodes.filter((t) => t.trim());
    check("prices formatted $X.XX", nonEmpty.length > 0 && nonEmpty.every((t) => /\$\d+\.\d{2}/.test(t)), `${nonEmpty.length} price nodes`);

    // 6. category link + sort control
    await page.locator('.urumi-filter-pills a[href*="product-category/apparel"]').first().click();
    await sleep(1800);
    check("category link navigates to Apparel", page.url().includes("/product-category/apparel/"), page.url());

    // sort on the shop page (12 products): the cheapest (Pen Set, $12.00) is not
    // the default-first tile, so price-low-to-high must change the order
    await page.goto(`${STORE}/shop/`, { waitUntil: "domcontentloaded" });
    await sleep(2000);
    const sortSelect = page.locator("select").first();
    const hasSort = (await sortSelect.count()) > 0;
    check("sort control present", hasSort, "");
    if (hasSort) {
      const beforeName = await firstTileName(page);
      const lowHigh = await sortSelect.locator("option").allTextContents()
        .then((opts) => opts.findIndex((o) => /low to high/i.test(o)));
      await sortSelect.selectOption({ index: lowHigh }).catch(() => {});
      await sleep(2500);
      const afterName = await firstTileName(page);
      check("sort control changes the grid order", beforeName !== afterName, `first tile "${beforeName}" -> "${afterName}"`);
    }

    // 7. add to cart updates the mini-cart count
    await page.goto(`${STORE}/product/urumi-classic-tee/`, { waitUntil: "domcontentloaded" });
    await sleep(1800);
    const addBtn = page.locator(".single_add_to_cart_button, button[name=add-to-cart]").first();
    check("product page has add-to-cart button", (await addBtn.count()) > 0, "");
    const cartBefore = await miniCartCount(page);
    await addBtn.click();
    await sleep(3000);
    const cartAfter = await miniCartCount(page);
    check("add to cart updates the cart count", cartAfter > cartBefore, `before=${cartBefore} after=${cartAfter}`);

    // empty the cart again so the cart screenshot shows the honest state
    await page.goto(`${STORE}/cart/`, { waitUntil: "domcontentloaded" });
    await sleep(1500);
    const removeBtn = page.locator(".wc-block-cart-item__remove-link, a.remove_from_cart_button").first();
    if (await removeBtn.count()) {
      await removeBtn.click();
      await sleep(2500);
    }

    // 8. screenshots at 1440
    for (const [name, url] of SHOTS) {
      await gotoPage(page, url);
      await page.screenshot({ path: path.join(ART, `${name}-1440.png`) });
    }
    await ctx.close();

    // ============================ mobile pass (390) ============================
    const mctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const mpage = await mctx.newPage();
    attachWatchers(mpage, thirdParty, consoleErrors);

    for (const [name, url] of SHOTS) {
      const r = await mpage.goto(`${STORE}${url}`, { waitUntil: "domcontentloaded" }).catch(() => null);
      await sleep(1800);
      const overflow = await mpage.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth).catch(() => -1);
      const ok = !!r && r.status() === 200 && overflow <= 1;
      check(`390 ${name}: renders, no horizontal overflow`, ok, `status=${r ? r.status() : 0} overflow=${overflow}px`);
      await mpage.screenshot({ path: path.join(ART, `${name}-390.png`) });
    }

    // mobile nav overlay opens and closes
    await gotoPage(mpage, "/", 1500);
    const menuBtn = mpage.locator(".urumi-menu-button").first();
    check("mobile menu button present", (await menuBtn.count()) > 0, "");
    await menuBtn.click().catch(() => {});
    await sleep(700);
    const overlayOpen = await mpage.locator(".urumi-menu-overlay").first().evaluate((el) =>
      getComputedStyle(el).display !== "none" && getComputedStyle(el).visibility !== "hidden"
    ).catch(() => false);
    check("mobile nav overlay opens", overlayOpen === true, "");
    await menuBtn.click().catch(() => {});
    await sleep(500);
    const overlayHidden = await mpage.locator(".urumi-menu-overlay").first().evaluate((el) =>
      getComputedStyle(el).visibility === "hidden" || getComputedStyle(el).opacity === "0" || !el.offsetParent
    ).catch(() => false);
    check("mobile nav overlay closes", overlayHidden === true, "");
    await mctx.close();

    // zero third-party + console errors
    check("zero third-party requests", thirdParty.length === 0, thirdParty.slice(0, 5).join(" | ") || "none");
    check("no console errors", consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | ") || "none");

    const failed = results.filter((r) => !r.ok);
    check("summary", failed.length === 0, failed.length ? `${failed.length} FAIL` : `${results.length - 1} real checks pass`);
    if (failed.length || thirdParty.length || consoleErrors.length) {
      if (thirdParty.length) console.log(`\nthird-party requests observed:\n  ${thirdParty.slice(0, 20).join("\n  ")}`);
      if (consoleErrors.length) console.log(`\nconsole errors:\n  ${consoleErrors.slice(0, 10).join("\n  ")}`);
      process.exit(1);
    }
    console.log(`\nVERIFY STORE: all storefront checks passed (screenshots in ${ART})`);
  } finally {
    await browser.close();
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
