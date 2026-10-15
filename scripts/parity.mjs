#!/usr/bin/env node
// STAGE 1 parity harness: approved mockups (design/mockups/*.html) vs the
// deployed dashboard, measured in a real browser.
//
//   node scripts/parity.mjs                 # every page, admin + member
//   node scripts/parity.mjs --page login    # one page
//   node scripts/parity.mjs --role member   # one role
//   node scripts/parity.mjs --pixel         # login pixel diff only
//
// Geometry tolerances (the STAGE 1 contract): 8px on width/height, 12px on
// x/y. Computed styles must match exactly (0.6px for numeric values). Elements
// whose height depends on live data are marked data-dependent and only compare
// the properties that cannot move with the data. Data-dependent rows are
// reported separately and never count as PASS/FAIL geometry failures.
//
// Login also gets a pixel diff (pixelmatch) under 3% at 1440x900 and 390x844
// with reduced motion emulated. The mockup's inline logo row is stacked before
// the diff because the STAGE 1 acceptance contract supersedes the mockup HTML
// there (documented in the report); every other deviation is listed in the
// report, not patched into the comparison.
//
// Uses playwright-core + pixelmatch + pngjs from the dashboard devDependencies.
// Never reads .env; the admin password comes from the gateway-admin Secret via
// kubectl or GATEWAY_ADMIN_PASSWORD.

import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
const pixelmatch = require("../src/dashboard/node_modules/pixelmatch");
const { PNG } = require("../src/dashboard/node_modules/pngjs");

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const MOCKUPS = join(ROOT, "design", "mockups");
const ARTIFACTS = join(ROOT, "artifacts", "parity");
const DASHBOARD_URL = process.env.DASHBOARD_URL || "http://dashboard.127.0.0.1.nip.io";
const VIEWPORT = { width: 1440, height: 900 };
const MOBILE_VIEWPORT = { width: 390, height: 844 };
const PIXEL_THRESHOLD = 0.03; // 3%

const TOL = { x: 12, y: 12, w: 8, h: 8, style: 0.6 };

/* ---------- selector maps: identical selectors resolve in mockup and live ---------- */
const GEOM = ["x", "y", "w", "h"];
const S = (sel, measure, extra = {}) => ({ sel, measure, ...extra });

const LOGIN_SELECTORS = [
  S(".stage", ["padding"]),
  S(".login-card", [...GEOM, "padding", "border-radius", "box-shadow", "background-color"]),
  S(".login-logo .mark-40", ["w", "h"]),
  S(".login-logo .wordmark", ["font-size", "font-weight", "color"]),
  S(".login-logo .sub", ["font-size", "font-weight", "color"]),
  S(".login-card h1", ["font-size", "font-weight", "color"]),
  S(".login-card .helper", ["font-size", "color"]),
  S(".field input", [...GEOM, "padding", "border-radius", "font-size"]),
  S(".btn-primary", [...GEOM, "padding", "border-radius", "background-color", "color", "font-weight"]),
  S(".foot", ["font-size", "color"]),
  S(".tagline", [...GEOM, "font-size", "font-weight"]),
  S(".shape.arch", [...GEOM, "opacity"]),
  S(".shape.drift-b", [...GEOM]),
  S(".shape.drift-c", [...GEOM]),
];

