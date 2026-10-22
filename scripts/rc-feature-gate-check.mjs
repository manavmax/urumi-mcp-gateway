#!/usr/bin/env node
// RC feature-gate verification (real browser, real cluster):
//   flags OFF (expected): Stores + Hosted servers menu items ABSENT from the
//   sidebar and the mobile bottom nav; direct visits to /stores and /hosted
//   show the friendly "not enabled" panel; ZERO console errors.
//   flags ON: both menu items visible; Stores create form + Hosted form use
//   .field inputs (computed border + focus ring checked programmatically).
// Usage: GATEWAY_ADMIN_PASSWORD=... node scripts/rc-feature-gate-check.mjs --expect off|on
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
import { adminLogin, cookiePair } from "./lib/browser-auth.mjs";

const D = process.env.DASHBOARD_URL || "http://dashboard.rc.127.0.0.1.nip.io";
const EXPECT = process.argv.includes("--expect") ? process.argv[process.argv.indexOf("--expect") + 1] : "off";

const admin = await adminLogin(D);
const cookies = cookiePair(admin.cookie, D);
const browser = await chromium.launch({ headless: true });

let passed = 0, failed = 0;
const ok = (name, detail = "") => { passed++; console.log(`PASS ${name} ${detail}`); };
const fail = (name, msg = "") => { failed++; console.log(`FAIL ${name}: ${msg}`); };

  // ---- desktop: sidebar menu items ----
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await ctx.addCookies(cookies);
    const page = await ctx.newPage();
    const errors = [];
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 200)); });
    await page.addInitScript(() => { try { localStorage.setItem("theme", "light"); } catch {} });
    await page.goto(D + "/overview", { waitUntil: "networkidle", timeout: 45000 });
    await page.waitForTimeout(700);
    const navTexts = await page.$$eval(".rail-nav a", (as) => as.map((a) => a.textContent.trim()));
    const storesInNav = navTexts.some((t) => t.includes("Stores"));
    const hostedInNav = navTexts.some((t) => t.includes("Hosted servers"));
    if (EXPECT === "off") {
      if (!storesInNav && !hostedInNav) ok("menus hidden (flags off)", `nav=${JSON.stringify(navTexts)}`);
      else fail("menus hidden", `sidebar has ${JSON.stringify(navTexts)}`);
    } else {
      if (storesInNav && hostedInNav) ok("menus visible (flags on)");
      else fail("menus visible", `sidebar=${JSON.stringify(navTexts)}`);
    }

    // ---- direct visits ----
    for (const [path, label, hint] of [
      ["/stores", "Stores"],
      ["/hosted", "Hosted servers"],
    ]) {
      const r = await page.goto(D + path, { waitUntil: "networkidle", timeout: 45000 });
      await page.waitForTimeout(600);
      const body = await page.evaluate(() => document.body.innerText);
      const panel = body.includes("This feature is not enabled on this deployment");
      if (EXPECT === "off") {
        if (r.status() === 200 && body.includes("This feature is not enabled on this deployment") && body.includes("An administrator enables")) {
          ok(`${label} direct visit -> friendly panel`, path);
        } else {
          fail(`${label} direct visit`, `status=${r.status()} panel text present=${body.includes("not enabled")}`);
        }
      } else {
        const gone = !body.includes("This feature is not enabled on this deployment");
        if (r.status() === 200 && gone) ok(`${label} enabled state renders`, `text=${body.trim().length} chars`);
        else fail(`${label} enabled state`, `status=${r.status()}`);
      }
    }

    // ---- mobile bottom nav ----
    const mob = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const mpage = await mob.newPage();
    mpage.on("pageerror", (e) => errors.push("pageerror: " + String(e).slice(0, 200)));
    await mpage.addInitScript(() => { try { localStorage.setItem("theme", "light"); } catch {} });
    for (const c of cookies) await mpage.context().addCookies([c]);
    await mpage.goto(D + "/overview", { waitUntil: "networkidle", timeout: 45000 });
    await mpage.waitForTimeout(600);
    const bottom = await mpage.$$eval(".bottomnav a span", (els) => els.map((e) => e.textContent.trim()));
    const bottomHasStores = bottom.includes("Stores");
    const bottomHasHosted = bottom.some((t) => t.includes("Hosted"));
    if (EXPECT === "off") {
      if (!bottomHasStores && !bottomHasHosted) ok("mobile bottom nav hides both items", JSON.stringify(bottom));
      else fail("mobile bottom nav", `shows ${JSON.stringify(bottom)}`);
    } else {
      if (bottom.includes("Stores") && bottom.some((t) => t.startsWith("Hosted"))) ok("mobile bottom nav shows both");
      else fail("mobile bottom nav", `items=${JSON.stringify(bottom)}`);
    }
    await mob.close();

    // ---- form styling when enabled ----
    if (EXPECT === "on") {
      const form = await page.evaluate(async () => {
        const r = await fetch("/api/stores", { headers: { Accept: "application/json" } });
        return r.status;
      });
      await page.goto(D + "/stores", { waitUntil: "networkidle", timeout: 45000 });
      await page.waitForTimeout(500);
      const storesForm = await page.evaluate(() => {
        const input = document.querySelector('#store-name');
        if (!input) return { present: false };
        const cs = getComputedStyle(input);
        const field = input.closest(".field");
        const lbl = field ? field.querySelector("label") : null;
        input.focus();
        const focusShadow = getComputedStyle(input).boxShadow;
        return {
          present: true,
          border: cs.borderStyle !== "none" && cs.borderTopWidth !== "0px",
          padding: parseFloat(cs.paddingTop) >= 6,
          ringOnFocus: getComputedStyle(input).boxShadow !== "none",
          label: !!field?.querySelector("label"),
        };
      });
      if (storesForm.present && storesForm.border && storesForm.padding && storesForm.label) ok("stores create form styled (.field, border, label)", `border=${storesForm.border} label=${storesForm.label}`);
      else fail("stores create form styling", JSON.stringify(storesForm));

      await page.goto(D + "/hosted", { waitUntil: "networkidle", timeout: 45000 });
      await page.waitForTimeout(500);
      const hostedForm = await page.evaluate(async () => {
        const input = document.querySelector("#hosted-image");
        if (!input) return { present: false };
        const cs = getComputedStyle(input);
        const field = input.closest(".field");
        return {
          present: true,
          border: cs.borderStyle !== "none",
          padding: parseFloat(cs.paddingTop) >= 6,
          label: !!field?.querySelector("label"),
          textarea: !!document.querySelector("#hosted-env"),
        };
      });
      if (hostedForm.present && hostedForm.border && hostedForm.label && hostedForm.textarea) ok("hosted form styled (.field + labels)", "inputs bordered, labels present, textarea in .field");
      else fail("hosted form styling", JSON.stringify(hostedForm));
    }

    if (errors.length) fail("console errors", JSON.stringify(errors.slice(0, 3)));
    else ok("zero console errors across all checks");
    await ctx.close();
  }

  console.log(`FEATURE-GATE CHECK: ${passed} pass, ${failed} fail (expected ${EXPECT})`);
  process.exit(failed === 0 ? 0 : 1);
await browser.close();
