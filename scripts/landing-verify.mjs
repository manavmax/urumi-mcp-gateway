#!/usr/bin/env node
// Landing page verification (ADR-080/084/086). Run against the dockerised page:
//   docker build -t urumi/landing:0.2.0 src/landing
//   docker run -d --rm --name urumi-landing-test --user 101 \
//     --tmpfs /tmp:mode=1777 --tmpfs /var/cache/nginx:mode=1777 --tmpfs /var/run:mode=1777 \
//     -p 127.0.0.1:8090:8080 urumi/landing:0.2.0
//   LANDING_URL=http://127.0.0.1:8090 node scripts/landing-verify.mjs
//
// Gates, per docs/LANDING_DESIGN.md and the rebuild brief:
//   1. zero external requests (every request stays on the page origin)
//   2. zero console errors / page errors (CSP violations surface here)
//   3. no horizontal scroll at 375, 768, 1024 and 1440
//   4. AA text contrast on the key text elements in BOTH themes
//   5. sticky nav: stuck at the top and visually scrolled after 8px
//   6. prefers-reduced-motion: animations stop and final values appear
//   7. "Break it yourself": kill pod -> Unreachable while others answer, then
//      restarting -> Connected; disable removes tools; revoke gives 401;
//      issue new key clears it; reset restores everything
//   8. copy buttons put the expected text on the clipboard
//   9. budgets: total transfer under 350KB including fonts, JS under 40KB
//  10. screenshots 1440 + 390, light AND dark, into artifacts/landing/
//      and 6 hero frames 600ms apart into artifacts/landing/frames/
// Screenshots are gitignored (artifacts/). Reviewed by eye after the run.
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
const __dirname = dirname(fileURLToPath(import.meta.url));
const URL_BASE = process.env.LANDING_URL || "http://127.0.0.1:8090";
const OUT = join(__dirname, "..", "artifacts", "landing");
const FRAMES = join(OUT, "frames");
mkdirSync(OUT, { recursive: true });
mkdirSync(FRAMES, { recursive: true });

// In-page evaluator: WCAG ratio against the first OPAQUE ancestor background.
// SVG text is measured via fill. Elements inside role="img" SVG artwork are
// still checked here; the purely decorative footer wordmark is not.
const EVAL_SRC = `
function parse(c) {
  let m = /rgba?\\(\\s*([\\d.]+)[,\\s]+([\\d.]+)[,\\s]+([\\d.]+)(?:[,\\s/]+([\\d.]+))?/.exec(String(c || ""));
  if (m) return [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3]), m[4] == null || m[4] === "" ? 1 : parseFloat(m[4])];
  m = /^#([0-9a-f]{3,8})$/i.exec(String(c || "").trim());
  if (m) {
    let h = m[1];
    if (h.length === 3) h = h.split("").map(x => x + x).join("");
    if (h.length === 6) return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16), 1];
  }
  return null;
}
function lum(r, g, b) {
  const f = (c) => { const s = c / 255; return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function ratio(a, b) {
  const x = lum(a[0], a[1], a[2]), y = lum(b[0], b[1], b[2]);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}
function effBg(el) {
  let node = el;
  while (node) {
    const c = parse(getComputedStyle(node).backgroundColor);
    if (c && c[3] === 1) return c;
    node = node.parentElement;
  }
  return null;
}
window.__check = (sels) => sels.map((s) => {
  const el = document.querySelector(s);
  if (!el) return { sel: s, missing: true, pass: true };
  const cs = getComputedStyle(el);
  const isSvg = el instanceof SVGElement;
  const fg = parse(isSvg ? cs.fill : cs.color);
  if (!fg) return { sel: s, pass: true, note: "no color" };
  const bg = effBg(el) || [4, 8, 4, 1];
  const r = ratio(fg, bg);
  const px = parseFloat(cs.fontSize);
  const large = (parseFloat(cs.fontWeight) >= 700 && px >= 18.66) || px >= 24;
  const need = large ? 3 : 4.5;
  return { sel: s, ratio: Math.round(r * 100) / 100, need, pass: r >= need };
});
`;

const CONTRAST_SELECTS = [
  ".announce p", ".hero h1", ".lead", ".hero-note",
  ".term-title", ".term-text", ".term-call", ".term-answer", ".chip-sample",
  ".eyebrow", ".section-head p", ".card h3", ".card-lead", ".card-tag",
  ".feature-list li", ".step h3", ".step p", ".w-label", ".w-value", ".w-call",
  ".client-tab", ".snippet-title", ".code-block", ".tok-key", ".config-note",
  ".marks li", ".built-note",
  ".sim-name", ".status-ok", ".sim-server-tools li", ".tool-chips li",
  ".sim-count", ".sim-note", ".panel-title", ".panel-note",
  ".mock-table th", ".mock-table td", ".badge-ok", ".badge-err", ".badge-warn",
  ".stat-label", ".stat-num", ".chip-neutral",
  ".allow-card h3", ".mini h4", ".mini p",
  ".note-card p", ".note-card cite a", ".doc-tag", ".doc-card h3",
  ".btn-mono", ".footer h3", ".footer nav a", ".footer-project p", ".footer-base p",
  ".node-title", ".node-sub", ".edge-label", ".badge-num",
  // navigation pills and links, both themes (ADR-087: the nav was the bug report)
  ".nav .btn-primary", ".nav .btn-secondary", ".nav-links a", ".wordmark",
];

