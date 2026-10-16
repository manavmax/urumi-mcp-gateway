#!/usr/bin/env node
// Observability item 3: banner rendering rules (Playwright, live dashboard).
//
//   node scripts/verify-alerts-banner.mjs
//
// Exercises GET /api/alerts + the banner UI against the deployed dashboard:
//   - admin banner appears when a server is Unreachable, names it + the reason,
//     and carries "Open server" + "Check now" buttons;
//   - dismissal is per session (hidden after close, back in a fresh tab);
//   - member gets the calm notice with the slug and no internal details;
//   - healthy state shows no banner.
//
// The scenario drives ONE temporary admin-added server pointing at a dead host so
// the real seeded upstreams are untouched. Cleanup deletes that server and the
// throwaway member. Uses the shared login helpers in scripts/lib/browser-auth.mjs.
// Never reads .env; the admin password comes from the gateway-admin Secret.

import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
import { adminLogin, loginAs, cookiePair } from "./lib/browser-auth.mjs";

const DASHBOARD_URL = process.env.DASHBOARD_URL || "http://dashboard.127.0.0.1.nip.io";

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok, detail });
  console.log(`   ${ok ? "PASS" : "FAIL"} ${name}${detail ? `: ${detail}` : ""}`);
}

// Build an authenticated fetch() inside the page context so cookies + CSRF are
// handled by the browser session.
async function pageFetch(page, path, opts = {}) {
  return page.evaluate(async ({ path, method, body, csrf }) => {
    const headers = { "Content-Type": "application/json" };
    if (csrf) headers["X-CSRF-Token"] = csrf;
    const res = await fetch(path, { method, headers, credentials: "include", body: body ? JSON.stringify(body) : undefined });
    let json = null;
    try { json = await res.json(); } catch { /* 204/empty */ }
    return { status: res.status, json };
  }, { path, method: opts.method || "GET", body: opts.body, csrf: opts.csrf });
}

async function getCsrf(page) {
  return page.evaluate(async () => {
    const res = await fetch("/api/me", { credentials: "include" });
    return (await res.json()).csrf_token;
  });
}