const OVERVIEW_SELECTORS = [
  S(".sidebar-pill", [...GEOM, "border-radius", "box-shadow", "background-color"]),
  S(".rail-item.active .rail-ic", ["w", "h", "background-color"]),
  S(".content", ["x", "w"]),
  S(".page-head h1", ["font-size", "font-weight", "color"]),
  S(".page-head .card-sub", ["font-size", "color"]),
  S(".head-actions .search", [...GEOM, "padding", "border-radius", "box-shadow"]),
  S(".search-go", ["w", "h", "border-radius", "background-color"]),
  S(".bento.row1", ["gap"]),
  S(".row1 .card", ["x", "w"], { dataDependent: true }),
  S(".stat.hero", ["x", "w", "padding", "border-radius", "background-image"], { dataDependent: true }),
  S(".stat-label", ["font-size", "font-weight", "color"]),
  S(".stat-num", ["font-size", "font-weight"], { dataDependent: true }),
  S(".chart-card", ["x", "w", "padding", "border-radius", "box-shadow"], { dataDependent: true }),
  S(".float-chip", ["padding", "border-radius", "box-shadow"]),
  S(".feed-row", ["padding"]),
  S(".chip", ["padding", "border-radius", "font-size", "font-weight"]),
  S(".chip-ok", ["background-color", "color"]),
  S(".chip-warn", ["background-color", "color"]),
  S(".chip-danger", ["background-color", "color"]),
  S(".chip-neutral", ["background-color", "color"]),
  S(".bento.row3", ["gap"]),
];

const FLEET_SELECTORS = [
  S(".topbar", [...GEOM, "padding"]),
  S(".topbar .search", [...GEOM, "padding", "border-radius", "box-shadow"]),
  S(".icon-btn", ["w", "h", "border-radius", "background-color"]),
  S(".user-menu > button", ["padding", "border-radius", "box-shadow"]),
  S(".content", ["x", "w"]),
  S(".page-head h1", ["font-size", "font-weight", "color"]),
  S(".content > section.card", ["x", "w", "padding", "border-radius", "box-shadow", "background-color"]),
  S(".card-head .card-title", ["font-size", "font-weight"]),
  S("th", ["font-size", "font-weight", "color", "padding"], { dataDependent: true }),
  S("td", ["padding"], { dataDependent: true }),
  /* status chips are state-dependent: real data may not include every state */
  S(".chip", ["padding", "border-radius", "font-size", "font-weight"], { dataDependent: true }),
  S(".chip-ok", ["background-color", "color"], { dataDependent: true }),
  S(".chip-warn", ["background-color", "color"], { dataDependent: true }),
  S(".chip-danger", ["background-color", "color"], { dataDependent: true }),
  S(".chip-neutral", ["background-color", "color"], { dataDependent: true }),
  S(".btn.btn-primary", ["padding", "border-radius", "background-color", "color", "font-weight"], { roles: ["admin"] }),
  S(".btn.btn-secondary", ["padding", "border-radius", "background-color", "color"], { roles: ["admin"] }),
  S(".src", ["font-size", "padding", "border-radius"]),
];

const CHAT_SELECTORS = [
  S(".chat-layout", ["gap"]),
  S(".thread", ["gap"]),
  S(".empty-state", ["padding"]),
  S(".empty-mark", ["w", "h", "border-radius", "background-color"]),
  S(".suggestion-grid", ["gap"]),
  S(".starter", ["padding", "border-radius", "box-shadow", "gap"]),
  S(".starter .tile", ["w", "h", "border-radius"]),
  S(".composer", ["padding", "border-radius", "box-shadow"]),
  S(".send", ["w", "h", "border-radius", "background-color"]),
  S(".history .card", ["padding"]),
  S(".hist-item", ["padding"]),
  S(".page-head h1", ["font-size", "font-weight", "color"]),
];

