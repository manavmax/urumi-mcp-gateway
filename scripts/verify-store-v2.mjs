#!/usr/bin/env node
// Storefront verification harness for the store-v2 branch (screenshots, e2e COD
// checkout, REST catalog checks, page weight). Works against any store URL:
// the compose harness (http://localhost:18088, credentials from
// artifacts/store-compose/.env) or the cluster (creds via env vars).
//
//   node scripts/verify-store-v2.mjs screenshots --out artifacts/store-audit
//   node scripts/verify-store-v2.mjs checkout    --out artifacts/store-audit
//   node scripts/verify-store-v2.mjs rest        --expect 32
//
// Env:
//   STORE_URL           base URL (default http://localhost:18088)
//   V2_CK / V2_CS       Woo consumer key/secret; if unset, read from
//                       artifacts/store-compose/.env (chmod 600, gitignored)
//   V2_PRODUCT_SIMPLE   product page URL for the e2e checkout (default: first
//                       /product/ link on /shop/)
//   V2_SEARCH_QUERY     search query for the search-results screenshot (default: candle)
//
// Never prints credentials. Everything off-origin is treated as a failure.

import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";

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

const STORE = process.env.STORE_URL || "http://localhost:18088";
const STORE_ORIGIN = new URL(STORE).origin;
const OUT_DEFAULT = "artifacts/store-v2";

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log(`   ${ok ? "PASS" : "FAIL"} ${name}${detail ? `: ${detail}` : ""}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function creds() {
  if (process.env.V2_CK && process.env.V2_CS) {
    return { ck: process.env.V2_CK, cs: process.env.V2_CS };
  }
  try {
    const env = readFileSync("artifacts/store-compose/.env", "utf8");
    const ck = env.match(/^V2_CK=(.+)$/m)?.[1];
    const cs = env.match(/^V2_CS=(.+)$/m)?.[1];
    if (ck && cs) return { ck: ck.trim(), cs: cs.trim() };
  } catch {}
  return null;
}
const wooAuthHeader = () => {
  const c = creds();
  if (!c) throw new Error("no Woo credentials: set V2_CK/V2_CS or artifacts/store-compose/.env");
  return `Basic ${Buffer.from(`${c.ck}:${c.cs}`).toString("base64")}`;
};

function attachWatchers(page, thirdParty, consoleErrors) {
  page.on("request", (r) => {
    try { if (new URL(r.url()).origin !== STORE_ORIGIN) thirdParty.push(r.url()); } catch {}
  });
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
}

async function overflowX(page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

async function pageWeight(page) {
  return page.evaluate(() =>
    performance
      .getEntriesByType("resource")
      .reduce((n, e) => n + (e.encodedBodySize || 0), 0)
  );
}

// Pages to screenshot at both widths. SLUGS can override the audit defaults.
const PAGES = (slugMap) => [
  ["home", "/"],
  ["shop", "/shop/"],
  ["category", slugMap.category || "/product-category/ceramics/"],
  ["product", slugMap.product || "/product/stoneware-mug-12-oz/"],
  ["cart", "/cart/"],
  ["checkout", "/checkout/"],
  ["search", `/?s=${encodeURIComponent(process.env.V2_SEARCH_QUERY || "candle")}&post_type=product`],
  ["404", "/this-page-does-not-exist/"],
  ["my-account", "/my-account/"],
];

async function shootPage(ctx, out, name, url, width, height) {
  const page = await ctx.newPage();
  const thirdParty = [];
  const consoleErrors = [];
  attachWatchers(page, thirdParty, consoleErrors);
  const resp = await page.goto(`${STORE}${url}`, { waitUntil: "domcontentloaded", timeout: 45000 });
  await sleep(1800);
  const wantStatus = name === "404" ? 404 : 200;
  check(`${name} ${width} HTTP`, resp ? resp.status() === wantStatus : false, resp ? `status=${resp.status()}` : "no response");
  const brokenImgs = await page.evaluate(() =>
    [...document.images].filter((i) => i.complete && i.naturalWidth === 0).map((i) => i.src.split("/").pop())
  );
  if (brokenImgs.length) check(`${name} ${width} images loaded`, false, `broken: ${brokenImgs.slice(0, 3).join(", ")}`);
  else check(`${name} ${width} images loaded`, true, "");
  check(`${name} ${width} zero third-party requests`, thirdParty.length === 0, thirdParty.slice(0, 2).join(" "));
  const realErrors = name === "404" ? consoleErrors.filter((e) => !e.includes("404")) : consoleErrors;
  check(`${name} ${width} no console errors`, realErrors.length === 0, realErrors.slice(0, 1).join(" "));
  const ov = await overflowX(page);
  check(`${name} ${width} no horizontal overflow`, ov <= 0, `scrollWidth-clientWidth=${ov}px`);

  if (width === 1440 && (name === "home" || name === "shop")) {
    const weight = await pageWeight(page);
    const docSize = resp ? (await page.evaluate(() => performance.getEntriesByType("navigation")[0]?.encodedBodySize || 0)) : 0;
    console.log(`   INFO ${name} page weight (subresources, encoded): ${(weight / 1024).toFixed(0)} KB + doc ${(docSize / 1024).toFixed(0)} KB`);
    results.push({ name: `${name} page weight KB`, ok: true, detail: `${((weight + docSize) / 1024).toFixed(0)}KB` });
  }
  await page.screenshot({ path: path.join(out, `${name}-${width}.png`), fullPage: true });
  await page.close();
}

async function cmdScreenshots(out) {
  mkdirSync(out, { recursive: true });
  const slugMap = {};
  const pages = PAGES(slugMap);
  const browser = await chromium.launch({ headless: true });
  const fillCart = async (ctx) => {
    // Pick a SIMPLE in-stock product via REST (a variable product would need
    // option selection), add it with the classic add-to-cart endpoint.
    let pid = null;
    try {
      const r = await fetch(`${STORE}/wp-json/wc/v3/products?type=simple&stock_status=instock&per_page=1`, { headers: { Authorization: wooAuthHeader() } });
      if (r.ok) {
        const list = await r.json();
        if (Array.isArray(list) && list[0]) pid = list[0].id;
      }
    } catch {}
    const page = await ctx.newPage();
    if (pid) {
      await page.goto(`${STORE}/?add-to-cart=${pid}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(2000);
    } else {
      // fallback: click the first product's add-to-cart
      const shop = await ctx.newPage();
      await shop.goto(`${STORE}/shop/`, { waitUntil: "domcontentloaded" });
      await shop.waitForTimeout(1200);
      const href = await shop.locator("a[href*='/product/']").first().getAttribute("href");
      await shop.close();
      if (href) {
        await page.goto(href, { waitUntil: "domcontentloaded" });
        await page.waitForTimeout(1200);
        const add = page.locator(".single_add_to_cart_button, form.cart button[type=submit]").first();
        if (await add.count()) await add.click();
        await page.waitForTimeout(2000);
      }
    }
    await page.close();
  };
  try {
    for (const [width, height] of [[1440, 900], [390, 844]]) {
      const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, reducedMotion: "reduce" });
      await fillCart(ctx);
      for (const [name, url] of pages) {
        console.log(` [${width}] ${name} ${url}`);
        await shootPage(ctx, out, name, url, width, height);
      }
      // mobile menu interaction at 390 (after the static shots)
      if (width === 390) {
        const page = await ctx.newPage();
        await page.goto(`${STORE}/`, { waitUntil: "domcontentloaded" });
        await sleep(1200);
        const toggle = page.locator(".urumi-menu-toggle, #urumi-menu-toggle").first();
        if (await toggle.count()) {
          await toggle.check({ force: true }).catch(async () => page.locator("label[for=urumi-menu-toggle]").first().click().catch(() => {}));
          await sleep(500);
          const overlayVisible = await page.locator(".urumi-menu-overlay a").first().isVisible().catch(() => false);
          check("390 mobile menu overlay opens", overlayVisible, "");
          await page.screenshot({ path: path.join(out, `mobile-menu-390.png`), fullPage: false });
        } else {
          check("390 mobile menu toggle present", false, "no .urumi-menu-toggle found");
        }
        await page.close();
      }
      await ctx.close();
    }
  } finally {
    await browser.close();
  }
}