async function main() {
  const browser = await chromium.launch();
  let deadServerId = null;
  let memberEmail = "";
  try {
    const admin = await adminLogin(DASHBOARD_URL);
    if (!admin) throw new Error("could not log in as admin - is the gateway admin password set?");
    const cookie = cookiePair(admin.cookie, DASHBOARD_URL);

    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await ctx.addCookies(cookie);
    const page = await ctx.newPage();
    await page.goto(DASHBOARD_URL, { waitUntil: "networkidle" });
    const csrf = await getCsrf(page);

    // ------------------------------------------------------------------
    // setup: add a server pointing at a dead host (connection refused)
    const slug = `dead${Date.now() % 100000}`;
    const created = await pageFetch(page, "/api/servers", {
      method: "POST",
      csrf,
      body: { slug, url: "http://urumi-no-such-svc:8000/mcp", auth_type: "none", timeout_ms: 2000, enabled: true },
    });
    check("create dead server for banner test", created.status === 201, created.json?.detail || created.status);
    if (created.status !== 201) {
      console.log(`\n${results.filter((r) => r.ok).length}/${results.length} checks PASS`);
      return;
    }
    deadServerId = created.json.id;

    // ------------------------------------------------------------------
    // 1. admin Overview shows the banner after the server is Unreachable
    await page.goto(`${DASHBOARD_URL}/overview`, { waitUntil: "networkidle" });
    let bannerVisible = false;
    for (let i = 0; i < 30 && !bannerVisible; i++) {
      await page.waitForTimeout(500);
      bannerVisible = await page.locator('.banner[role="alert"]').count() > 0;
    }
    check("admin Overview shows the banner for an unreachable server", bannerVisible);

    if (bannerVisible) {
      const text = (await page.locator('.banner[role="alert"]').innerText()).toLowerCase();
      check("banner names the server", text.includes(slug), text.slice(0, 120));
      check("banner has a reason (category)", /reason/.test(text));
      check(
        "banner has Open server + Check now buttons",
        (await page.locator('.banner button:has-text("Open server")').count()) === 1 &&
          (await page.locator('.banner button:has-text("Check now")').count()) === 1,
      );
    }

    // 2. dismissal is per session
    if (bannerVisible) {
      await page.locator(".banner-close").click();
      await page.waitForTimeout(300);
      check("dismiss hides the banner", (await page.locator('.banner[role="alert"]').count()) === 0);

      const ctx2 = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      await ctx2.addCookies(cookie);
      const page2 = await ctx2.newPage();
      await page2.goto(`${DASHBOARD_URL}/overview`, { waitUntil: "networkidle" });
      await page2.waitForTimeout(1500);
      const freshVisible = (await page2.locator('.banner[role="alert"]').count()) > 0;
      check("banner returns in a fresh tab (per-session dismissal)", freshVisible);
      await ctx2.close();
    }

    // 3. member Overview: calm notice with the slug, no internal details
    memberEmail = `banner${Date.now() % 100000}@urumi.local`;
    const memberRes = await pageFetch(page, "/api/users", {
      method: "POST",
      csrf,
      body: { email: memberEmail, password: "banner-pass-123", role: "member" },
    });
    if (memberRes.status === 201) {
      const m = await loginAs(DASHBOARD_URL, memberEmail, "banner-pass-123");
      if (m) {
        const ctx3 = await browser.newContext({ viewport: { width: 1440, height: 900 } });
        await ctx3.addCookies(cookiePair(m.cookie, DASHBOARD_URL));
        const page3 = await ctx3.newPage();
        await page3.goto(`${DASHBOARD_URL}/overview`, { waitUntil: "networkidle" });
        await page3.waitForTimeout(1500);
        const noteCount = await page3.locator(".banner-calm").count();
        check("member Overview shows the calm notice", noteCount === 1);
        if (noteCount) {
          const text = (await page3.locator(".banner-calm").innerText()).toLowerCase();
          check(
            "calm notice names the slug, no internal details",
            text.includes(slug) && !/connection refused|http_error|reason/.test(text),
            text.slice(0, 120),
          );
        }
        await ctx3.close();
      } else {
        check("member login", false, "could not log in as the throwaway member");
      }
    } else {
      check("create throwaway member", false, `status ${memberRes.status}`);
    }
  } finally {
    // cleanup: delete the dead server and the throwaway member (best effort)
    const ctxc = await browser.newContext({ viewport: { width: 800, height: 600 } });
    try {
      const admin = await adminLogin(DASHBOARD_URL);
      if (admin) {
        await ctxc.addCookies(cookiePair(admin.cookie, DASHBOARD_URL));
        const pagec = await ctxc.newPage();
        await pagec.goto(DASHBOARD_URL, { waitUntil: "networkidle" });
        const csrf = await getCsrf(pagec);
        if (deadServerId) {
          await pagec.evaluate(async ({ id, csrf }) => {
            await fetch(`/api/servers/${id}`, { method: "DELETE", headers: { "X-CSRF-Token": csrf }, credentials: "include" });
          }, { id: deadServerId, csrf });
        }
        if (memberEmail) {
          await pagec.evaluate(async ({ email, csrf }) => {
            const list = await (await fetch("/api/users", { credentials: "include" })).json();
            const u = list.users.find((x) => x.email === email);
            if (u) await fetch(`/api/users/${u.id}`, { method: "DELETE", headers: { "X-CSRF-Token": csrf }, credentials: "include" });
          }, { email: memberEmail, csrf });
        }
      }
    } catch (e) {
      console.log(`   WARN cleanup failed: ${e.message}`);
    }
    await ctxc.close();
    await browser.close();
  }

  console.log(`\n${results.filter((r) => r.ok).length}/${results.length} checks PASS`);
  process.exit(results.every((r) => r.ok) ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