const PAGES = [
  {
    page: "login", mockup: "login.html", path: "/", selectors: LOGIN_SELECTORS,
    pixel: true, roles: ["anon"], liveNeedsAuth: false,
  },
  {
    page: "overview", mockup: "overview.html", path: "/overview", selectors: OVERVIEW_SELECTORS,
    roles: ["admin", "member"], structure: ["member"],
  },
  {
    page: "servers", mockup: "servers.html", path: "/servers", selectors: [
      ...FLEET_SELECTORS,
      S(".page-head .card-sub", ["font-size", "color"]),
      S(".note-banner", ["padding", "border-radius", "background-color"], { roles: ["member"] }),
      S(".switch .track", ["w", "h", "border-radius", "background-color"], { roles: ["admin"] }),
      S("details.tools > summary", ["padding", "border-radius", "font-size"], { dataDependent: true }),
      S(".slug", ["font-size", "font-weight"]),
      S(".url", ["font-size", "max-width"]),
    ],
    roles: ["admin", "member"],
  },
  {
    page: "members", mockup: "members.html", path: "/members", selectors: [
      ...FLEET_SELECTORS,
      /* the keys card is the last content card in both views (the users card is admin-only) */
      S(".content > section.card", ["x", "w", "padding", "border-radius", "box-shadow", "background-color"], { nth: -1 }),
      S(".note-banner", ["padding", "border-radius", "background-color"], { roles: ["member"] }),
      S(".grid-4", ["gap"]),
      S(".invite", ["padding", "border-radius", "background-color"], { roles: ["admin"] }),
      S(".invite .field input", ["padding", "border-radius", "font-size"], { roles: ["admin"] }),
      S(".stat-num", ["font-size", "font-weight"], { dataDependent: true }),
      S(".email", ["font-size", "font-weight"], { roles: ["admin"], dataDependent: true }),
      S(".mono-cell", ["font-size"], { dataDependent: true }),
    ],
    roles: ["admin", "member"],
  },
  {
    page: "audit", mockup: "audit.html", path: "/audit", selectors: [
      ...FLEET_SELECTORS,
      S(".page-head .card-sub", ["font-size", "color"]),
      S(".note-banner", ["padding", "border-radius", "background-color"]),
      S(".seg", ["padding", "border-radius"]),
      S(".filters .field input", ["padding", "border-radius", "font-size"], { dataDependent: true }),
      S(".filters .field label", ["font-size", "font-weight", "color"]),
      S(".tool-name", ["font-size", "font-weight"], { dataDependent: true }),
      S(".sub", ["font-size", "color"], { dataDependent: true }),
    ],
    roles: ["admin", "member"],
  },
  {
    page: "chat", mockup: "chat.html", path: "/chat", selectors: CHAT_SELECTORS,
    roles: ["admin", "member"],
  },
];

/* ---------- tiny CLI ---------- */
function argValue(name) {
  const i = process.argv.indexOf(`--${name}`);
  return i !== -1 ? process.argv[i + 1] : null;
}
const onlyPage = argValue("page");
const onlyRole = argValue("role");
const pixelOnly = process.argv.includes("--pixel");

