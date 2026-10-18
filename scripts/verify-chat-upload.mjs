#!/usr/bin/env node
// I1 integration pass, item D: chat image ATTACH flow, live in a real browser.
// Proves, end to end, with an ADMIN session:
//   1. attaching a tiny PNG through the hidden file input shows an in-memory
//      preview thumbnail (blob: URL) with a remove button;
//   2. the remove button clears the preview;
//   3. drag & drop on the composer (a real DataTransfer drop event) attaches;
//   4. a GIF and an oversized file are rejected CLIENT-SIDE with clear text;
//   5. sending "create a product named I1 Proof Tee priced 12.99 and attach this
//      image" yields tool chips naming product creation and the image attach;
//   6. the created product is visible through the STORE REST API with an image
//      whose images[0].src URL returns 200 + an image content type;
//   7. localStorage history contains the "[image]" placeholder and NO base64
//      (no "iVBOR" substring, no stored value over 5000 chars);
//   8. a MEMBER role without write permission is never offered the attach
//      helper (permissions-based check: woo__add_product_image is filtered from
//      the member's /api/tools, and the agent only offers the helper when that
//      tool is allowed).
// Run: node scripts/verify-chat-upload.mjs (needs the live dashboard + store,
// the admin gateway session and the live LLM chain).
import { createRequire } from "node:module";
import { execSync } from "node:child_process";
import * as browserAuth from "./lib/browser-auth.mjs";

const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");

const DASHBOARD_URL = process.env.DASHBOARD_URL || "http://dashboard.127.0.0.1.nip.io";
const STORE = process.env.STORE_URL || "http://store.127.0.0.1.nip.io";
const PRODUCT_NAME = "I1 Proof Tee";
const failures = [];
const check = (name, ok, detail) => {
  console.log(`   ${ok ? "PASS" : "FAIL"} ${name}${detail ? `: ${detail}` : ""}`);
  if (!ok) failures.push(`${name}${detail ? `: ${detail}` : ""}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// A real tiny PNG so the preview thumbnail renders actual bytes.
function tinyPng() {
  // 1x1 PNG (RGBA). Hand-built: signature + IHDR + IDAT + IEND.
  const base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
  return Buffer.from(base64, "base64");
}

function wooCreds() {
  const ck = execSync("kubectl exec -n urumi deploy/urumi-woo-mcp -- sh -c 'echo -n \"$WOO_CONSUMER_KEY\"'", { encoding: "utf8" });
  const cs = execSync("kubectl exec -n urumi deploy/urumi-woo-mcp -- sh -c 'echo -n \"$WOO_CONSUMER_SECRET\"'", { encoding: "utf8" });
  return { ck, cs };
}

async function deleteProductIfPresent(name) {
  try {
    const { ck, cs } = wooCreds();
    const auth = `Basic ${Buffer.from(`${ck}:${cs}`).toString("base64")}`;
    const r = await fetch(`${STORE}/wp-json/wc/v3/products?search=${encodeURIComponent(name)}&per_page=100`, { headers: { Authorization: auth } });
    if (!r.ok) return;
    const rows = await r.json();
    for (const p of Array.isArray(rows) ? rows : []) {
      if (p.name === name) {
        await fetch(`${STORE}/wp-json/wc/v3/products/${p.id}?force=true`, { method: "DELETE", headers: { Authorization: auth } });
        console.log(`   (cleanup: deleted pre-existing "${name}" #${p.id})`);
      }
    }
  } catch (e) {
    console.log(`   (cleanup note: could not delete pre-existing product: ${String(e).slice(0, 120)})`);
  }
}

const PNG = tinyPng();

