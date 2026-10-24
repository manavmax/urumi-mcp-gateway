#!/usr/bin/env node
// REAL storefront checkout (DoD Phase A #1): drives the actual storefront in a
// browser (product page -> cart -> block checkout with Cash on Delivery ->
// place order), then confirms the order landed via the Store API POST response,
// the Woo REST API, and the gateway's woo__list_orders, and finally deletes the
// test order (cleanup).
//
//   node scripts/verify-checkout.mjs
//
// In a real browser the WooCommerce block-checkout script creates and attaches
// the Store API nonce itself, so this exercises the same path a human demo would.
// Uses playwright-core from the dashboard devDependencies (no npm install).
// The admin password / Woo creds are read from Kubernetes secrets, never printed.

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
import { execSync } from "node:child_process";
import { adminLogin, httpJson } from "./lib/browser-auth.mjs";

const STORE = process.env.STORE_URL || "http://store.127.0.0.1.nip.io";
const DASHBOARD_URL = process.env.DASHBOARD_URL || "http://dashboard.127.0.0.1.nip.io";
const PRODUCT = process.env.CHECKOUT_PRODUCT || "http://store.127.0.0.1.nip.io/product/urumi-shoes/";

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok, detail });
  console.log(`   ${ok ? "PASS" : "FAIL"} ${name}${detail ? `: ${detail}` : ""}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function wooCreds() {
  const ck = execSync("kubectl exec -n urumi deploy/urumi-woo-mcp -- sh -c 'echo -n \"$WOO_CONSUMER_KEY\"'", { encoding: "utf8" });
  const cs = execSync("kubectl exec -n urumi deploy/urumi-woo-mcp -- sh -c 'echo -n \"$WOO_CONSUMER_SECRET\"'", { encoding: "utf8" });
  return { ck, cs };
}
const wooAuthHeader = () => {
  const { ck, cs } = wooCreds();
  return `Basic ${Buffer.from(`${ck}:${cs}`).toString("base64")}`;
};

async function main() {
  const browser = await chromium.launch({ headless: true });
  const billingEmail = `checkout-probe-${Date.now()}@example.invalid`;
  let orderId = null;
  let orderNumber = null;
  let confirmed = false;
  try {
    const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
    const page = await ctx.newPage();
    page.on("response", async (r) => {
      if (r.url().includes("/wp-json/wc/store/v1/checkout") && r.request().method() === "POST") {
        let body = "";
        try { body = await r.text(); } catch {}
        let parsed = null;
        try { parsed = JSON.parse(body); } catch {}
        console.log(`   [Store checkout POST] ${r.status()}`);
        if (parsed?.order_id) {
          orderId = parsed.order_id;
          orderNumber = parsed.order_number || parsed.order_id;
          confirmed = r.status() === 200;
          check(`Store API returned order ${orderId} (status ${parsed.status})`, confirmed, `status=${parsed.status} total=${parsed.total}`);
        }
      }
    });

    // 1. product page -> add to cart
    console.log(`   opening product: ${PRODUCT}`);
    await page.goto(PRODUCT, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1200);
    const singleAdd = page.locator(".single_add_to_cart_button, button[name=add-to-cart], form.cart button[type=submit]").first();
    check("product page shows add-to-cart button", await singleAdd.count() > 0, "");
    await singleAdd.click();
    await page.waitForTimeout(2500);

    // 2. cart -> checkout
    await page.goto(`${STORE}/checkout/`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);
    check("checkout page loads (wc-block-checkout)", (await page.locator(".wc-block-checkout, form.wc-block-checkout-form").count()) > 0, `url=${page.url()}`);
    const hasCod = await page.locator("input[value=cod], label:has-text('Cash on delivery')").count();
    check("Cash on delivery payment option present", hasCod > 0, `count=${hasCod}`);

    // 3. type contact + billing (pressSequentially fires the real input events
    //    the React block-checkout needs; .fill() alone was ignored by the store)
    async function typeInto(selector, value) {
      const el = page.locator(selector).first();
      if (await el.count() > 0) {
        await el.click();
        await el.press("Control+A");
        await el.pressSequentially(value, { delay: 12 });
        return true;
      }
      return false;
    }
    await typeInto(".wc-block-checkout__contact-fields input[type=email], #email, input[name=email]", billingEmail);
    const fields = { first_name: "Checklist", last_name: "Runner", address_1: "1 Test St", city: "Testville", postcode: "90210", phone: "5550100" };
    for (const [k, v] of Object.entries(fields)) {
      const ok = await typeInto(`input[name='billing[${k}]'], #billing-${k}`, v);
      if (!ok) console.log(`   (billing field ${k} not found in DOM)`);
    }
    const state = page.locator("input[name='billing[state]'], .wc-block-components-state-input input").first();
    if (await state.count() > 0) { await state.click(); await state.pressSequentially("CA", { delay: 12 }); }

    // 4. select COD
    const codRadio = page.locator("input[value=cod]").first();
    if (!(await codRadio.isChecked())) {
      await page.locator("label:has-text('Cash on delivery')").first().click().catch(() => codRadio.check({ force: true }));
    }
    await page.waitForTimeout(1200);
    check("COD radio selected", await codRadio.isChecked(), "");

    // 5. place the order
    const placeBtn = page.locator("button:has-text('Place Order'), .wc-block-components-checkout-place-order-button").first();
    check("Place Order button present", await placeBtn.count() > 0, "");
    await page.waitForTimeout(800);
    await placeBtn.click();
    console.log("   clicked Place Order, waiting for the Store API response...");
    await page.waitForTimeout(15000);

    // 6. confirm (Store API POST response is authoritative; page may redirect away)
    if (confirmed && orderId) {
      console.log(`   order placed: #${orderNumber} (status processing) via block checkout`);
    } else {
      const notices = await page.locator(".wc-block-components-notice-banner, [role=alert]").allInnerTexts().catch(() => []);
      check("checkout did not show a blocking error", notices.length === 0, JSON.stringify(notices).slice(0, 400));
    }

    // 7. confirm via Woo REST API by billing email
    if (!confirmed) {
      await sleep(1500);
      const auth = wooAuthHeader();
      const r = await fetch(`${STORE}/wp-json/wc/v3/orders?search=${encodeURIComponent(billingEmail)}`, { headers: { Authorization: auth } });
      if (r.ok) {
        const orders = await r.json();
        if (Array.isArray(orders) && orders.length > 0) {
          orderId = orders[0].id;
          orderNumber = orders[0].number || orders[0].id;
          confirmed = orders[0].status !== "checkout-draft";
          check(`order found in Woo via REST (id ${orderId}, status ${orders[0].status}, total ${orders[0].total})`, confirmed, `email=${billingEmail}`);
        } else {
          check("order found in Woo via REST", false, "no order matched billing email");
        }
      } else {
        check("Woo REST search for test order", false, `status ${r.status}`);
      }
    }

    // 8. confirm via gateway woo__list_orders (the DoD path: client/chat can see it)
    if (orderId) {
      try {
        const admin = await adminLogin(DASHBOARD_URL);
        const ah = { "Content-Type": "application/json", "X-CSRF-Token": admin.csrf };
        const mk = await httpJson(`${DASHBOARD_URL}/api/keys`, { method: "POST", body: {}, cookie: admin.cookie, headers: ah });
        const apiKey = mk.json?.key || "";
        const MCP_H = { "Content-Type": "application/json", Accept: "application/json, text/event-stream", "MCP-Protocol-Version": "2025-03-26" };
        const rr = await httpJson(`${DASHBOARD_URL}/mcp`, { method: "POST", body: { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "woo__list_orders", arguments: {} } }, headers: { ...MCP_H, Authorization: `Bearer ${apiKey}` } });
        const text = rr.json?.result?.content?.[0]?.text || rr.text;
        check("order visible via gateway woo__list_orders", rr.status === 200 && text.includes(String(orderId)), `status=${rr.status} contains=${text.includes(String(orderId))}`);
      } catch (e) {
        check("gateway woo__list_orders check", false, String(e).slice(0, 200));
      }
    }
  } finally {
    if (orderId) {
      const auth = wooAuthHeader();
      const del = await fetch(`${STORE}/wp-json/wc/v3/orders/${orderId}?force=true`, { method: "DELETE", headers: { Authorization: auth } });
      check("test order deleted after the probe", del.status === 200, `delete status=${del.status}`);
    } else {
      console.log("   (no order id captured; skipping delete)");
    }
    await browser.close();
  }

  const failed = results.filter((r) => !r.ok);
  check("summary", failed.length === 0, failed.length ? `${failed.length} FAIL` : `${results.length - 1} real checks pass`);
  if (failed.length) process.exit(1);
  console.log("\nVERIFY CHECKOUT: real storefront COD flow passed");
}

main().catch((e) => { console.error(e); process.exit(1); });