/* ---------- auth helpers (mirrors scripts/screenshots.mjs) ---------- */
async function httpJson(url, { method = "GET", body, headers = {}, cookie } = {}) {
  const h = { "Content-Type": "application/json", ...headers };
  if (cookie) h["Cookie"] = cookie;
  const res = await fetch(url, { method, headers: h, body: body ? JSON.stringify(body) : undefined });
  const text = await res.text();
  let json = null;
  try { json = JSON.parse(text); } catch { /* not json */ }
  return { res, text, json, ok: res.ok, status: res.status, setCookie: res.headers.get("set-cookie") || "" };
}
function parseCookie(setCookieHeader) {
  return setCookieHeader.split(",").map((s) => s.split(";")[0].trim()).filter(Boolean).join("; ");
}
async function adminLogin() {
  let pass = process.env.GATEWAY_ADMIN_PASSWORD || "";
  let email = process.env.GATEWAY_ADMIN_EMAIL || "admin@urumi.local";
  if (!pass) {
    const { execSync } = await import("node:child_process");
    pass = execSync("kubectl get secret gateway-admin -n urumi -o jsonpath='{.data.password}' | base64 -d", { encoding: "utf8" }).trim();
  }
  const r = await httpJson(`${DASHBOARD_URL}/api/auth/login`, { method: "POST", body: { email, password: pass } });
  if (!r.ok) throw new Error(`admin login failed ${r.status} ${r.text.slice(0, 300)}`);
  return { cookie: parseCookie(r.setCookie), csrf: r.json?.csrf_token || "", email, pass };
}
async function createThrowawayMember(adminCookie, adminCsrf) {
  const { randomUUID } = await import("node:crypto");
  const email = `tmp-parity-${randomUUID().slice(0, 8)}@example.invalid`;
  const password = `Tmp-${randomUUID().slice(0, 12)}-a1!`;
  const r = await httpJson(`${DASHBOARD_URL}/api/users`, {
    method: "POST", body: { email, password, role: "member" },
    cookie: adminCookie, headers: { "X-CSRF-Token": adminCsrf },
  });
  if (!r.ok) throw new Error(`create member failed ${r.status} ${r.text.slice(0, 300)}`);
  return { email, password, id: r.json?.id };
}
async function deleteMember(adminCookie, adminCsrf, userId) {
  const r = await httpJson(`${DASHBOARD_URL}/api/users/${userId}`, {
    method: "DELETE", cookie: adminCookie, headers: { "X-CSRF-Token": adminCsrf },
  });
  if (!r.ok && r.status !== 204) console.error(`  ! delete member ${userId} -> ${r.status} ${r.text.slice(0, 200)}`);
}
async function loginAs(email, password) {
  const r = await httpJson(`${DASHBOARD_URL}/api/auth/login`, { method: "POST", body: { email, password } });
  if (!r.ok) throw new Error(`login ${email} failed ${r.status} ${r.text.slice(0, 300)}`);
  return parseCookie(r.setCookie);
}
function cookiePair(cookieHeader) {
  return cookieHeader.split(";").map((c) => {
    const [name, ...rest] = c.trim().split("=");
    return { name, value: rest.join("="), domain: new URL(DASHBOARD_URL).hostname, path: "/" };
  }).filter((c) => c.name && c.value);
}

/* ---------- in-page measurement ---------- */
/* A selector may appear in more than one list (shared fleet list + per-page
   override); the later, more specific entry wins so only one measurement per
   selector is taken and compared. */
function dedupeSpecs(selectors) {
  const out = [];
  for (const spec of selectors) {
    const i = out.findIndex((s) => s.sel === spec.sel);
    if (i !== -1) out[i] = spec;
    else out.push(spec);
  }
  return out;
}

async function measure(page, selectors) {
  return page.evaluate((sels) => {
    const out = [];
    for (const spec of sels) {
      const { sel, measure, dataDependent, nth } = spec;
      const all = Array.from(document.querySelectorAll(sel));
      const el = all.length === 0 ? null : nth === -1 ? all[all.length - 1] : all[0];
      if (!el) {
        out.push({ sel, missing: true, dataDependent: !!dataDependent });
        continue;
      }
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      const values = {};
      for (const prop of measure) {
        if (prop === "x") values.x = r.x;
        else if (prop === "y") values.y = r.y;
        else if (prop === "w") values.w = r.width;
        else if (prop === "h") values.h = r.height;
        else values[prop] = cs.getPropertyValue(prop).trim();
      }
      out.push({ sel, values, dataDependent: !!dataDependent });
    }
    return out;
  }, selectors);
}

function num(value) {
  if (typeof value === "number") return value;
  const m = /^(-?[\d.]+)px$/.exec(String(value).trim());
  return m ? parseFloat(m[1]) : null;
}
function compareValues(prop, mock, live) {
  if (mock === live) return { ok: true };
  const a = num(mock), b = num(live);
  if (a != null && b != null) return { ok: Math.abs(a - b) <= TOL.style, detail: `${mock} vs ${live}` };
  return { ok: false, detail: `${mock} vs ${live}` };
}

