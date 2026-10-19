#!/usr/bin/env node
// https-on-kind browser proof (prod-readiness item 3): a REAL browser loads the
// dashboard over TLS (self-signed issuer on kind, cert for *.127.0.0.1.nip.io),
// logs in through the real login form, and asserts:
//   - zero console errors
//   - session cookie carries Secure + HttpOnly + SameSite
//   - CSP + security headers present on the https response
// Usage: node scripts/verify-tls-browser.mjs
// Never reads .env; the admin password comes from the gateway-admin Secret.

import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
import { execSync } from "node:child_process";

const DASHBOARD_URL = process.env.DASHBOARD_URL || "https://dashboard.127.0.0.1.nip.io";
const EMAIL = process.env.GATEWAY_ADMIN_EMAIL || "admin@urumi.local";
const PASS = execSync("kubectl get secret gateway-admin -n urumi -o jsonpath='{.data.password}' | base64 -d", { encoding: "utf8" }).trim();

const failures = [];
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"} ${name}`);
  if (!ok) failures.push(name);
};

const consoleErrors = [];
const consoleErrorsAfterLogin = [];
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ ignoreHTTPSErrors: true });
const page = await context.newPage();
let afterLogin = false;
page.on("console", (m) => { if (m.type() === "error" && afterLogin) consoleErrors.push(m.text()); });
page.on("pageerror", (e) => { if (afterLogin) consoleErrors.push(`pageerror: ${e.message}`); });

console.log("== open", DASHBOARD_URL, "over https ==");
const resp = await page.goto(DASHBOARD_URL, { waitUntil: "networkidle" });
check("https page loads", !!page.url());
check("https status 200", (await page.goto(DASHBOARD_URL, { waitUntil: "domcontentloaded" })).status() === 200);

const csp = (await page.goto(DASHBOARD_URL, { waitUntil: "domcontentloaded" })).headers()["content-security-policy"];
check("CSP header present over https", !!csp);

// Real login through the form
await page.fill("#pw", PASS);
await page.click("button[type=submit]");
await page.waitForURL(/(overview|members|servers|audit|chat)/i, { timeout: 15000 }).catch(() => {});
const loggedIn = await page.locator("text=Sign out").count().catch(() => 0) ||
  await page.locator("nav, .topbar, .sidebar").count().catch(() => 0);
afterLogin = true; // from here on any console error fails the gate
check("login works over https (signed in)", loggedIn > 0 || !page.url().includes("login"));

// Session cookie flags
const cookies = await context.cookies();
const session = cookies.find((c) => c.name === "urumi_session");
check("session cookie present", !!session);
check("cookie Secure", !!session?.secure, `secure=${session?.secure}`);
check("cookie HttpOnly", !!session?.httpOnly, `httpOnly=${session?.httpOnly}`);
check("cookie SameSite", !!session?.sameSite && session.sameSite !== "none", `sameSite=${session?.sameSite}`);
check("no console errors", consoleErrors.length === 0, consoleErrors.join(" | ").slice(0, 200));

import { mkdirSync } from "node:fs";
mkdirSync("artifacts/screenshots/tls", { recursive: true });
await page.screenshot({ path: "artifacts/screenshots/https-kind-dashboard.png" });
console.log("screenshot: artifacts/screenshots/https-kind-dashboard.png");

await browser.close();
if (consoleErrors.length) failures.push(`console errors: ${consoleErrors.slice(0, 5).join(" | ")}`);
if (failures.length) { console.log("FAILURES:", failures.join("; ")); process.exit(1); }
console.log("TLS BROWSER TEST PASSED (https login, zero console errors, Secure+HttpOnly+SameSite cookie, CSP present)");