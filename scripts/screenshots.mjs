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
import { mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { adminLogin, createThrowawayMember, deleteMember, loginAs, cookiePair } from "./lib/browser-auth.mjs";

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
  { path: "/", label: "overview-root" },
  { path: "/overview", label: "overview" },
  { path: "/servers", label: "servers" },
  { path: "/members", label: "members" },
  { path: "/audit", label: "audit" },
  { path: "/chat", label: "chat" },
  { path: "/login", label: "login" },
];

async function screenshotStage({ adminCookie, memberCookie }) {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const role of ["admin", "member"]) {
      const cookieHeader = role === "admin" ? adminCookie : memberCookie;
      for (const vp of VIEWPORTS) {
        for (const pg of PAGES) {
          const tag = pg.label;
          const context = await browser.newContext({
            viewport: { width: vp.width, height: vp.height },
          });
          // Same cookie-priming path as scripts/parity.mjs (shared browser-auth):
          // seed EVERY cookie from the login response via context.addCookies.
          // A fresh context has no cookies, so /login is unauthenticated.
          if (pg.path !== "/login" && cookieHeader) {
            await context.addCookies(cookiePair(cookieHeader, DASHBOARD_URL));
          }
          const page = await context.newPage();
          const target = `${DASHBOARD_URL}${pg.path}`;
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
  const admin = await adminLogin(DASHBOARD_URL);
  console.log(`admin login ok as ${admin.email}`);
  let member = null;
  let memberAuth = null;
  try {
    member = await createThrowawayMember(DASHBOARD_URL, admin.cookie, admin.csrf, "tmp-member-");
    console.log(`throwaway member ${member.email} id=${member.id}`);
    memberAuth = await loginAs(DASHBOARD_URL, member.email, member.password);
  } catch (e) {
    console.error(`throwaway member create/login failed: ${e.message} — continuing with admin screenshots only`);
  }
  try {
    await screenshotStage({ adminCookie: admin.cookie, memberCookie: memberAuth?.cookie || "" });
  } finally {
    if (member?.id) {
      await deleteMember(DASHBOARD_URL, admin.cookie, admin.csrf, member.id);
      console.log(`deleted throwaway member ${member.id}`);
    }
  }
  console.log("done");
}
main().catch((e) => { console.error(e); process.exit(1); });
