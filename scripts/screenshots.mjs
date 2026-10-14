#!/usr/bin/env node
// BEFORE/AFTER screenshots - uses playwright-core (installed as dashboard devDep).
// Creates a throwaway member, screenshots as admin + member at desktop/mobile, then deletes it.
// Writes to artifacts/screenshots/{before,after}/{admin,member}/{page}-{width}.png
// Usage: node scripts/screenshots.mjs --stage before|after
// Never reads .env.

import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
// Repo-relative: resolves from this script's own directory (scripts/), so the
// script runs from any checkout/mount path. The dashboards/node_modules install
// is what ships playwright-core (see src/dashboard/package.json devDependencies).
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
import { randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const STAGE = (() => {
  const i = process.argv.indexOf("--stage");
  return i !== -1 ? process.argv[i + 1] : "before";
})();
if (!["before", "after"].includes(STAGE)) {
  console.error("usage: node scripts/screenshots.mjs --stage before|after");
  process.exit(2);
}
const DASHBOARD_URL = process.env.DASHBOARD_URL || "http://dashboard.127.0.0.1.nip.io";
const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "mobile", width: 375, height: 812 },
];
const PAGES = [
  { path: "/", label: "servers" },
  { path: "/servers", label: "servers" },
  { path: "/members", label: "members" },
  { path: "/audit", label: "audit" },
  { path: "/chat", label: "chat" },
  { path: "/login", label: "login" },
];

async function httpJson(url, { method = "GET", body, headers = {}, cookie } = {}) {
  const h = { "Content-Type": "application/json", ...headers };
  if (cookie) h["Cookie"] = cookie;
  const res = await fetch(url, { method, headers: h, body: body ? JSON.stringify(body) : undefined });
  const text = await res.text();
  let json = null;
  try { json = JSON.parse(text); } catch {}
  return { res, text, json, ok: res.ok, status: res.status, setCookie: res.headers.get("set-cookie") || "" };
}
function parseCookie(setCookieHeader) {
  return setCookieHeader.split(",").map(s => s.split(";")[0].trim()).filter(Boolean).join("; ");
}
async function adminLogin() {
  let pass = process.env.GATEWAY_ADMIN_PASSWORD || "";
  let email = process.env.GATEWAY_ADMIN_EMAIL || "admin@urumi.local";
  if (!pass) {
    const { execSync } = await import("node:child_process");
    pass = execSync("kubectl get secret gateway-admin -n urumi -o jsonpath='{.data.password}' | base64 -d", { encoding: "utf8" }).trim();
  }
  const r = await httpJson(`${DASHBOARD_URL}/api/auth/login`, { method: "POST", body: { email, password: pass } });
  if (!r.ok) throw new Error(`admin login failed ${r.status} ${r.text.slice(0, 500)}`);
  const cookie = parseCookie(r.setCookie);
  const csrf = r.json?.csrf_token || "";
  return { cookie, csrf, email, pass };
}
async function createThrowawayMember(adminCookie, adminCsrf) {
  const email = `tmp-member-${randomUUID().slice(0, 8)}@example.invalid`;
  const password = `Tmp-${randomUUID().slice(0, 12)}-a1!`;
  const r = await httpJson(`${DASHBOARD_URL}/api/users`, {
    method: "POST", body: { email, password, role: "member" },
    cookie: adminCookie, headers: { "X-CSRF-Token": adminCsrf },
  });
  if (!r.ok) throw new Error(`create member failed ${r.status} ${r.text.slice(0, 500)}`);
  return { email, password, id: r.json?.id };
}
async function deleteMember(adminCookie, adminCsrf, userId) {
  const r = await httpJson(`${DASHBOARD_URL}/api/users/${userId}`, {
    method: "DELETE", cookie: adminCookie, headers: { "X-CSRF-Token": adminCsrf },
  });
  if (!r.ok && r.status !== 204) console.error(`delete member ${userId} -> ${r.status} ${r.text.slice(0, 300)}`);
}
async function memberLogin(email, password) {
  const r = await httpJson(`${DASHBOARD_URL}/api/auth/login`, { method: "POST", body: { email, password } });
  if (!r.ok) throw new Error(`member login ${email} failed ${r.status} ${r.text.slice(0, 500)}`);
  return { cookie: parseCookie(r.setCookie), csrf: r.json?.csrf_token || "" };
}

async function screenshotStage({ adminCookie, memberCookie }) {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const role of ["admin", "member"]) {
      const cookieHeader = role === "admin" ? adminCookie : memberCookie;
      for (const vp of VIEWPORTS) {
        for (const pg of PAGES) {
          // Deduplicate: "/" and "/servers" same screenshot; skip duplicate label+viewport per role
          // Actually capture both but second overwrites; keep distinct by path
          const tag = pg.path === "/" ? "servers-root" : pg.label;
          const context = await browser.newContext({
            viewport: { width: vp.width, height: vp.height },
          });
          const page = await context.newPage();
          const target = `${DASHBOARD_URL}${pg.path}`;
          // Prime session cookie via document.cookie after first goto to root
          await page.goto(DASHBOARD_URL, { waitUntil: "networkidle", timeout: 15000 });
          if (pg.path !== "/login" && cookieHeader) {
            const token = cookieHeader.split("urumi_session=")[1]?.split(";")[0] || "";
            if (token) await page.evaluate((tok) => { document.cookie = `urumi_session=${tok}; path=/`; }, token);
          }
          if (pg.path === "/login") {
            await page.evaluate(() => { document.cookie = "urumi_session=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/"; });
          }
          await page.goto(target, { waitUntil: "networkidle", timeout: 15000 });
          await page.waitForTimeout(900);
          const outDir = join(ROOT, "artifacts", "screenshots", STAGE, role);
          mkdirSync(outDir, { recursive: true });
          const out = join(outDir, `${tag}-${vp.name}.png`);
          await page.screenshot({ path: out, fullPage: true });
          console.log(`wrote ${out}`);
          await context.close();
        }
      }
    }
  } finally {
    await browser.close();
  }
}

async function main() {
  console.log(`stage=${STAGE} url=${DASHBOARD_URL}`);
  const admin = await adminLogin();
  console.log(`admin login ok as ${admin.email}`);
  let member = null;
  let memberAuth = null;
  try {
    member = await createThrowawayMember(admin.cookie, admin.csrf);
    console.log(`throwaway member ${member.email} id=${member.id}`);
    memberAuth = await memberLogin(member.email, member.password);
  } catch (e) {
    console.error(`throwaway member create/login failed: ${e.message} — continuing with admin screenshots only`);
  }
  try {
    await screenshotStage({ adminCookie: admin.cookie, memberCookie: memberAuth?.cookie || "" });
  } finally {
    if (member?.id) {
      await deleteMember(admin.cookie, admin.csrf, member.id);
      console.log(`deleted throwaway member ${member.id}`);
    }
  }
  console.log("done");
}
main().catch((e) => { console.error(e); process.exit(1); });