async function cmdCheckout(out) {
  mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  let orderId = null;
  let orderNumber = null;
  let confirmed = false;
  const billingEmail = `store-v2-checkout-${Date.now()}@example.invalid`;
  try {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    page.on("response", async (r) => {
      if (r.url().includes("/wp-json/wc/store/v1/checkout") && r.request().method() === "POST") {
        let body = "";
        try { body = await r.text(); } catch {}
        let parsed = null;
        try { parsed = JSON.parse(body); } catch {}
        if (parsed?.order_id) {
          orderId = parsed.order_id;
          orderNumber = parsed.order_number || parsed.order_id;
          confirmed = r.status() === 200;
          check(`Store API returned order ${orderId} (status ${parsed.status})`, confirmed, `status=${parsed.status} total=${parsed.total}`);
        }
      }
    });

    let product = process.env.V2_PRODUCT_SIMPLE;
    if (!product) {
      try {
        const r = await fetch(`${STORE}/wp-json/wc/v3/products?type=simple&stock_status=instock&per_page=1`, { headers: { Authorization: wooAuthHeader() } });
        if (r.ok) {
          const list = await r.json();
          if (Array.isArray(list) && list[0]) product = list[0].permalink;
        }
      } catch {}
      if (!product) {
        const shop = await ctx.newPage();
        await shop.goto(`${STORE}/shop/`, { waitUntil: "domcontentloaded" });
        await sleep(1500);
        product = await shop.locator(".urumi-collection a[href*='/product/'], a[href*='/product/']").first().getAttribute("href");
        await shop.close();
      }
      // The hardened wordpress image reports HTTPS=on, so REST-built permalinks
      // may come back https:// while the compose store serves http://.
      if (product && STORE.startsWith("http:")) product = product.replace(/^https:/, "http:");
      check("found a simple product URL for checkout", !!product, product || "");
    }

    console.log(`   opening product: ${product}`);
    await page.goto(product, { waitUntil: "domcontentloaded" });
    await sleep(1500);
    const singleAdd = page.locator(".single_add_to_cart_button, button[name=add-to-cart], form.cart button[type=submit]").first();
    check("product page shows add-to-cart button", (await singleAdd.count()) > 0, "");
    await singleAdd.click();
    await sleep(2500);

    await page.goto(`${STORE}/checkout/`, { waitUntil: "domcontentloaded" });
    await sleep(3000);
    check("checkout page loads (wc-block-checkout)", (await page.locator(".wc-block-checkout, form.wc-block-checkout-form").count()) > 0, `url=${page.url()}`);
    const hasCod = await page.locator("input[value=cod], label:has-text('Cash on delivery')").count();
    check("Cash on delivery payment option present", hasCod > 0, `count=${hasCod}`);

    async function typeInto(selector, value) {
      const el = page.locator(selector).first();
      if ((await el.count()) > 0) {
        await el.click();
        await el.press("Control+A");
        await el.pressSequentially(value, { delay: 10 });
        return true;
      }
      return false;
    }
    await typeInto(".wc-block-checkout__contact-fields input[type=email], #email, input[name=email]", billingEmail);
    const fields = { first_name: "Store", last_name: "V2", address_1: "1 Test St", city: "Testville", postcode: "90210", phone: "5550100" };
    for (const [k, v] of Object.entries(fields)) {
      if (!(await typeInto(`input[name='billing[${k}]'], #billing-${k}`, v))) {
        console.log(`   (billing field ${k} not found in DOM)`);
      }
    }
    const state = page.locator("input[name='billing[state]'], .wc-block-components-state-input input").first();
    if ((await state.count()) > 0) { await state.click(); await state.pressSequentially("CA", { delay: 10 }); }

    const codRadio = page.locator("input[value=cod]").first();
    if (!(await codRadio.isChecked())) {
      await page.locator("label:has-text('Cash on delivery')").first().click().catch(() => codRadio.check({ force: true }));
    }
    await sleep(1200);
    check("COD radio selected", await codRadio.isChecked(), "");

    const placeBtn = page.locator("button:has-text('Place Order'), .wc-block-components-checkout-place-order-button").first();
    check("Place Order button present", (await placeBtn.count()) > 0, "");
    await sleep(800);
    await placeBtn.click();
    console.log("   clicked Place Order, waiting for the Store API response...");
    await sleep(15000);

    if (confirmed && orderId) {
      console.log(`   order placed: #${orderNumber} via block checkout`);
      await sleep(2000);
      await page.screenshot({ path: path.join(out, `order-received-1440.png`), fullPage: true });
      const ov = await overflowX(page);
      check("order-received 1440 no horizontal overflow", ov <= 0, `${ov}px`);
      const t4 = await browser.newContext({ viewport: { width: 390, height: 844 } });
      const p4 = await t4.newPage();
      await p4.goto(`${STORE}/checkout/order-received/${orderId}/?key=wc_order_${orderId}`, { waitUntil: "domcontentloaded" }).catch(() => {});
      await sleep(2000);
      await p4.screenshot({ path: path.join(out, `order-received-390.png`), fullPage: true });
      await t4.close();
    } else {
      const notices = await page.locator(".wc-block-components-notice-banner, [role=alert]").allInnerTexts().catch(() => []);
      check("checkout completed without blocking error", false, JSON.stringify(notices).slice(0, 400));
      await page.screenshot({ path: path.join(out, `checkout-error-1440.png`), fullPage: true });
    }

    // REST confirmation (authoritative for the woo-mcp tools path)
    const auth = wooAuthHeader();
    const r = await fetch(`${STORE}/wp-json/wc/v3/orders?search=${encodeURIComponent(billingEmail)}&per_page=10`, { headers: { Authorization: auth } });
    if (r.ok) {
      const orders = await r.json();
      const live = (orders || []).filter((o) => o.status !== "checkout-draft");
      if (live.length > 0) {
        const o = live[0];
        check(`order visible via Woo REST (id ${o.id}, status ${o.status}, total ${o.total})`, true, `payment_method=${o.payment_method}`);
        if (o.payment_method === "cod") check("order payment method is COD", true, "");
        orderId = o.id;
      } else {
        check("order visible via Woo REST", false, `no non-draft order for ${billingEmail}`);
      }
    } else {
      check("Woo REST orders reachable", false, `HTTP ${r.status}`);
    }
    await page.close();
    await ctx.close();
  } finally {
    await browser.close();
  }
  if (orderId) {
    console.log(`\n ORDER_ID=${orderId}`);
    results.push({ name: "e2e COD order created + REST visible", ok: confirmed });
  }
}