const WIDTHS = [
  { name: "desktop-dark", width: 1440, height: 900, theme: "dark", shots: true, full: true },
  { name: "mobile-dark", width: 390, height: 844, theme: "dark", shots: true },
  { name: "narrow-dark", width: 375, height: 812, theme: "dark", shots: false },
  { name: "tablet-dark", width: 768, height: 1024, theme: "dark", shots: false },
  { name: "laptop-dark", width: 1024, height: 768, theme: "dark", shots: false },
  { name: "desktop-light", width: 1440, height: 900, theme: "light", shots: true, full: true },
  { name: "mobile-light", width: 390, height: 844, theme: "light", shots: true },
];

let fail = 0;
const problems = (c, msg) => { console.log(`FAIL ${c}: ${msg}`); fail++; };
const browser = await chromium.launch();

async function newCase(c, extra = {}) {
  const ctx = await browser.newContext({
    viewport: { width: c.width, height: c.height },
    colorScheme: c.theme,
    ...extra,
  });
  await ctx.addInitScript((t) => {
    try { localStorage.setItem("landing-theme", t); } catch (e) {}
  }, c.theme);
  const page = await ctx.newPage();
  const requests = [];
  const consoleErrors = [];
  page.on("request", (r) => requests.push(r.url()));
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));
  await page.goto(URL_BASE, { waitUntil: "networkidle" });
  return { ctx, page, requests, consoleErrors };
}

function bytesOf(requests, suffix) {
  return requests.filter((u) => u.endsWith(suffix)).length; // unused helper kept out of gates
}
void bytesOf;