function comparePage(selectors, mockRow, liveRow) {
  const results = [];
  for (const spec of selectors) {
    if (spec.roles && !spec.roles.includes(currentRole)) continue;
    const m = mockRow.find((r) => r.sel === spec.sel);
    const l = liveRow.find((r) => r.sel === spec.sel);
    const mMissing = !m || m.missing;
    const lMissing = !l || l.missing;
    if (mMissing && lMissing) {
      // both sides agree the element is not rendered (e.g. no disabled key in real data)
      results.push({ sel: spec.sel, ok: true, detail: "absent in both", dataDependent: true });
      continue;
    }
    if (mMissing) { results.push({ sel: spec.sel, ok: false, detail: "present in live, absent in mockup", dataDependent: spec.dataDependent }); continue; }
    if (lMissing) {
      results.push({
        sel: spec.sel,
        ok: !!spec.dataDependent,
        detail: spec.dataDependent ? "absent in live (data/state dependent)" : "absent in live page",
        dataDependent: !!spec.dataDependent,
      });
      continue;
    }
    const fails = [];
    for (const prop of spec.measure) {
      const mv = m.values[prop], lv = l.values[prop];
      if (mv === undefined || lv === undefined) { fails.push(`${prop}: missing`); continue; }
      const tol = prop === "x" || prop === "y" ? TOL[prop] : prop === "w" || prop === "h" ? TOL[prop] : null;
      if (tol != null) {
        const a = num(mv), b = num(lv);
        if (a == null || b == null || Math.abs(a - b) > tol) fails.push(`${prop}: ${mv} vs ${lv} (tol ${tol})`);
      } else {
        const cmp = compareValues(prop, mv, lv);
        if (!cmp.ok) fails.push(`${prop}: ${cmp.detail}`);
      }
    }
    results.push({ sel: spec.sel, ok: fails.length === 0, detail: fails.join("; "), dataDependent: spec.dataDependent });
  }
  return results;
}

/* ---------- acceptance deviation, applied to the login mockup ----------
   The STAGE 1 acceptance contract supersedes the mockup HTML in exactly two
   places on the login page, and this function rewrites the in-browser mockup
   so both sides are compared on the contract:
   1. the logo block is STACKED (mark, wordmark, muted sub beneath, left
      aligned) instead of the mockup's inline row;
   2. the drift animation classes are named (.drift-b / .drift-c) so the same
   selectors resolve on both sides. Every other deviation is listed in the
   report, never patched into the comparison. */
async function alignLoginMockup(page) {
  await page.evaluate(() => {
    const card = document.querySelector(".login-card");
    const row = card?.querySelector(".row");
    if (row) {
      const logo = document.createElement("div");
      logo.className = "login-logo";
      logo.style.cssText = "display:grid;gap:10px;justify-items:start";
      const svg = row.querySelector("svg");
      if (svg) {
        const mark = document.createElement("span");
        mark.className = "mark-40";
        mark.style.cssText = "width:40px;height:40px;display:inline-flex";
        mark.appendChild(svg);
        logo.appendChild(mark);
      }
      const text = row.querySelector("div");
      if (text) {
        text.className = "wordmark";
        const sub = text.querySelector(".sub");
        if (sub) sub.style.cssText = "display:block;margin-top:6px;font-size:var(--t-sm);font-weight:500;color:var(--text-muted)";
        logo.appendChild(text);
      }
      row.replaceWith(logo);
    }
    const shapes = document.querySelectorAll("body > .shape");
    if (shapes[1]) shapes[1].classList.add("drift-b");
    if (shapes[2]) shapes[2].classList.add("drift-c");
  });
}

