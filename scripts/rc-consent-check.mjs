#!/usr/bin/env node
// RC consent page verification: styled card (dashboard tokens, light/dark via
// prefers-color-scheme), computed-style audit + screenshots + console checks.
// Usage: GATEWAY_ADMIN_PASSWORD=... DASHBOARD_URL=... OAUTH_URL_FILE=/tmp/rcr-oauth-url.txt \
//        node scripts/rc-consent-check.mjs
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
import { adminLogin, cookiePair } from "./lib/browser-auth.mjs";
import { readFileSync } from "node:fs";

const D = process.env.DASHBOARD_URL || "http://dashboard.rcr.127.0.0.1.nip.io";
const URL_FILE = process.env.OAUTH_URL_FILE || "/tmp/rcr-oauth-url.txt";
const OUT = "/Users/manavsharma/Desktop/Urumi_AI/artifacts/screenshots/rc-verify";
const authorizeUrl = readFileSync(URL_FILE, "utf8").split("\n")[0];

const issues = [];
let pass = 0, failed = 0;
const ok = (name, detail = "") => { pass++; console.log(`PASS ${name} ${detail}`); };
const fail = (name, msg = "") => { failed++; console.log(`FAIL ${name}: ${msg}`); };

const admin = await adminLogin(D);
const cookies = cookiePair(admin.cookie, D);
const browser = await chromium.launch({ headless: true });

try {
  for (const [scheme, schemeLabel] of [["light", "light"], ["dark", "dark"]]) {
    for (const [w, h, wl] of [[1440, 900, "1440"], [390, 844, "390"]]) {
      const ctx = await browser.newContext({ viewport: { width: w, height: h }, colorScheme: scheme });
      await ctx.addCookies(cookies);
      const page = await ctx.newPage();
      const errs = [];
      page.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 200)); });
      page.on("pageerror", (e) => errs.push(String(e).slice(0, 200)));
      const resp = await page.goto(authorizeUrl, { waitUntil: "networkidle", timeout: 45000 });
      await page.waitForTimeout(400);
      const audit = await page.evaluate(() => {
        const card = document.querySelector(".consent-card");
        if (!card) return { present: false };
        const cs = getComputedStyle(card);
        const approve = [...document.querySelectorAll("button")].find((b) => b.textContent === "Approve");
        const deny = [...document.querySelectorAll("button")].find((b) => b.textContent === "Deny");
        const r = card.getBoundingClientRect();
        return {
          present: true,
          hasShadow: cs.boxShadow !== "none",
          radius: cs.borderRadius,
          bodyBg: getComputedStyle(document.body).backgroundColor,
          maxW: cs.maxWidth,
          centered: Math.abs((card.getBoundingClientRect().left + card.getBoundingClientRect().right - window.innerWidth) / 2) < 40,
          approveBg: approve ? getComputedStyle(approve).backgroundColor : null,
          denyShadow: deny ? getComputedStyle(deny).boxShadow : null,
          clientShown: document.body.innerText.includes("Urumi CLI"),
          scopeShown: document.body.innerText.includes("mcp:tools"),
          resourceShown: document.body.innerText.includes("/mcp"),
          overflow: document.documentElement.scrollWidth - window.innerWidth,
        };
      });
      if (resp.status() === 200 && audit.present && audit.hasShadow && audit.overflow <= 2 && errs.length === 0 && audit.clientShown && audit.scopeShown) {
        pass++;
        console.log(`PASS consent-${w}-${schemeLabel}: card styled (radius=${audit.cardRadius} shadow=${audit.hasShadow} bg=${audit.bodyBg} maxW=${audit.maxW}), approve=${audit.approveBg}, deny inset-shadow=${audit.denyShadow !== "none"}, zero console errors`);
      } else {
        fail++;
        console.log(`FAIL consent-${w}-${schemeLabel}: ${JSON.stringify({ ...audit, errs: errs.slice(0, 2) })}`);
      }
      await page.screenshot({ path: `${OUT}/oauth-consent-${w}-${schemeLabel}.png` });
      await ctx.close();
    }
  }
  console.log(`CONSENT CHECK: ${pass} pass, ${failed} fail`);
  process.exit(fail === 0 ? 0 : 1);
} finally {
  await browser.close();
}
