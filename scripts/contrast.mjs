#!/usr/bin/env node
// F1 item 2 contrast gate: every page, admin AND member, BOTH themes.
// Part 1 of 3: imports, config, page table.
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import * as browserAuth from "./lib/browser-auth.mjs";
const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
const { PNG } = require("../src/dashboard/node_modules/pngjs");
const __dirname = dirname(fileURLToPath(import.meta.url));
const DASHBOARD_URL = process.env.DASHBOARD_URL || "http://dashboard.127.0.0.1.nip.io";
const VIEWPORT = { width: 1440, height: 900 };
const argv = process.argv.slice(2);
const onlyPage = (() => { const i = argv.indexOf("--page"); return i === -1 ? null : argv[i + 1]; })();
const onlyRole = (() => { const i = argv.indexOf("--role"); return i === -1 ? null : argv[i + 1]; })();
const PAGES = [
  { page: "login", path: "/", roles: ["anon"] },
  { page: "overview", path: "/overview?expanded=1", roles: ["admin", "member"] },
  { page: "servers", path: "/servers", roles: ["admin", "member"] },
  { page: "members", path: "/members", roles: ["admin", "member"] },
  { page: "audit", path: "/audit", roles: ["admin", "member"] },
  { page: "chat", path: "/chat", roles: ["admin", "member"] },
];
const THEMES = ["light", "dark"];
const HOVER_SELS = "tbody tr, .btn, .card, a, .chip, .seg button, .rail-item, .hist-item, .starter, .theme-btn, .theme-dot";

/* A real 1x1 PNG so the attach preview thumbnail renders actual bytes. */
function tinyPngBuffer() {
  const png = new PNG({ width: 1, height: 1 });
  png.data[0] = 76; png.data[1] = 92; png.data[2] = 111; png.data[3] = 255;
  return PNG.sync.write(png);
}
const TINY_PNG = tinyPngBuffer();