/* ---------- pixel diff ---------- */
async function pixelDiff(browser, mockupPath, liveUrl, viewport, label) {
  const mctx = await browser.newContext({ viewport, reducedMotion: "reduce" });
  const mpage = await mctx.newPage();
  await mpage.addStyleTag({ content: "::-webkit-scrollbar{display:none}" });
  await mpage.goto(`file://${mockupPath}?rm=1`, { waitUntil: "load" });
  await alignLoginMockup(mpage);
  await mpage.waitForTimeout(150);
  const mockShot = await mpage.screenshot({ animations: "disabled" });
  await mctx.close();

  const lctx = await browser.newContext({ viewport, reducedMotion: "reduce" });
  const lpage = await lctx.newPage();
  await lpage.addStyleTag({ content: "::-webkit-scrollbar{display:none}" });
  await lpage.goto(liveUrl, { waitUntil: "networkidle" });
  await lpage.waitForTimeout(150);
  const liveShot = await lpage.screenshot({ animations: "disabled" });
  await lctx.close();

  const a = PNG.sync.read(mockShot);
  const b = PNG.sync.read(liveShot);
  if (a.width !== b.width || a.height !== b.height) {
    return { label, ok: false, ratio: 1, note: `size mismatch ${a.width}x${a.height} vs ${b.width}x${b.height}` };
  }
  const diff = new PNG({ width: a.width, height: a.height });
  const changed = pixelmatch(a.data, b.data, diff.data, a.width, a.height, { threshold: 0.1 });
  const ratio = changed / (a.width * a.height);
  mkdirSync(ARTIFACTS, { recursive: true });
  const out = join(ARTIFACTS, `login-diff-${label}.png`);
  writeFileSync(out, PNG.sync.write(diff));
  return { label, ok: ratio < PIXEL_THRESHOLD, ratio, note: `${changed} px changed (${(ratio * 100).toFixed(2)}%), threshold ${(PIXEL_THRESHOLD * 100).toFixed(0)}%` };
}

/* ---------- member Overview structure checks (FIX 1) ----------
   The member Overview is a DISTINCT page with no approved mockup, so mockup
   geometry is not meaningful for it. Instead we assert structure + safety of
   the live page at desktop and mobile: every required card is present with
   non-zero size, no admin-only/team-wide text leaks in, and nothing overflows
   the viewport horizontally. */
const MEMBER_STRUCTURE = {
  required: [
    { sel: ".content .page-head h1", name: "greeting h1", min: 1 },
    { sel: '[aria-label="Getting started"]', name: "Getting started", min: 1 },
    { sel: '[aria-label="Connect your client"]', name: "Connect your client", min: 1 },
    { sel: '[aria-label="Connect your client"] .keybox', name: "MCP URL box", min: 1 },
    { sel: '[aria-label="My activity"] .card.stat', name: "My activity tiles", exact: 3 },
    { sel: '[aria-label="My calls per day"] svg[role="img"]', name: "Calls per day chart", min: 1 },
    { sel: '[aria-label="Recent activity"]', name: "Recent activity", min: 1 },
    { sel: ".starter", name: "Try in chat starters", exact: 3 },
  ],
  forbidden: ["fleet status", "fleet health", "get /api/users", "active accounts", "registered members", "team-wide", "team totals", "all servers"],
};