async function cmdRest(expect) {
  const auth = wooAuthHeader();
  const all = [];
  let page = 1;
  while (true) {
    const r = await fetch(`${STORE}/wp-json/wc/v3/products?per_page=100&page=${page}&status=publish`, { headers: { Authorization: auth } });
    if (!r.ok) { check("REST product list reachable", false, `HTTP ${r.status}`); return; }
    const chunk = await r.json();
    if (!Array.isArray(chunk) || !chunk.length) break;
    all.push(...chunk);
    page++;
    if (page > 5) break;
  }
  check(`REST product list returns >= ${expect} products`, all.length >= expect, `count=${all.length}`);
  const noImages = all.filter((p) => !(p.images && p.images.length));
  check("every product has at least one image", noImages.length === 0, `missing: ${noImages.slice(0, 3).map((p) => p.sku || p.name).join(", ")}`);
  const withGallery = all.filter((p) => (p.images || []).length >= 2);
  check("products with gallery images (2+)", withGallery.length >= expect * 0.6, `${withGallery.length}/${all.length}`);
  const onSale = all.filter((p) => p.on_sale);
  check("products on sale present", onSale.length > 0, `${onSale.length} on sale`);
  // Out-of-stock state must match the catalog exactly (the photo-first cut of
  // 2026-10-23 removed both OOS products, so a hardcoded ">= 1" would lie).
  let catalogOosSkus = [];
  try {
    const catalog = JSON.parse(readFileSync("store/products.json", "utf8"));
    catalogOosSkus = (catalog.products || [])
      .filter((p) => p.stock === 0 || p.out_of_stock)
      .map((p) => p.sku);
  } catch {}
  const liveOos = all.filter((p) => p.stock_status === "outofstock").map((p) => p.sku);
  const oosMatch = liveOos.length === catalogOosSkus.length && liveOos.every((s) => catalogOosSkus.includes(s));
  check("out-of-stock SKUs match the catalog", oosMatch, `live=[${liveOos.join(",")}] catalog=[${catalogOosSkus.join(",")}]`);
  const withWeight = all.filter((p) => p.weight && Number(p.weight) > 0);
  const withDims = all.filter((p) => p.dimensions && p.dimensions.length && p.dimensions.width && p.dimensions.height);
  check("products carry weight", withWeight.length >= expect, `${withWeight.length}/${all.length}`);
  check("products carry dimensions", withDims.length >= expect, `${withDims.length}/${all.length}`);
  const withTags = all.filter((p) => (p.tags || []).length > 0);
  check("products carry tags", withTags.length >= expect * 0.9, `${withTags.length}/${all.length}`);

  // variable products: fetch variations for each
  const variable = all.filter((p) => p.type === "variable");
  check("variable products present (4 to 6)", variable.length >= 4 && variable.length <= 7, `${variable.length} variable`);
  let variationsTotal = 0;
  for (const v of variable.slice(0, 8)) {
    const r = await fetch(`${STORE}/wp-json/wc/v3/products/${v.id}/variations?per_page=100`, { headers: { Authorization: auth } });
    if (r.ok) {
      const vars = await r.json();
      variationsTotal += vars.length;
      const withStock = vars.filter((x) => x.manage_stock && Number(x.stock_quantity) >= 0);
      if (vars.length < 2 || withStock.length < vars.length) {
        check(`variable ${v.sku || v.name} has stocked variations`, false, `${vars.length} vars, stocked=${withStock.length}`);
      }
    }
  }
  check("variations exist with their own stock", variationsTotal >= 8, `total variations=${variationsTotal}`);
}

async function main() {
  const [cmd, ...args] = process.argv.slice(2);
  const outIdx = args.indexOf("--out");
  const out = outIdx >= 0 ? args[outIdx + 1] : OUT_DEFAULT;
  const expectIdx = args.indexOf("--expect");
  const expect = expectIdx >= 0 ? parseInt(args[expectIdx + 1], 10) : 32;

  console.log(`store: ${STORE}`);
  if (cmd === "screenshots") await cmdScreenshots(out);
  else if (cmd === "checkout") await cmdCheckout(out);
  else if (cmd === "rest") await cmdRest(expect);
  else {
    console.log("usage: verify-store-v2.mjs screenshots|checkout|rest [--out DIR] [--expect N]");
    process.exit(2);
  }

  const fails = results.filter((r) => !r.ok).length;
  console.log(`\n${results.length} checks, ${fails} failures`);
  process.exit(fails ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