try {
  // ---------- per-width sweeps ----------
  for (const c of WIDTHS) {
    const { ctx, page, requests, consoleErrors } = await newCase(c);
    let caseFails = 0;

    const applied = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
    if (applied !== c.theme) { problems(c.name, `data-theme=${applied}, expected ${c.theme}`); caseFails++; }

    const external = requests.filter((u) => !u.startsWith(URL_BASE));
    if (external.length) { problems(c.name, `external requests: ${external.join(", ")}`); caseFails++; }
    if (consoleErrors.length) { problems(c.name, `console: ${consoleErrors.slice(0, 5).join(" | ")}`); caseFails++; }

    // no horizontal scroll; clip-aware overflow check (hidden/clip ancestors contain)
    const overflow = await page.evaluate(() => {
      const vw = document.documentElement.clientWidth;
      const sw = document.documentElement.scrollWidth;
      const wide = [];
      const contained = (el) => {
        for (let n = el; n && n !== document.body; n = n.parentElement) {
          const ox = getComputedStyle(n).overflowX;
          if (ox === "auto" || ox === "scroll" || ox === "hidden" || ox === "clip") return true;
        }
        return false;
      };
      document.querySelectorAll("body *").forEach((el) => {
        const b = el.getBoundingClientRect();
        if (b.width > 0 && b.right > vw + 1 && !contained(el)) wide.push(String(el.className || el.tagName) + "|" + Math.round(b.right));
      });
      return { vw, sw, wide: wide.slice(0, 6) };
    });
    if (overflow.sw > overflow.vw + 1 || overflow.wide.length) {
      problems(c.name, `scrollWidth ${overflow.sw} vs ${overflow.vw}; wide: ${overflow.wide.join(", ")}`);
      caseFails++;
    }

    // default config: beyond-brief and video stay hidden; claims wired
    const flags = await page.evaluate(() => ({
      beyond: document.getElementById("beyond").hidden,
      video: document.getElementById("video").hidden,
      gw: document.querySelector("[data-gateway-url]").textContent,
      bearer: document.querySelector("#pane-cursor code").textContent,
      catalog: document.querySelector("[data-store-catalog]").textContent,
      count: document.getElementById("simCount").textContent,
    }));
    if (!flags.beyond || !flags.video) { problems(c.name, `beyond/video visibility wrong: ${JSON.stringify(flags)}`); caseFails++; }
    if (!flags.gw.endsWith("/mcp") || flags.gw.includes("example.com") ||
        !(flags.gw.startsWith("http://dashboard.") || flags.gw.startsWith("https://dashboard."))) {
      problems(c.name, `gateway url wrong: ${flags.gw}`); caseFails++;
    }
    if (!flags.bearer.includes("Bearer <your-api-key>")) { problems(c.name, "Bearer placeholder not visible"); caseFails++; }
    if (flags.catalog !== "12-product") { problems(c.name, `store claim = "${flags.catalog}"`); caseFails++; }
    if (flags.count !== "13") { problems(c.name, `combined tool count = ${flags.count}, expected 13`); caseFails++; }

    // contrast gate on both screenshot themes
    if (c.shots) {
      const checked = await page.evaluate(`(() => { ${EVAL_SRC}; return window.__check(${JSON.stringify(CONTRAST_SELECTS)}); })()`);
      const bad = checked.filter((r) => !r.pass);
      if (bad.length) {
        problems(c.name + " contrast", bad.map((b) => `${b.sel} ${b.ratio}<${b.need}`).join(", "));
        caseFails++;
      }
      c._contrast = `${checked.filter((r) => r.pass).length}/${checked.length}`;
    }

    // nav sheet gate: never visible, never takes space, cannot open on desktop
    const navState = await page.evaluate(() => {
      const sheet = document.getElementById("navSheet");
      const cs = getComputedStyle(sheet);
      const nav = document.querySelector(".nav").getBoundingClientRect();
      const first = document.querySelector("main .hero").getBoundingClientRect();
      return {
        sheetDisplay: cs.display,
        sheetAttrHidden: sheet.hidden,
        sheetH: sheet.getBoundingClientRect().height,
        contentStartsUnderBar: Math.abs(first.top - nav.bottom) < 2,
        navH: Math.round(nav.height),
      };
    });
    if (navState.sheetDisplay !== "none" || !navState.sheetAttrHidden || navState.sheetH > 0) {
      problems(c.name, `nav sheet visible on load: ${JSON.stringify(navState)}`);
      caseFails++;
    }
    if (!navState.contentStartsUnderBar) {
      problems(c.name, `page content does not start under the bar: hero.top=${navState.contentStartsUnderBar}`);
      caseFails++;
    }
    if (c.width >= 900 && navState.navH !== 64) {
      problems(c.name, `desktop nav height ${navState.navH}, expected 64`);
      caseFails++;
    }

    // hero visibility gates (ADR-087): >=45% of the graphic visible at 1440x900;
    // headline, buttons and the hero card visible at 390
    if (c.name === "desktop-dark" || c.name === "desktop-light") {
      const vis = await page.evaluate(() => {
        const r = document.getElementById("heroVisual").getBoundingClientRect();
        return { top: r.top, h: r.height, visible: Math.max(0, window.innerHeight - r.top) / r.height };
      });
      if (vis.visible < 0.45) {
        problems(c.name, `hero graphic only ${(vis.visible * 100).toFixed(1)}% visible at load (top=${vis.top} h=${vis.h})`);
        caseFails++;
      }
    }
    if (c.name === "mobile-dark" || c.name === "mobile-light") {
      const mvis = await page.evaluate(() => ({
        actionsBottom: document.querySelector(".hero-actions").getBoundingClientRect().bottom,
        terminalTop: document.getElementById("terminal").getBoundingClientRect().top,
      }));
      if (mvis.actionsBottom > 844 || mvis.terminalTop > 844) {
        problems(c.name, `mobile hero: actions bottom=${mvis.actionsBottom}, terminal top=${mvis.terminalTop} (viewport 844)`);
        caseFails++;
      }
    }

    // sticky nav: stuck at top and visually scrolled while at 1600px
    await page.evaluate(() => window.scrollTo(0, 1600));
    await page.waitForTimeout(350);
    const sticky = await page.evaluate(() => {
      const h = document.querySelector(".nav");
      const r = h.getBoundingClientRect();
      return {
        top: r.top, pos: getComputedStyle(h).position,
        scrollY: window.scrollY, scrolled: h.classList.contains("scrolled"),
        bg: getComputedStyle(h).backgroundColor,
      };
    });
    if (sticky.scrollY > 0 && (sticky.pos !== "sticky" && sticky.pos !== "fixed" || Math.abs(sticky.top) > 1)) {
      problems(c.name, `nav not stuck: pos=${sticky.pos} top=${sticky.top}`);
      caseFails++;
    }
    if (!sticky.scrolled || sticky.bg === "rgba(0, 0, 0, 0)") {
      problems(c.name, `nav scrolled state wrong: scrolled=${sticky.scrolled} bg=${sticky.bg}`);
      caseFails++;
    }

    // dismissing the announcement bar must not break the sticky offset
    await page.evaluate(() => document.getElementById("announceClose").click());
    await page.evaluate(() => window.scrollTo(0, 2400));
    await page.waitForTimeout(250);
    const sticky2 = await page.evaluate(() => {
      const h = document.querySelector(".nav");
      const r = h.getBoundingClientRect();
      return { top: r.top, announceHidden: document.getElementById("announce").hidden, scrollY: window.scrollY };
    });
    if (!sticky2.announceHidden || (sticky2.scrollY > 0 && Math.abs(sticky2.top) > 1)) {
      problems(c.name, `sticky broken after announcement dismiss: ${JSON.stringify(sticky2)}`);
      caseFails++;
    }
    await page.evaluate(() => window.scrollTo(0, 0));

    // screenshots (reveal everything first: scroll through, settle, return)
    if (c.shots) {
      await page.evaluate(async () => {
        const step = window.innerHeight * 0.8;
        for (let y = 0; y <= document.body.scrollHeight; y += step) { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 60)); }
        window.scrollTo(0, 0);
      });
      await page.waitForTimeout(900);
      await page.screenshot({ path: join(OUT, `landing-${c.name}.png`), fullPage: !!c.full });
    }

    console.log(`${caseFails === 0 ? "OK" : "FAIL"} ${c.name}: theme=${applied} requests=${requests.length} external=${external.length}${c._contrast ? " contrast=" + c._contrast : ""} consoleErrors=${consoleErrors.length}`);
    fail += caseFails;
    await ctx.close();
  }

  // ---------- navigation: sheet routes, trap, lock, contrast (both themes) ----------
  for (const theme of ["dark", "light"]) {
    const c = { name: "nav-375-" + theme, width: 375, height: 812, theme };
    const { ctx, page } = await newCase(c);
    let caseFails = 0;
    const sheetClosed = async (label) => {
      await page.waitForTimeout(420);
      const st = await page.evaluate(() => {
        const sheet = document.getElementById("navSheet");
        return {
          attr: sheet.hidden,
          display: getComputedStyle(sheet).display,
          openClass: sheet.classList.contains("open"),
          expanded: document.getElementById("navToggle").getAttribute("aria-expanded"),
          lock: document.documentElement.classList.contains("nav-open"),
        };
      });
      if (!st.attr || st.display !== "none" || st.openClass || st.expanded !== "false" || st.lock) {
        problems(c.name, `sheet not closed via ${label}: ${JSON.stringify(st)}`);
        caseFails++;
      }
    };
    // open via the menu button
    await page.click("#navToggle");
    await page.waitForTimeout(450);
    const open = await page.evaluate(() => {
      const sheet = document.getElementById("navSheet");
      return {
        expanded: document.getElementById("navToggle").getAttribute("aria-expanded"),
        display: getComputedStyle(sheet).display,
        opacity: getComputedStyle(sheet).opacity,
        lock: document.documentElement.classList.contains("nav-open"),
        focusIn: sheet.contains(document.activeElement),
      };
    });
    if (open.expanded !== "true" || open.display === "none" || open.opacity !== "1" || !open.lock || !open.focusIn) {
      problems(c.name, `open state wrong: ${JSON.stringify(open)}`);
      caseFails++;
    }
    // body scroll is locked while open
    await page.evaluate(() => window.scrollTo(0, 300));
    const scrollY = await page.evaluate(() => window.scrollY);
    if (scrollY !== 0) { problems(c.name, `scroll lock failed: scrollY=${scrollY}`); caseFails++; }
    // contrast of the pills inside the OPEN sheet
    const sheetChecked = await page.evaluate(`(() => { ${EVAL_SRC}; return window.__check(${JSON.stringify([".nav-sheet-actions .btn-primary", ".nav-sheet-actions .btn-secondary", ".sheet-links a"])}); })()`);
    const badSheet = sheetChecked.filter((r) => !r.pass);
    if (badSheet.length) {
      problems(c.name + " contrast", "open sheet: " + badSheet.map((b) => `${b.sel} ${b.ratio}<${b.need}`).join(", "));
      caseFails++;
    }
    // focus trap: 12 tabs stay inside
    for (let i = 0; i < 12; i++) await page.keyboard.press("Tab");
    const trapOk = await page.evaluate(() => document.getElementById("navSheet").contains(document.activeElement));
    if (!trapOk) { problems(c.name, "focus escaped the sheet while tabbing"); caseFails++; }
    // close via Escape, focus returns to the menu button
    await page.keyboard.press("Escape");
    await sheetClosed("Escape");
    const focusBack = await page.evaluate(() => document.activeElement === document.getElementById("navToggle"));
    if (!focusBack) { problems(c.name, "focus did not return to the menu button"); caseFails++; }
    // close via the close button
    await page.click("#navToggle");
    await page.waitForTimeout(450);
    await page.click("#navSheetClose");
    await sheetClosed("close button");
    // close via choosing a link, which also scrolls to the section
    await page.click("#navToggle");
    await page.waitForTimeout(450);
    await page.click('.sheet-links a[href="#security"]');
    await page.waitForTimeout(700);
    await sheetClosed("link click");
    const sec = await page.evaluate(() => document.getElementById("security").getBoundingClientRect().top);
    if (Math.abs(sec) > 90) { problems(c.name, `sheet link did not scroll: #security top=${sec}`); caseFails++; }
    // close by resizing to desktop, where the sheet can never render
    await page.click("#navToggle");
    await page.waitForTimeout(450);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.waitForTimeout(250);
    const desktopState = await page.evaluate(() => ({
      attr: document.getElementById("navSheet").hidden,
      display: getComputedStyle(document.getElementById("navSheet")).display,
      lock: document.documentElement.classList.contains("nav-open"),
      menuBtnGone: document.getElementById("navToggle").offsetParent === null,
    }));
    if (!desktopState.attr || desktopState.display !== "none" || desktopState.lock || !desktopState.menuBtnGone) {
      problems(c.name, `resize to desktop did not close/hide: ${JSON.stringify(desktopState)}`);
      caseFails++;
    }
    console.log(`${caseFails === 0 ? "OK" : "FAIL"} ${c.name}: sheet routes, trap, lock, contrast ${sheetChecked.filter((r) => r.pass).length}/${sheetChecked.length}`);
    fail += caseFails;
    await ctx.close();
  }

  // ---------- scroll-spy: sliding highlight follows the section in view ----------
  {
    const c = { name: "nav-spy", width: 1440, height: 900, theme: "dark" };
    const { ctx, page } = await newCase(c);
    let caseFails = 0;
    await page.evaluate(() => document.getElementById("security").scrollIntoView({ behavior: "instant" }));
    await page.waitForTimeout(900);
    const s1 = await page.evaluate(() => {
      const active = document.querySelector(".nav-links a.active");
      const glide = document.getElementById("navGlide");
      const cs = getComputedStyle(glide);
      const link = document.querySelector('.nav-links a[data-spy="security"]');
      const m = /matrix\(\s*[^,]+,\s*[^,]+,\s*[^,]+,\s*[^,]+,\s*([^,]+)/.exec(cs.transform);
      return {
        active: active ? active.getAttribute("data-spy") : null,
        current: active ? active.getAttribute("aria-current") : null,
        glideW: parseFloat(glide.style.width),
        glideX: m ? Math.round(parseFloat(m[1])) : null,
        linkLeft: link.offsetLeft,
        glideOpacity: cs.opacity,
      };
    });
    if (s1.active !== "security" || s1.current !== "true" || !s1.glideW || s1.glideX === null ||
        Math.abs(s1.glideX - s1.linkLeft) > 2 || s1.glideOpacity !== "1") {
      problems(c.name, `security not highlighted: ${JSON.stringify(s1)}`);
      caseFails++;
    }
    await page.evaluate(() => document.getElementById("kubernetes").scrollIntoView({ behavior: "instant" }));
    await page.waitForTimeout(900);
    const s2 = await page.evaluate(() => {
      const active = document.querySelector(".nav-links a.active");
      return { active: active ? active.getAttribute("data-spy") : null };
    });
    if (s2.active !== "kubernetes") { problems(c.name, `kubernetes not highlighted: ${JSON.stringify(s2)}`); caseFails++; }
    console.log(`${caseFails === 0 ? "OK" : "FAIL"} nav-spy: security->${s1.active} kubernetes->${s2.active} glideX=${s1.glideX}`);
    fail += caseFails;
    await ctx.close();
  }

  // ---------- outbound links: one repo value, correct targets, main paths ----------
  {
    const c = { name: "links", width: 1440, height: 900, theme: "dark" };
    const { ctx, page } = await newCase(c);
    let caseFails = 0;
    const REPO = "https://github.com/manavmax/urumi-mcp-gateway";
    const links = await page.evaluate(() => {
      const out = [];
      document.querySelectorAll("a[href]").forEach((a) => {
        let abs;
        try { abs = new URL(a.getAttribute("href"), location.href).href; }
        catch (e) { abs = a.getAttribute("href"); } // e.g. subdomain-of-IP in the docker preview
        const target = a.getAttribute("target") || "";
        const rel = a.getAttribute("rel") || "";
        out.push({ href: abs, target, rel, text: a.textContent.trim().slice(0, 30) });
      });
      return out;
    });
    const distinct = [...new Map(links.map((l) => [l.href, l])).values()].sort((a, b) => a.href.localeCompare(b.href));
    console.log("distinct hrefs (" + distinct.length + "):");
    distinct.forEach((l) => console.log("  " + l.href));
    // every github.com href must use the one repo; no stale orgs or placeholders
    const gh = links.filter((l) => l.href.includes("github.com"));
    const badGh = gh.filter((l) => !l.href.startsWith(REPO));
    if (badGh.length) { problems(c.name, `non-repo github links: ${badGh.map((l) => l.href).join(", ")}`); caseFails++; }
    const stale = links.filter((l) => /urumi-ai|example\.com|your-org|blob\/landing/.test(l.href));
    if (stale.length) { problems(c.name, `stale/placeholder links: ${stale.map((l) => l.href).join(", ")}`); caseFails++; }
    // GitHub links open in a new tab with noopener; site links stay same-tab
    const badTarget = gh.filter((l) => !(l.target === "_blank" && /noopener/.test(l.rel) && /noreferrer/.test(l.rel)));
    const sameTab = links.filter((l) => /:\/\/dashboard\.|:\/\/store\./.test(l.href) && l.target === "_blank");
    if (badTarget.length) { problems(c.name, `github links missing target/rel: ${badTarget.map((l) => l.href).join(", ")}`); caseFails++; }
    if (sameTab.length) { problems(c.name, `site links must not open a new tab: ${sameTab.map((l) => l.href).join(", ")}`); caseFails++; }
    // dashboard and store hrefs derive from the page host in docker; the chart
    // injects value-built URLs in-cluster (checked via helm template below)
    const dash = links.filter((l) => /^https?:\/\/dashboard\./.test(l.href));
    const store = links.filter((l) => /^https?:\/\/store\./.test(l.href));
    if (!dash.length) { problems(c.name, "no dashboard links rendered"); caseFails++; }
    if (!store.length) { problems(c.name, "no store links rendered"); caseFails++; }
    // every /blob/main/<path> link must exist on the main branch
    const paths = [...new Set(gh.filter((l) => l.href.includes("/blob/main/")).map((l) => l.href.slice(REPO.length + "/blob/main/".length)))];
    console.log("blob/main paths (" + paths.length + "): " + paths.join(", "));
    const { execSync } = await import("node:child_process");
    const tree = new Set(execSync("git ls-tree -r main --name-only", { cwd: join(__dirname, ".."), encoding: "utf8" }).split("\n"));
    const missing = paths.filter((p) => !tree.has(p));
    if (missing.length) { problems(c.name, `blob/main paths missing on main: ${missing.join(", ")}`); caseFails++; }
    console.log(`${caseFails === 0 ? "OK" : "FAIL"} links: ${gh.length} github (${badGh.length} bad), ${dash.length} dashboard, ${store.length} store, ${paths.length} blob paths (${missing ? missing.length : 0} missing on main)`);
    fail += caseFails;
    await ctx.close();
  }

  // ---------- desktop-dark: budgets, clipboard, simulation, frames ----------
  {
    const c = { name: "desktop-dark-main", width: 1440, height: 900, theme: "dark" };
    const { ctx, page, requests, consoleErrors } = await newCase(c);
    await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: URL_BASE });

    // budgets from real response bodies
    let total = 0, js = 0, fonts = 0;
    for (const u of [...new Set(requests)]) {
      const res = await page.request.get(u);
      const size = (await res.body()).length;
      total += size;
      if (u.endsWith(".js")) js += size;
      if (u.endsWith(".woff2")) fonts += size;
    }
    console.log(`budgets: total=${total}B js=${js}B fonts=${fonts}B (limits 358400B / 40960B)`);
    if (total > 358400) { problems(c.name, `total transfer ${total}B > 350KB`); }
    if (js > 40960) { problems(c.name, `javascript ${js}B > 40KB`); }

    // copy buttons + tabs
    const gw = await page.evaluate(() => document.querySelector("[data-gateway-url]").textContent);
    async function clipOf(btnSel) {
      await page.click(btnSel);
      await page.waitForTimeout(120);
      return page.evaluate(() => navigator.clipboard.readText());
    }
    const clipCursor = await clipOf('.copy-btn[data-copy="cursor"]');
    if (clipCursor !== await page.evaluate(() => document.querySelector("#pane-cursor code").textContent)) {
      problems(c.name, "cursor copy text mismatch");
    }
    if (!clipCursor.includes(gw) || !clipCursor.includes("Bearer <your-api-key>")) {
      problems(c.name, `cursor copy missing url/placeholder: ${clipCursor.slice(0, 80)}`);
    }
    await page.click('.client-tab[data-tab="claude"]');
    await page.waitForTimeout(300);
    const claudeVisible = await page.evaluate(() => ({
      claude: !document.getElementById("pane-claude").hidden,
      cursor: document.getElementById("pane-cursor").hidden,
    }));
    if (!claudeVisible.claude || !claudeVisible.cursor) problems(c.name, "tab switch failed");
    const clipClaude = await clipOf('.copy-btn[data-copy="claude"]');
    if (!clipClaude.includes("claude mcp add") || !clipClaude.includes(gw)) problems(c.name, "claude copy wrong");
    const clipChip = await clipOf('#simCombined li[data-tool="woo__list_orders"]');
    if (clipChip !== "woo__list_orders") problems(c.name, `tool chip copy = "${clipChip}"`);
    if (consoleErrors.length) problems(c.name, `console: ${consoleErrors.slice(0, 3).join(" | ")}`);

    // ---- simulation ----
    const status = (srv) => page.evaluate((s) => {
      const card = document.querySelector(`.sim-server[data-server="${s}"]`);
      return { text: card.querySelector(".sim-status").textContent, dead: card.classList.contains("is-dead") };
    }, srv);
    const count = () => page.evaluate(() => document.getElementById("simCount").textContent);
    const logCount = (needle) => page.evaluate((n) => document.getElementById("simLog").textContent.split(n).length - 1, needle);

    await page.evaluate(() => document.getElementById("sim-section").scrollIntoView({ block: "center" }));
    await page.waitForTimeout(400);

    // kill pod on the selected server (woo)
    const okBefore = await logCount("200 ok");
    await page.click("#simKill");
    await page.waitForTimeout(900);
    let st = await status("woo");
    if (st.text !== "Unreachable" || !st.dead) problems(c.name, `kill pod: woo status "${st.text}"`);
    if ((await status("time")).text !== "Connected" || (await status("notes")).text !== "Connected") {
      problems(c.name, "kill pod: other servers disturbed");
    }
    await page.waitForTimeout(3200); // sample ticker runs meanwhile
    if ((await logCount("200 ok")) <= okBefore) problems(c.name, "kill pod: no new successful calls on the other servers");
    await page.waitForTimeout(2400); // t≈6.5s
    st = await status("woo");
    if (st.text !== "restarting…") problems(c.name, `kill pod: expected restarting, got "${st.text}"`);
    await page.waitForTimeout(3600); // t≈10s
    st = await status("woo");
    if (st.text !== "Connected" || st.dead) problems(c.name, `kill pod: expected recovery, got "${st.text}"`);

    // disable removes the tools of the selected server
    await page.click('.sim-server[data-server="time"]');
    await page.click("#simDisable");
    await page.waitForTimeout(500);
    const timeGone = await page.evaluate(() =>
      [...document.querySelectorAll('#simCombined li[data-tool^="time__"]')].every((li) => li.style.display === "none"));
    if (!timeGone) problems(c.name, "disable: time tools still listed");
    if ((await count()) !== "11") problems(c.name, `disable: count ${(await count())}, expected 11`);

    // revoke -> 401 on the next call; issue new key clears it
    await page.click("#simRevoke");
    await page.waitForTimeout(300);
    if (!(await page.evaluate(() => !document.getElementById("simIssue").hidden))) problems(c.name, "revoke: issue button not shown");
    await page.waitForTimeout(3000);
    if (!(await logCount("401 unauthorized"))) problems(c.name, "revoke: no 401 row appeared");
    await page.click("#simIssue");
    await page.waitForTimeout(200);
    if (!(await page.evaluate(() => document.getElementById("simIssue").hidden))) problems(c.name, "issue new key: button still shown");

    // reset restores everything
    await page.click("#simReset");
    await page.waitForTimeout(500);
    const reset = await page.evaluate(() => ({
      statuses: [...document.querySelectorAll(".sim-status")].map((s) => s.textContent),
      count: document.getElementById("simCount").textContent,
      wooVisible: [...document.querySelectorAll('#simCombined li[data-tool^="woo__"]')].every((li) => li.style.display !== "none"),
    }));
    if (reset.statuses.join(",") !== "Connected,Connected,Connected") problems(c.name, `reset statuses: ${reset.statuses}`);
    if (reset.count !== "13" || !reset.wooVisible) problems(c.name, `reset: count ${reset.count} wooVisible=${reset.wooVisible}`);

    // ---- hero frames live in their own tall context (see below) ----
    await ctx.close();
  }

  // ---------- hero frames: 6 frames, 600ms apart, tall viewport ----------
  {
    const c = { name: "hero-frames", width: 1440, height: 2200, theme: "dark" };
    const { ctx, page } = await newCase(c);
    const hero = await page.locator("#heroVisual").boundingBox();
    if (hero && hero.y + hero.height <= 2200) {
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(500);
      for (let i = 1; i <= 6; i++) {
        await page.screenshot({
          path: join(FRAMES, `hero-frame-${i}.png`),
          clip: { x: hero.x, y: hero.y, width: hero.width, height: hero.height },
        });
        if (i < 6) await page.waitForTimeout(600);
      }
      console.log(`frames: 6 hero frames saved (${Math.round(hero.width)}x${Math.round(hero.height)})`);
    } else {
      problems(c.name, `hero visual box unusable: ${JSON.stringify(hero)}`);
    }

    // packet visibility regression gate: packets must actually paint (the CSS
    // opacity:0 rule used to override the per-frame opacity attribute)
    let maxOp = 0, halos = 0, cores = 0;
    for (let i = 0; i < 6; i++) {
      const s = await page.evaluate(() => {
        let mx = 0, h = 0, c = 0;
        document.querySelectorAll("#hvPackets circle").forEach((el) => {
          const op = parseFloat(el.getAttribute("opacity") || "0");
          if (op > mx) mx = op;
          if (el.classList.contains("pkt-halo")) h++; else c++;
        });
        return { mx, h, c };
      });
      maxOp = Math.max(maxOp, s.mx); halos = s.h; cores = s.c;
      await page.waitForTimeout(300);
    }
    if (cores === 0 || maxOp < 0.5) { problems(c.name, `packets not painting: cores=${cores} maxOpacity=${maxOp}`); }
    if (halos !== cores) { problems(c.name, `packet halo trail missing: cores=${cores} halos=${halos}`); }

    // hero decor gates: planes subdued, dashed lines strong enough to see
    const decor = await page.evaluate(() => {
      const a = getComputedStyle(document.querySelector(".hv-plane-a rect")).opacity;
      const b = getComputedStyle(document.querySelector(".hv-plane-b rect")).opacity;
      const stroke = getComputedStyle(document.querySelector(".hv-path")).stroke;
      const m = /rgba?\([^)]*?,\s*([\d.]+)\)/.exec(stroke);
      return { a: parseFloat(a), b: parseFloat(b), strokeAlpha: m ? parseFloat(m[1]) : 0 };
    });
    if (decor.a > 0.35 || decor.b > 0.35) { problems(c.name, `planes too strong: ${JSON.stringify(decor)}`); }
    if (decor.strokeAlpha < 0.25) { problems(c.name, `hero lines too faint: strokeAlpha=${decor.strokeAlpha}`); }
    console.log(`hero decor: planeA=${decor.a} planeB=${decor.b} strokeAlpha=${decor.strokeAlpha} packets(maxOp=${maxOp.toFixed(2)}, cores=${cores}, halos=${halos})`);
    await ctx.close();
  }

  // ---------- reduced motion: animations stop, final values appear ----------
  {
    const failBefore = fail;
    const c = { name: "reduced-motion", width: 1440, height: 900, theme: "dark" };
    const { ctx, page, requests, consoleErrors } = await newCase(c, { reducedMotion: "reduce" });
    const external = requests.filter((u) => !u.startsWith(URL_BASE));
    if (external.length) problems(c.name, `external requests: ${external.join(", ")}`);
    if (consoleErrors.length) problems(c.name, `console: ${consoleErrors.slice(0, 3).join(" | ")}`);

    const rm = await page.evaluate(() => ({
      packets: getComputedStyle(document.querySelector(".hv-packets")).display,
      marquee: getComputedStyle(document.querySelector(".marks")).animationName,
      stat: document.querySelector(".stat-num[data-count]").textContent,
      termCall: getComputedStyle(document.querySelector("#termCall")).visibility,
      termAnswer: getComputedStyle(document.querySelector("#termAnswer")).visibility,
      lit: document.querySelectorAll("#tourWide .node.lit, #tourWide .dpath.lit").length,
      nodes: document.querySelectorAll("#tourWide .node").length + document.querySelectorAll("#tourWide .dpath").length,
      track: getComputedStyle(document.querySelector(".steps-track span")).transform,
      url: document.getElementById("typeUrl").textContent,
    }));
    if (rm.packets !== "none") problems(c.name, `packets visible under reduced motion (${rm.packets})`);
    if (rm.marquee !== "none") problems(c.name, `marquee still animating (${rm.marquee})`);
    if (!rm.stat.includes("4,812")) problems(c.name, `stat not at final value: "${rm.stat}"`);
    if (rm.termCall !== "visible" || rm.termAnswer !== "visible") problems(c.name, `terminal final values hidden: ${rm.termCall}/${rm.termAnswer}`);
    if (rm.lit < rm.nodes) problems(c.name, `diagram not fully lit: ${rm.lit}/${rm.nodes}`);
    if (rm.url === "") problems(c.name, "typing url widget empty under reduced motion");

    // sliding highlight: no animation under reduced motion, still positioned
    await page.evaluate(() => document.getElementById("security").scrollIntoView());
    await page.waitForTimeout(500);
    const rmSpy = await page.evaluate(() => {
      const g = document.getElementById("navGlide");
      const active = document.querySelector(".nav-links a.active");
      return {
        dur: getComputedStyle(g).transitionDuration,
        transform: getComputedStyle(g).transform,
        active: active ? active.getAttribute("data-spy") : null,
      };
    });
    if (!(parseFloat(rmSpy.dur) < 0.001)) problems(c.name, `glide transition not disabled: ${rmSpy.dur}`);
    if (rmSpy.active !== "security" || rmSpy.transform === "none") {
      problems(c.name, `glide not positioned without animation: ${JSON.stringify(rmSpy)}`);
    }
    console.log(`${fail === failBefore ? "OK" : "FAIL"} reduced-motion: packets=${rm.packets} marquee=${rm.marquee} stat="${rm.stat}" lit=${rm.lit}/${rm.nodes} glideDur=${rmSpy.dur}`);
    await ctx.close();
  }
} finally {
  await browser.close();
}

writeFileSync(join(OUT, "summary.json"), JSON.stringify({ ok: fail === 0 }, null, 2));
if (fail) { console.log(`LANDING VERIFY FAILED (${fail} problems)`); process.exit(1); }
console.log("LANDING VERIFY PASSED (screenshots in artifacts/landing, frames in artifacts/landing/frames)");