// Part 2 of 3: in-page evaluator source (stringified into evaluate calls).
const EVALUATOR = `
function __parse(c) {
  let m = /rgba?\\(\\s*([\\d.]+)[,\\s]+([\\d.]+)[,\\s]+([\\d.]+)(?:[,\\s/]+([\\d.]+))?/.exec(String(c || ""));
  if (m) return [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3]), m[4] == null || m[4] === "" ? 1 : parseFloat(m[4])];
  m = /^#([0-9a-f]{3,8})$/i.exec(String(c || "").trim());
  if (m) {
    let h = m[1];
    if (h.length === 3) h = h.split("").map((x) => x + x).join("");
    if (h.length === 6) return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16), 1];
  }
  return null;
}
function __lum(r, g, b) {
  const f = (c) => { const s = c / 255; return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function __ratio(a, b) {
  const x = __lum(a[0], a[1], a[2]), y = __lum(b[0], b[1], b[2]);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}
function __blend(fg, bg) {
  const a = fg[3];
  return [fg[0]*a + bg[0]*(1-a), fg[1]*a + bg[1]*(1-a), fg[2]*a + bg[2]*(1-a), 1];
}
function __stops(bg) {
  const cols = [];
  const re = /rgba?\\([^)]+\\)|#[0-9a-f]{3,8}/gi;
  let m;
  while ((m = re.exec(String(bg)))) { const p = __parse(m[0]); if (p) cols.push(p); }
  return cols;
}
function __bg(el) {
  // Nearest opaque ancestor background wins (matches painting order);
  // gradient stops on that same layer count as candidates, worst wins.
  let n = el;
  while (n && n !== document.documentElement) {
    const cs = getComputedStyle(n);
    const img = cs.backgroundImage || "";
    if (img && img !== "none") {
      const stops = __stops(img).map((s) => [s[0], s[1], s[2], 1]);
      if (stops.length) return stops;
    }
    const b = __parse(cs.backgroundColor);
    if (b && b[3] > 0.9) return [[b[0], b[1], b[2], 1]];
    n = n.parentElement;
  }
  const bb = __parse(getComputedStyle(document.body).backgroundColor);
  if (bb) return [[bb[0], bb[1], bb[2], 1]];
  return [[255, 255, 255, 1]];
}
function __vis(el) {
  const r = el.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return false;
  // Offscreen/collapsed rail labels report the page bg, not their own paint.
  if (r.left < -200 || r.top < -200) return false;
  if (r.left > (window.innerWidth || 1440) + 50) return false;
  // Content of a closed <details> is not painted (content-visibility: hidden)
  // and Chromium keeps stale computed colours there; not user-visible.
  const det = el.closest ? el.closest("details") : null;
  if (det && !det.open) return false;
  const cs = getComputedStyle(el);
  return cs.visibility !== "hidden" && cs.display !== "none" && parseFloat(cs.opacity || "1") > 0.05;
}
function __sel(el) {
  const parts = [];
  let n = el;
  for (let i = 0; i < 3 && n && n !== document.body; i++) {
    let s = n.tagName.toLowerCase();
    if (n.id) s += "#" + n.id;
    else if (n.className && typeof n.className === "string") s += "." + n.className.trim().split(/\\s+/).slice(0,2).join(".");
    parts.unshift(s);
    n = n.parentElement;
  }
  return parts.join(" > ");
}
function __evaluateVisible() {
  const failures = [];
  let checked = 0;
  const els = document.querySelectorAll("body *");
  for (const el of els) {
    if (!__vis(el)) continue;
    if (el.children.length > 0) continue;
    const text = (el.textContent || "").trim();
    if (!text) continue;
    const cs = getComputedStyle(el);
    const fg = __parse(cs.color);
    if (!fg) continue;
    const fs = parseFloat(cs.fontSize || "16");
    const fw = cs.fontWeight || "400";
    const large = fs >= 24 || (fs >= 18.66 && (fw === "700" || fw === "bold" || parseInt(fw) >= 700));
    const need = large ? 3.0 : 4.5;
    checked++;
    let worst = Infinity, wb = null;
    for (const b of __bg(el)) { const r = __ratio([fg[0],fg[1],fg[2]], b); if (r < worst) { worst = r; wb = b; } }
    if (worst < need) failures.push({ selector: __sel(el), ratio: worst.toFixed(2), fg: cs.color, bg: "rgb(" + wb.map(Math.round).join(",") + ")" });
  }
  for (const svg of document.querySelectorAll("svg")) {
    if (!__vis(svg)) continue;
    const cs = getComputedStyle(svg);
    const col = __parse(cs.color) || __parse(cs.stroke) || __parse(cs.fill);
    if (!col) continue;
    checked++;
    let worst = Infinity, wb = null;
    for (const b of __bg(svg)) { const r = __ratio([col[0],col[1],col[2]], b); if (r < worst) { worst = r; wb = b; } }
    if (worst < 3.0) failures.push({ selector: __sel(svg) + " svg", ratio: worst.toFixed(2), fg: cs.color, bg: "rgb(" + wb.map(Math.round).join(",") + ")" });
  }
  return { checked, failures };
}
return __evaluateVisible();
`;

