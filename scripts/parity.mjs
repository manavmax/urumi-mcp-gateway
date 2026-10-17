#!/usr/bin/env node
// STAGE 1 parity harness: approved mockups (design/mockups/*.html) vs the
// deployed dashboard, measured in a real browser.
//
//   node scripts/parity.mjs                 # every page, admin + member
//   node scripts/parity.mjs --page login    # one page
//   node scripts/parity.mjs --role member   # one role
//   node scripts/parity.mjs --pixel         # login pixel diff only
//   node scripts/parity.mjs --theme dark    # dark theme only (default: both)
//
// DARK MODE + MOTION PASS: the harness runs every page in BOTH themes (light
// + dark) and both roles. Light-mode geometry is the PASS/FAIL gate (layout
// parity with the approved design must remain PASS in light mode); dark mode
// gets geometry parity info (reported, not a gate), a WCAG contrast gate on
// the main text-on-surface pairs (>= 4.5:1, ratios reported), and a
// screenshot of every page in both themes and both roles under
// artifacts/parity/.
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
import * as browserAuth from "./lib/browser-auth.mjs";

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
const CONTRAST_MIN = 4.5;

/* CLI flags: --page, --role, --pixel, --theme light|dark (default both). */
const argv = process.argv.slice(2);
const themeFlag = (() => {
  const i = argv.indexOf("--theme");
  if (i === -1) return null;
  const v = argv[i + 1];
  return v === "light" || v === "dark" ? v : null;
})();
const THEMES = themeFlag ? [themeFlag] : ["light", "dark"];

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
  S(".btn.btn-secondary", ["padding", "border-radius", "background-color", "color"], { roles: ["admin"], dataDependent: true }),
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

/* ---------- auth helpers: shared with scripts/screenshots.mjs (Fix 4) ----------
   One login contract and one cookie-priming path for every dashboard script,
   so a renamed or extra session cookie cannot break one script only. */
const { loginAs, adminLogin, createThrowawayMember, deleteMember, cookiePair } = browserAuth;

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

/* ---------- contrast: WCAG text-on-surface pairs in dark mode ---------- */
function luminance(r, g, b) {
  const f = (c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function parseRgb(s) {
  const m = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/.exec(String(s || ""));
  if (!m) return null;
  return [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3])];
}
function contrastRatio(fg, bg) {
  const a = parseRgb(fg), b = parseRgb(bg);
  if (!a || !b) return null;
  const l1 = luminance(...a), l2 = luminance(...b);
  const hi = Math.max(l1, l2), lo = Math.min(l1, l2);
  return (hi + 0.05) / (lo + 0.05);
}

/* Main text-on-surface pairs: each entry resolves a text element + the
   surface behind it. Screenshots + ratios are reported; < 4.5:1 FAILs. */
const CONTRAST_PAIRS = [
  { name: "body text on card", textSel: ".card .card-title, .content .page-head h1", bgSel: ".card, .content" },
  { name: "muted on card", textSel: ".card .card-sub, .card .muted, .content .muted", bgSel: ".card, .content" },
  { name: "primary pill text", textSel: ".btn-primary", bgSel: ".btn-primary" },
  { name: "chip text", textSel: ".chip", bgSel: ".chip" },
  { name: "input text", textSel: ".field input, .search input, .composer input", bgSel: ".field input, .search input, .composer input" },
  { name: "table cell text", textSel: "td", bgSel: ".card, .content" },
  { name: "chat bubble text", textSel: ".msg .bubble, .thread-card", bgSel: ".msg .bubble, .thread-card, .card" },
];

async function checkContrast(page, theme) {
  return page.evaluate((pairs) => {
    function bgOf(el) {
      let n = el;
      while (n && n !== document.documentElement) {
        const bg = getComputedStyle(n).backgroundColor;
        const m = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?/.exec(bg || "");
        if (m) {
          const a = m[4] == null || m[4] === "" ? 1 : parseFloat(m[4]);
          if (a > 0.9) return bg;
        }
        n = n.parentElement;
      }
      return getComputedStyle(document.body).backgroundColor;
    }
    const out = [];
    for (const p of pairs) {
      const el = document.querySelector(p.textSel);
      if (!el) { out.push({ name: p.name, ok: true, detail: "absent in page", ratio: null }); continue; }
      const fg = getComputedStyle(el).color;
      const bg = bgOf(el);
      out.push({ name: p.name, fg, bg, sel: p.textSel });
    }
    return out;
  }, CONTRAST_PAIRS);
}