async function runStructureChecks(browser, liveUrl, role, member, admin) {
  let cookie = null;
  if (role === "member" && member) cookie = cookiePair(await loginAs(member.email, member.password));
  if (role === "admin" && admin) cookie = cookiePair(admin.cookie);

  const results = [];
  for (const vp of [VIEWPORT, MOBILE_VIEWPORT]) {
    const ctx = await browser.newContext({ viewport: vp, reducedMotion: "reduce" });
    if (cookie) await ctx.addCookies(cookie);
    const page = await ctx.newPage();
    await page.goto(liveUrl, { waitUntil: "networkidle" });
    await page.waitForTimeout(500);
    const m = await page.evaluate(({ required, forbidden }) => {
      const out = { present: [], forbidden: [], scrollWidth: 0, innerWidth: 0, overflowers: [] };
      for (const r of required) {
        const els = Array.from(document.querySelectorAll(r.sel));
        const sized = els.filter((e) => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0; });
        const inView = els.every((e) => e.getBoundingClientRect().right <= window.innerWidth + 2);
        out.present.push({ name: r.name, sel: r.sel, exact: r.exact ?? null, min: r.min, count: els.length, sized: sized.length, inView });
      }
      const text = (document.body.innerText || "").toLowerCase();
      out.forbidden = forbidden.filter((t) => text.includes(t));
      out.scrollWidth = document.documentElement.scrollWidth;
      out.innerWidth = window.innerWidth;
      out.overflowers = Array.from(document.querySelectorAll(".content *"))
        .filter((e) => e.getBoundingClientRect().right > window.innerWidth + 2)
        .map((e) => (typeof e.className === "string" && e.className) || e.tagName)
        .slice(0, 6);
      return out;
    }, { required: MEMBER_STRUCTURE.required, forbidden: MEMBER_STRUCTURE.forbidden });
    await ctx.close();

    for (const p of m.present) {
      const cntOk = p.exact != null ? p.count === p.exact : p.count >= p.min;
      const sizeOk = p.sized >= (p.exact != null ? p.exact : 1);
      results.push({ sel: `${p.sel}`, ok: cntOk && sizeOk && p.inView, detail: `${p.name}: ${p.count} el(s), sized ${p.sized}, inView=${p.inView}` });
    }
    results.push({ sel: "no admin-only text", ok: m.forbidden.length === 0, detail: m.forbidden.length ? `FOUND: ${m.forbidden.join(", ")}` : "none" });
    results.push({ sel: `no horizontal overflow @${vp.width}`, ok: m.scrollWidth <= m.innerWidth + 2, detail: `scrollWidth ${m.scrollWidth} / inner ${m.innerWidth}; over: ${m.overflowers.join(", ") || "none"}` });
  }
  return results;
}

/* ---------- main ---------- */
let currentRole = "admin";