// Part 3 of 3: runner over pages, roles, themes, states.
// D2.2: chat page WITH an image attached — preview thumbnail, remove button,
// drag-over state and the client-side rejection message, in both themes and
// both roles, at rest, hover and focus-visible. Zero failures required.
async function evaluateChatAttach(browser, role, theme, failures, counts, auth) {
  const ctx = await browser.newContext({ viewport: VIEWPORT, reducedMotion: "reduce" });
  try {
    if (role === "admin") await ctx.addCookies(browserAuth.cookiePair(auth.admin.cookie, DASHBOARD_URL));
    if (role === "member") {
      const m = await browserAuth.loginAs(DASHBOARD_URL, auth.member.email, auth.member.password);
      await ctx.addCookies(browserAuth.cookiePair(m.cookie, DASHBOARD_URL));
    }
    const page = await ctx.newPage();
    await page.goto(`${DASHBOARD_URL}/chat`, { waitUntil: "networkidle" });
    await page.waitForTimeout(500);
    await page.evaluate((t) => {
      try { localStorage.setItem("theme", t); } catch (e) { /* ignore */ }
      document.documentElement.setAttribute("data-theme", t);
    }, theme);
    await page.waitForTimeout(300);

    const seen = new Set();
    const push = (state, f) => {
      const k = `${state}|${f.selector}|${f.ratio}`;
      if (seen.has(k)) return;
      seen.add(k);
      failures.push(`chat-attach/${role}/${theme}/${state} ${f.selector} ${f.ratio} ${f.fg} on ${f.bg}`);
    };
    const evalState = async (state) => {
      const r = await page.evaluate(new Function(EVALUATOR));
      counts[`chat-attach/${role}/${theme}/${state}`] = (counts[`chat-attach/${role}/${theme}/${state}`] || 0) + r.checked;
      for (const f of r.failures) push(state, f);
    };

    // 1) Rest with the preview thumbnail + remove button visible.
    await page.setInputFiles(".composer input[type=file]", { name: "proof.png", mimeType: "image/png", buffer: TINY_PNG });
    await page.waitForSelector('.thread img[src^="blob:"]', { timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(300);
    await evalState("attach-rest");

    // D2.3: save the attached-image state for both themes (user inspects them).
    mkdirSync(join(__dirname, "..", "artifacts", "contrast"), { recursive: true });
    await page.screenshot({ path: join(__dirname, "..", "artifacts", "contrast", `chat-attach-${role}-${theme}.png`), animations: "disabled" });

    // 2) Hover the preview thumbnail, the remove button and the composer.
    const chip = await page.$(".thread .chip img[src^='blob:']");
    if (chip) {
      const removeBtn = await page.$('button[aria-label="Remove attached image"]');
      if (removeBtn) {
        const box = await removeBtn.boundingBox();
        if (box) {
          await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(200);
          await evalState("attach-hover-remove");
        }
      }
      const img = await page.$('.thread .chip img[src^="blob:"]');
      if (img) {
        const box = await img.boundingBox();
        if (box) {
          await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(200);
          await evalState("attach-hover-thumb");
        }
      }
      // Restore the pointer to a neutral spot so later focus state is clean.
      await page.mouse.move(720, 60);
    }

    // 3) Focus-visible on the remove button (keyboard focus, not mouse).
    const focusBtn = await page.$('button[aria-label="Remove attached image"]');
    if (focusBtn) {
      await focusBtn.focus();
      await page.waitForTimeout(150);
      await evalState("attach-focus-remove");
      await page.keyboard.press("Tab");
    }

    // 4) Drag-over state: dragover over the composer must surface the ring.
    await page.evaluate(() => {
      const form = document.querySelector(".composer");
      if (form) {
        const dt = new DataTransfer();
        form.dispatchEvent(new DragEvent("dragover", { bubbles: true, cancelable: true, dataTransfer: dt }));
      }
    });
    await page.waitForTimeout(200);
    await evalState("attach-dragover");

    // 5) Client-side rejection: an oversized PNG and a GIF must both show the
    //    inline alert-error and never create a preview.
    await page.evaluate(() => {
      const form = document.querySelector(".composer");
      if (form) {
        const dt = new DataTransfer();
        form.dispatchEvent(new DragEvent("dragleave", { bubbles: true, cancelable: true, dataTransfer: dt }));
      }
    });
    await page.setInputFiles(".composer input[type=file]", { name: "big.png", mimeType: "image/png", buffer: Buffer.concat([TINY_PNG, Buffer.alloc(5 * 1024 * 1024 + 1, 0)]) });
    await page.waitForTimeout(200);
    await evalState("attach-reject-oversize");
    await page.setInputFiles(".composer input[type=file]", { name: "anim.gif", mimeType: "image/gif", buffer: Buffer.from("GIF89a") });
    await page.waitForTimeout(200);
    await evalState("attach-reject-gif");
    await ctx.close();
  } finally {
    await ctx.close().catch(() => {});
  }
}

async function run() {
  const browser = await chromium.launch({ headless: true });
  const failures = [];
  const counts = {};
  let memberCleanup = null;
  const bump = (k, n) => { counts[k] = (counts[k] || 0) + n; };
  try {
    const admin = await browserAuth.adminLogin(DASHBOARD_URL);
    const created = await browserAuth.createThrowawayMember(DASHBOARD_URL, admin.cookie, admin.csrf, "contrast-");
    const member = await browserAuth.loginAs(DASHBOARD_URL, created.email, created.password);
    member.email = created.email; member.password = created.password;
    memberCleanup = async () => browserAuth.deleteMember(DASHBOARD_URL, admin.cookie, admin.csrf, created.id);
    for (const cfg of PAGES) {
      if (onlyPage && cfg.page !== onlyPage) continue;
      const roles = cfg.roles.filter((r) => !onlyRole || r === onlyRole);
      for (const role of roles) {
        const ctx = await browser.newContext({ viewport: VIEWPORT, reducedMotion: "reduce" });
        if (role === "admin") await ctx.addCookies(browserAuth.cookiePair(admin.cookie, DASHBOARD_URL));
        if (role === "member") {
          const m = await browserAuth.loginAs(DASHBOARD_URL, member.email, member.password);
          await ctx.addCookies(browserAuth.cookiePair(m.cookie, DASHBOARD_URL));
        }
        const page = await ctx.newPage();
        await page.goto(`${DASHBOARD_URL}${cfg.path}`, { waitUntil: "networkidle" });
        await page.waitForTimeout(600);
        for (const theme of THEMES) {
          const seen = new Set();
          const push = (state, f) => {
            const k = `${state}|${f.selector}|${f.ratio}`;
            if (seen.has(k)) return;
            seen.add(k);
            failures.push(`${cfg.page}/${role}/${theme}/${state} ${f.selector} ${f.ratio} ${f.fg} on ${f.bg}`);
          };
          await page.evaluate((t) => {
            try { localStorage.setItem("theme", t); } catch (e) { /* ignore */ }
            document.documentElement.setAttribute("data-theme", t);
          }, theme);
          await page.waitForTimeout(400);
          const rest = await page.evaluate(new Function(EVALUATOR));
          bump(`${cfg.page}/${role}/${theme}/rest`, rest.checked);
          for (const f of rest.failures) push("rest", f);
          const hoverables = await page.$$(HOVER_SELS);
          let hc = 0;
          for (const el of hoverables.slice(0, 60)) {
            try {
              await el.hover({ timeout: 1500 });
              await page.waitForTimeout(60);
              const r = await page.evaluate(new Function(EVALUATOR));
              hc += r.checked;
              for (const f of r.failures) push("hover", f);
            } catch (e) { /* detached: skip */ }
          }
          bump(`${cfg.page}/${role}/${theme}/hover`, hc);
          for (const sel of [".user-menu > button", ".topbar .icon-btn", "details.tools > summary", "details > summary"]) {
            for (const btn of await page.$$(sel)) {
              try {
                await btn.click({ timeout: 1500 });
                await page.waitForTimeout(120);
              } catch (e) { /* ignore */ }
            }
            const r = await page.evaluate(new Function(EVALUATOR));
            bump(`${cfg.page}/${role}/${theme}/overlay`, r.checked);
            for (const f of r.failures) push("overlay", f);
          }
          for (const btn of await page.$$(".user-menu > button, .topbar .icon-btn")) {
            try {
              await btn.click({ timeout: 2000 });
              await page.waitForTimeout(200);
              await page.keyboard.press("Escape");
              await page.waitForTimeout(120);
            } catch (e) { /* ignore */ }
          }
        }
        // Switch Light->Dark->Light->Dark without reload, re-run rest.
        for (const theme of ["light", "dark", "light", "dark"]) {
          await page.evaluate((t) => { document.documentElement.setAttribute("data-theme", t); }, theme);
          await page.waitForTimeout(250);
          const r = await page.evaluate(new Function(EVALUATOR));
          bump(`${cfg.page}/${role}/reswitch-${theme}`, r.checked);
          for (const f of r.failures) failures.push(`${cfg.page}/${role}/reswitch-${theme} ${f.selector} ${f.ratio} ${f.fg} on ${f.bg}`);
        }
        await ctx.close();
      }
    }

    // D2.2: the chat attach UI in both themes and both roles.
    if (!onlyPage || onlyPage === "chat") {
      for (const theme of THEMES) {
        await evaluateChatAttach(browser, "admin", theme, failures, counts, { admin, member });
        await evaluateChatAttach(browser, "member", theme, failures, counts, { admin, member });
      }
    }
  } finally {
    if (memberCleanup) await memberCleanup();
    await browser.close();
  }
  console.log("\n== contrast counts ==");
  for (const [k, v] of Object.entries(counts)) console.log(`  ${k}: ${v}`);
  if (failures.length) {
    console.error(`\n${failures.length} CONTRAST FAILURES (showing 200):`);
    for (const f of failures.slice(0, 200)) console.error(` - ${f}`);
    process.exit(1);
  }
  console.log("\nALL CONTRAST CHECKS PASSED");
}

run().catch((e) => { console.error(e); process.exit(1); });