async function main() {
  const browser = await chromium.launch({ headless: true });
  let memberCleanup = null;
  try {
    const admin = await browserAuth.adminLogin(DASHBOARD_URL);

    /* ---- 8. member-without-write is never offered the attach helper ---- */
    // Capture the current member deny policy, add a deny for the write tool,
    // verify it is filtered from a member's /api/tools, then restore.
    const permGet = await browserAuth.httpJson(`${DASHBOARD_URL}/api/permissions`, { cookie: admin.cookie });
    const currentDeny = [];
    for (const srv of permGet.json?.servers || []) {
      for (const t of srv.tools || []) if (t.member_denied) currentDeny.push({ server_slug: srv.slug, tool_name: t.name });
    }
    const denyRule = { server_slug: "woo", tool_name: "woo__add_product_image" };
    await browserAuth.httpJson(`${DASHBOARD_URL}/api/permissions`, {
      method: "PUT",
      cookie: admin.cookie,
      headers: { "X-CSRF-Token": admin.csrf },
      body: { rules: [...currentDeny, denyRule] },
    });
    try {
      const created = await browserAuth.createThrowawayMember(DASHBOARD_URL, admin.cookie, admin.csrf, "i1-upload-");
      memberCleanup = async () => browserAuth.deleteMember(DASHBOARD_URL, admin.cookie, admin.csrf, created.id);
      const m = await browserAuth.loginAs(DASHBOARD_URL, created.email, created.password);
      const mctx = await browser.newContext();
      await mctx.addCookies(browserAuth.cookiePair(m.cookie, DASHBOARD_URL));
      const mpage = await mctx.newPage();
      await mpage.goto(`${DASHBOARD_URL}/chat`, { waitUntil: "networkidle" });
      const memberTools = await mpage.evaluate(async () => {
        const r = await fetch("/api/tools", { credentials: "include" });
        const j = await r.json();
        return (j.tools || []).map((t) => t.name);
      });
      const hasWrite = memberTools.includes("woo__add_product_image");
      // The attach helper is only offered when woo__add_product_image is allowed
      // (chat/agent.py expose_attach), so its absence proves the member is never
      // offered the attach helper.
      check("member without write permission is not offered the attach helper (woo__add_product_image filtered from /api/tools)", !hasWrite, hasWrite ? `member still lists ${JSON.stringify(memberTools.slice(0, 8))}` : `member tools: ${memberTools.length} (write tool absent)`);
      await mctx.close();
    } finally {
      await browserAuth.httpJson(`${DASHBOARD_URL}/api/permissions`, {
        method: "PUT",
        cookie: admin.cookie,
        headers: { "X-CSRF-Token": admin.csrf },
        body: { rules: currentDeny },
      });
    }

    /* ---- remove any earlier I1 Proof Tee so the model creates it fresh ---- */
    await deleteProductIfPresent(PRODUCT_NAME);

    /* ---- main attach flow as admin ---- */
    const ctx = await browser.newContext();
    await ctx.addCookies(browserAuth.cookiePair(admin.cookie, DASHBOARD_URL));
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(`${DASHBOARD_URL}/chat`, { waitUntil: "networkidle" });

    // 1. attach through the file input -> preview thumbnail
    await page.setInputFiles(".composer input[type=file]", { name: "proof.png", mimeType: "image/png", buffer: PNG });
    await page.waitForSelector('.thread img[src^="blob:"]', { timeout: 8000 });
    const previewVisible = await page.$('.thread img[src^="blob:"]');
    check("attach via file input shows a preview thumbnail", !!previewVisible, "");

    // 2. remove button clears the preview
    await page.click('button[aria-label="Remove attached image"]');
    await page.waitForTimeout(200);
    const removed = (await page.$('.thread img[src^="blob:"]')) === null;
    check("remove button clears the preview", removed, "");

    // 3. drag & drop attaches (real DataTransfer with a File)
    const dropped = await page.evaluate((b64) => {
      const dt = new DataTransfer();
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      dt.items.add(new File([bytes], "drop.png", { type: "image/png" }));
      const form = document.querySelector(".composer");
      if (!form) return false;
      form.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt }));
      return true;
    }, PNG.toString("base64"));
    await page.waitForTimeout(400);
    const droppedPreview = (await page.$('.thread img[src^="blob:"]')) !== null;
    check("drag & drop attaches an image", dropped && droppedPreview, dropped ? "" : "drop event not dispatched");

    // 4a. GIF rejected client-side with clear text (no preview replaces the prior)
    await page.setInputFiles(".composer input[type=file]", { name: "anim.gif", mimeType: "image/gif", buffer: Buffer.from("GIF89a") });
    await page.waitForTimeout(250);
    const gifAlert = await page.$eval(".alert-error", (el) => (el.textContent || "").trim()).catch(() => "");
    check("GIF rejected client-side with a clear message", /only png, jpeg or webp/i.test(gifAlert), `alert="${gifAlert}"`);

    // 4b. oversized PNG (>5 MB) rejected client-side with clear text
    await page.setInputFiles(".composer input[type=file]", { name: "big.png", mimeType: "image/png", buffer: Buffer.concat([PNG, Buffer.alloc(5 * 1024 * 1024 + 1, 0)]) });
    await page.waitForTimeout(250);
    const bigAlert = await page.$eval(".alert-error", (el) => (el.textContent || "").trim()).catch(() => "");
    check("oversized file rejected client-side with a clear message", /too large/i.test(bigAlert), `alert="${bigAlert}"`);

    // clear the rejection banner + any stale preview before the send step
    await page.evaluate(() => {
      const btn = document.querySelector('button[aria-label="Remove attached image"]');
      if (btn) btn.click();
    });
    await page.waitForTimeout(200);

    // restore a valid attachment for the send step
    await page.setInputFiles(".composer input[type=file]", { name: "proof.png", mimeType: "image/png", buffer: PNG });
    await page.waitForSelector('.thread img[src^="blob:"]', { timeout: 8000 });

    // 5. send the create + attach request and assert the tool chips
    await page.fill('input[aria-label="Chat message"]', `create a product named ${PRODUCT_NAME} priced 12.99 and attach this image`);
    await page.press('input[aria-label="Chat message"]', "Enter");
    await page.waitForFunction(
      () => !document.querySelector(".typing") && document.querySelectorAll(".msg.assistant .bubble").length > 0,
      null,
      { timeout: 180000 },
    );
    await page.waitForTimeout(800);
    const toolNames = await page.$$eval(".tool-call .head .name", (els) => els.map((e) => (e.textContent || "").trim()));
    console.log(`   tool chips seen: ${JSON.stringify(toolNames)}`);
    const hasCreate = toolNames.some((n) => /create_product/i.test(n) || /create product/i.test(n));
    const hasAttach = toolNames.some((n) => /attach_product_image|add_product_image/i.test(n));
    check("tool chips show a product creation", hasCreate, `tools=${JSON.stringify(toolNames)}`);
    check("tool chips show the image attach", hasAttach, `tools=${JSON.stringify(toolNames)}`);

    // 6. product exists via the STORE REST with an image whose URL is live
    const prod = await (async () => {
      const r = await fetch(`${STORE}/wp-json/wc/store/v1/products?search=${encodeURIComponent(PRODUCT_NAME)}&per_page=50`);
      if (!r.ok) return { ok: false, detail: `store REST status ${r.status}` };
      const rows = await r.json();
      const p = (Array.isArray(rows) ? rows : []).find((x) => x.name === PRODUCT_NAME);
      if (!p) return { ok: false, detail: `no product named "${PRODUCT_NAME}" in store REST` };
      const src = Array.isArray(p.images) && p.images[0] ? p.images[0].src : null;
      return { ok: true, id: p.id, src, price: p.prices?.price };
    })();
    check(`product "${PRODUCT_NAME}" found via store REST`, prod.ok, prod.ok ? `id=${prod.id} price=${prod.price}` : prod.detail);
    let imgUrlOk = false;
    if (prod.ok && prod.src) {
      // The attachment URL may be https (WordPress normalises on the HTTPS
      // header) but the local store is served over plain HTTP; try both schemes.
      const candidates = [prod.src];
      if (/^https:\/\//i.test(prod.src)) candidates.push(prod.src.replace(/^https:\/\//i, "http://"));
      let imgStatus = 0;
      let imgCt = "";
      for (const u of candidates) {
        try {
          const img = await fetch(u, { headers: { Host: new URL(u).host } });
          imgStatus = img.status;
          imgCt = img.headers.get("content-type") || "";
          if (imgStatus === 200) break;
        } catch {
          /* try the next scheme */
        }
      }
      imgUrlOk = imgStatus === 200 && /^image\//.test(imgCt);
      check("images[0].src exists and the URL returns 200 with an image content type", imgUrlOk, `status=${imgStatus} content-type=${imgCt} url=${prod.src}`);
    } else if (prod.ok) {
      check("images[0].src exists and the URL returns 200 with an image content type", false, "product has no images[0].src");
    }

    // 7. localStorage history: "[image]" placeholder, no base64, no oversized values
    const hist = await page.evaluate((email) => {
      const key = `urumi.chat.${email || "anon"}`;
      const raw = localStorage.getItem(key) || "";
      const hasMarker = raw.includes("[image]");
      const hasB64 = raw.includes("iVBOR");
      const over = raw.length > 5000;
      return { rawLength: raw.length, hasMarker, hasB64, over };
    }, admin.email);
    check("localStorage history contains the [image] placeholder", hist.hasMarker, `rawLen=${hist.rawLength}`);
    check("localStorage history has NO base64 (no iVBOR, no value over 5000 chars)", !hist.hasB64 && !hist.over, `hasB64=${hist.hasB64} over=${hist.over} len=${hist.rawLength}`);

    // cleanup: delete the proof product created by this run
    await deleteProductIfPresent(PRODUCT_NAME);

    if (errors.length) check("no page errors", false, errors.join("; "));
    await ctx.close();
  } finally {
    if (memberCleanup) await memberCleanup();
    await browser.close();
  }

  if (failures.length) {
    console.error(`\n${failures.length} FAILING check(s):`);
    for (const f of failures) console.error(` - ${f}`);
    process.exit(1);
  }
  console.log("\nALL CHAT-UPLOAD CHECKS PASSED");
}

main().catch((e) => { console.error(e); process.exit(1); });