async function run() {
  const browser = await chromium.launch({ headless: true });
  const failures = [];
  let admin = null;
  let member = null;
  let memberCleanup = null;

  const needAdmin = PAGES.some((p) => (!onlyPage || p.page === onlyPage) && p.roles?.includes("admin"));
  const needMember = PAGES.some((p) => (!onlyPage || p.page === onlyPage) && p.roles?.includes("member")) && (!onlyRole || onlyRole === "member");

  if (needAdmin) admin = await adminLogin();
  if (needMember) {
    member = await createThrowawayMember(admin.cookie, admin.csrf);
    memberCleanup = () => deleteMember(admin.cookie, admin.csrf, member.id);
    console.log(`parity member: ${member.email}`);
  }

  const report = [];
  try {
    if (!pixelOnly) for (const cfg of PAGES) {
      if (onlyPage && cfg.page !== onlyPage) continue;
      const roles = cfg.roles.filter((r) => !onlyRole || r === onlyRole);

      for (const role of roles) {
        currentRole = role;
        const liveUrl = `${DASHBOARD_URL}${cfg.path}?expanded=1`;

        /* member Overview is a distinct page: structure/safety checks, no mockup */
        if (cfg.structure && cfg.structure.includes(role)) {
          const results = await runStructureChecks(browser, liveUrl, role, member, admin);
          const hard = results.filter((r) => !r.ok);
          const status = hard.length === 0 ? "PASS" : "FAIL";
          console.log(`\n[${status}] ${cfg.page} (${role}) — ${results.filter((r) => r.ok).length}/${results.length} structure checks (distinct member page, no mockup)`);
          for (const r of results) console.log(`   ${r.ok ? "PASS" : "FAIL"} ${r.sel}: ${r.detail}`);
          if (hard.length) failures.push(`${cfg.page}/${role}: ${hard.length} structure check(s) FAIL`);
          report.push({ page: cfg.page, role, status, results });
          continue;
        }

        const specs = dedupeSpecs(cfg.selectors);
        const mockupQuery = cfg.mockup.startsWith("login") ? "" : role === "member" ? "?view=member&expanded=1" : "?expanded=1";
        const mockupUrl = `file://${join(MOCKUPS, cfg.mockup)}${mockupQuery}`;

        const mctx = await browser.newContext({ viewport: VIEWPORT });
        const mpage = await mctx.newPage();
        await mpage.goto(mockupUrl, { waitUntil: "load" });
        if (cfg.page === "login") {
          console.log("   (login: applied the STAGE 1 acceptance deviation to the mockup: stacked logo block, named drift classes)");
          await alignLoginMockup(mpage);
        }
        await mpage.waitForTimeout(250);
        const mockRows = await measure(mpage, specs);
        await mctx.close();

        const lctx = await browser.newContext({ viewport: VIEWPORT });
        if (role === "admin" && admin) await lctx.addCookies(cookiePair(admin.cookie));
        if (role === "member" && member) await lctx.addCookies(cookiePair(await loginAs(member.email, member.password)));
        const lpage = await lctx.newPage();
        await lpage.goto(liveUrl, { waitUntil: "networkidle" });
        await lpage.waitForTimeout(400);
        const liveRows = await measure(lpage, specs);
        await lctx.close();

        const results = comparePage(specs, mockRows, liveRows);
        const hard = results.filter((r) => !r.ok && !r.dataDependent);
        const soft = results.filter((r) => !r.ok && r.dataDependent);
        const status = hard.length === 0 ? "PASS" : "FAIL";
        console.log(`\n[${status}] ${cfg.page} (${role}) — ${results.length - hard.length - soft.length}/${results.length} measured elements match`);
        for (const r of results) {
          if (!r.ok && !r.dataDependent) console.log(`   FAIL ${r.sel}: ${r.detail}`);
          else if (!r.ok && r.dataDependent) console.log(`   data ${r.sel}: ${r.detail}`);
        }
        if (hard.length) failures.push(`${cfg.page}/${role}: ${hard.length} element(s) FAIL`);
        report.push({ page: cfg.page, role, status, results });
      }
    }

    /* login pixel diff (both viewports, reduced motion) */
    if (!onlyPage || onlyPage === "login") {
      const loginCfg = PAGES.find((p) => p.page === "login");
      const mockupPath = join(MOCKUPS, loginCfg.mockup);
      for (const [label, viewport] of [["desktop", VIEWPORT], ["mobile", MOBILE_VIEWPORT]]) {
        const r = await pixelDiff(browser, mockupPath, DASHBOARD_URL, viewport, label);
        console.log(`\n[${r.ok ? "PASS" : "FAIL"}] login pixel diff ${r.label}: ${r.note}`);
        if (!r.ok) failures.push(`login pixel diff ${r.label}: ${r.note}`);
        report.push({ page: "login-pixel", role: label, status: r.ok ? "PASS" : "FAIL", note: r.note });
      }
    }
  } finally {
    if (memberCleanup) await memberCleanup();
    await browser.close();
  }

  /* artifacts: one markdown table per page/role for the STAGE 1 report */
  mkdirSync(ARTIFACTS, { recursive: true });
  const lines = ["# STAGE 1 parity measurements (1440x900, admin + member)", ""];
  for (const r of report) {
    lines.push(`## ${r.page} (${r.role}) — ${r.status}`);
    if (r.note) lines.push(`- ${r.note}`);
    if (r.results) {
      lines.push("");
      lines.push("| element | result | detail |");
      lines.push("| --- | --- | --- |");
      for (const row of r.results) {
        const verdict = row.ok ? "PASS" : row.dataDependent ? "DATA" : "FAIL";
        lines.push(`| ${row.sel} | ${verdict} | ${row.detail || ""} |`);
      }      lines.push("");
    }
  }
  writeFileSync(join(ARTIFACTS, "parity-report.md"), lines.join("\n"));
  console.log(`\nwrote ${join(ROOT, "artifacts", "parity", "parity-report.md")}`);

  if (failures.length) {
    console.error(`\n${failures.length} FAILING group(s):`);
    for (const f of failures) console.error(` - ${f}`);
    process.exit(1);
  }
  console.log("\nALL PARITY CHECKS PASSED");
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