/* Screenshot every page in both themes and both roles. */
/* ---------- member Overview structure checks (FIX 1) ----------
   The motion proof lives in scripts/verify-motion.mjs (stat sampled at 100ms
   and 1s ends on the API value; reduced motion shows final at 0ms; no
   console errors).
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

async function runStructureChecks(browser, liveUrl, role, member, admin, theme = "light") {
  let cookie = null;
  if (role === "member" && member) {
    const m = await loginAs(DASHBOARD_URL, member.email, member.password);
    cookie = cookiePair(m.cookie, DASHBOARD_URL);
  }
  if (role === "admin" && admin) cookie = cookiePair(admin.cookie, DASHBOARD_URL);

  const results = [];
  for (const vp of [VIEWPORT, MOBILE_VIEWPORT]) {
    const ctx = await browser.newContext({ viewport: vp, reducedMotion: "reduce" });
    if (cookie) await ctx.addCookies(cookie);
    const page = await ctx.newPage();
    await page.goto(liveUrl, { waitUntil: "networkidle" });
    await page.evaluate((t) => {
      try { localStorage.setItem("theme", t); } catch { /* ignore */ }
      document.documentElement.setAttribute("data-theme", t);
    }, theme);
    await page.waitForTimeout(500);
    mkdirSync(ARTIFACTS, { recursive: true });
    await page.screenshot({ path: join(ARTIFACTS, `page-overview-${role}-${theme}-${vp.width}.png`), animations: "disabled" });
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

  if (needAdmin) admin = await adminLogin(DASHBOARD_URL);
  if (needMember) {
    member = await createThrowawayMember(DASHBOARD_URL, admin.cookie, admin.csrf, "tmp-parity-");
    memberCleanup = () => deleteMember(DASHBOARD_URL, admin.cookie, admin.csrf, member.id);
    console.log(`parity member: ${member.email}`);
  }

  const report = [];
  try {
    if (!pixelOnly) for (const cfg of PAGES) {
      if (onlyPage && cfg.page !== onlyPage) continue;
      const roles = cfg.roles.filter((r) => !onlyRole || r === onlyRole);

      for (const role of roles) {
        for (const theme of THEMES) {
          currentRole = role;
          const liveUrl = `${DASHBOARD_URL}${cfg.path}?expanded=1`;
          const tag = `${cfg.page}/${role}/${theme}`;

          /* member Overview is a distinct page: structure/safety checks, no mockup.
             Light mode is the gate; dark mode structure is reported alongside. */
          if (cfg.structure && cfg.structure.includes(role)) {
            const results = await runStructureChecks(browser, liveUrl, role, member, admin, theme);
            const hard = results.filter((r) => !r.ok);
            const gate = theme === "light";
            const status = hard.length === 0 ? "PASS" : gate ? "FAIL" : "INFO";
            console.log(`\n[${status}] ${cfg.page} (${role}, ${theme}) — ${results.filter((r) => r.ok).length}/${results.length} structure checks (distinct member page, no mockup)`);
            for (const r of results) console.log(`   ${r.ok ? "PASS" : "FAIL"} ${r.sel}: ${r.detail}`);
            if (gate && hard.length) failures.push(`${tag}: ${hard.length} structure check(s) FAIL`);
            report.push({ page: `${cfg.page}[${theme}]`, role, status, results });
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
          if (role === "admin" && admin) await lctx.addCookies(cookiePair(admin.cookie, DASHBOARD_URL));
          if (role === "member" && member) {
            const m = await loginAs(DASHBOARD_URL, member.email, member.password);
            await lctx.addCookies(cookiePair(m.cookie, DASHBOARD_URL));
          }
          const lpage = await lctx.newPage();
          await lpage.goto(liveUrl, { waitUntil: "networkidle" });
          /* force the theme under test (default System would follow the
             headless browser's media, not the theme we want to measure) */
          await lpage.evaluate((t) => {
            try { localStorage.setItem("theme", t); } catch { /* ignore */ }
            document.documentElement.setAttribute("data-theme", t);
          }, theme);
          await lpage.waitForTimeout(400);
          const liveRows = await measure(lpage, specs);

          /* screenshot every page in both themes and both roles */
          mkdirSync(ARTIFACTS, { recursive: true });
          const shotName = `page-${cfg.page}-${role}-${theme}.png`;
          await lpage.screenshot({ path: join(ARTIFACTS, shotName), animations: "disabled" });
          console.log(`   screenshot: artifacts/parity/${shotName}`);

          /* contrast gate on the main text-on-surface pairs (dark only) */
          if (theme === "dark") {
            const pairs = await checkContrast(lpage, theme);
            for (const p of pairs) {
              if (p.ratio === null && !p.fg) {
                report.push({ page: `contrast-dark[${cfg.page}/${role}]`, role, status: "PASS", note: `${p.name}: absent in page` });
                console.log(`   PASS contrast ${p.name}: absent in page`);
                continue;
              }
              const ratio = contrastRatio(p.fg, p.bg);
              const ok = ratio != null && ratio >= CONTRAST_MIN;
              const note = `${p.name}: ${ratio == null ? "unmeasurable" : ratio.toFixed(2) + ":1"} (fg ${p.fg} on ${p.bg})`;
              console.log(`   [${ok ? "PASS" : "FAIL"}] contrast ${note}`);
              report.push({ page: `contrast-dark[${cfg.page}/${role}]`, role, status: ok ? "PASS" : "FAIL", note });
              if (!ok) failures.push(`${tag} contrast: ${note}`);
            }
          }
          await lctx.close();

          const results = comparePage(specs, mockRows, liveRows);
          const hard = results.filter((r) => !r.ok && !r.dataDependent);
          const soft = results.filter((r) => !r.ok && r.dataDependent);
          /* light mode geometry is the PASS/FAIL gate; dark mode is INFO
             (same layout, different palette) so palette diffs never fail parity */
          const gate = theme === "light";
          const status = hard.length === 0 ? "PASS" : gate ? "FAIL" : "INFO";
          console.log(`\n[${status}] ${cfg.page} (${role}, ${theme}) — ${results.length - hard.length - soft.length}/${results.length} measured elements match`);
          for (const r of results) {
            if (!r.ok && !r.dataDependent) console.log(`   FAIL ${r.sel}: ${r.detail}`);
            else if (!r.ok && r.dataDependent) console.log(`   data ${r.sel}: ${r.detail}`);
          }
          if (gate && hard.length) failures.push(`${tag}: ${hard.length} element(s) FAIL`);
          report.push({ page: `${cfg.page}[${theme}]`, role, status, results });
        }
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
