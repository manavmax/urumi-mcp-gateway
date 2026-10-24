// Landing screenshot + pixel-audit pass (this branch only, not a gate).
// Produces: artifacts/landing/full/landing-<size>-<theme>-full.png (full page,
// 1440 and 390, dark and light) and artifacts/landing/clips/<size>-<theme>/<nn>-<id>.png
// (one clip per visible top-level section). Every PNG is then fed back through
// a canvas to measure painted content: per-clip content fraction and empty
// vertical runs on full pages (stand-in for eyeballing by a model that cannot
// see images). Run: node scripts/landing-shots.mjs
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
const __dirname = dirname(fileURLToPath(import.meta.url));
const URL_BASE = process.env.LANDING_URL || "http://127.0.0.1:8090";
const OUT = join(__dirname, "..", "artifacts", "landing");
mkdirSync(join(OUT, "full"), { recursive: true });
mkdirSync(join(OUT, "clips"), { recursive: true });
mkdirSync(join(OUT, "qa"), { recursive: true });

const browser = await chromium.launch();

// ---- capture ----
const produced = [];
for (const size of [{ name: "desktop", width: 1440, height: 900 }, { name: "mobile", width: 390, height: 844 }]) {
  for (const theme of ["dark", "light"]) {
    const ctx = await browser.newContext({ viewport: { width: size.width, height: size.height }, colorScheme: theme });
    await ctx.addInitScript((t) => { try { localStorage.setItem("landing-theme", t); } catch (e) {} }, theme);
    const page = await ctx.newPage();
    await page.goto(URL_BASE, { waitUntil: "networkidle" });
    await page.evaluate(() => document.fonts.ready);
    // reveal everything exactly like landing-verify does, with instant jumps
    // (smooth scroll-behavior would make the sweep lag and leave lower
    // sections unrevealed at capture time)
    await page.evaluate(async () => {
      const step = window.innerHeight * 0.8;
      for (let y = 0; y <= document.body.scrollHeight; y += step) { window.scrollTo({ top: y, behavior: "instant" }); await new Promise(r => setTimeout(r, 70)); }
      window.scrollTo({ top: 0, behavior: "instant" });
    });
    await page.waitForTimeout(900);
    const full = join(OUT, "full", `landing-${size.name}-${theme}-full.png`);
    await page.screenshot({ path: full, fullPage: true });
    produced.push(full);

    // one clip per visible top-level section (+ footer)
    const sections = await page.evaluate(() => {
      const els = [...document.querySelectorAll("main > section, main > .hero, footer")];
      return els.map((el, i) => ({
        i,
        id: el.id || el.className.split(" ")[0] || ("el" + i),
        visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
      }));
    });
    const dir = join(OUT, "clips", `${size.name}-${theme}`);
    mkdirSync(dir, { recursive: true });
    for (const s of sections) {
      if (!s.visible) continue;
      const loc = page.locator("main > section, footer").nth(s.i);
      const clip = join(dir, `${String(s.i).padStart(2, "0")}-${s.id}.png`);
      try { await loc.screenshot({ path: clip }); produced.push(clip); }
      catch (e) { console.log("clip failed:", s.id, e.message.split("\n")[0]); }
    }
    // QA clips of each VISIBLE band figure (did the graphic actually paint?)
    const figs = await page.locator(".fig-canvas").count();
    for (let i = 0; i < figs; i++) {
      const fig = page.locator(".fig-canvas").nth(i);
      if (!(await fig.isVisible())) continue;
      const fid = await fig.evaluate((el) => el.closest("figure")?.id || `fig${i}`);
      const clip = join(OUT, "qa", `fig-${fid}-${size.name}-${theme}.png`);
      try { await fig.screenshot({ path: clip }); produced.push(clip); }
      catch (e) { console.log("fig clip failed:", fid, e.message.split("\n")[0]); }
    }
    await ctx.close();
    console.log(`${size.name}-${theme}: full page + ${sections.filter(s => s.visible).length} clips + ${figs} fig clips`);
  }
}

// ---- pixel audit via canvas (no image libraries needed) ----
const auditCtx = await browser.newContext();
const auditPage = await auditCtx.newPage();
const audit = {};
for (const file of produced) {
  const b64 = readFileSync(file).toString("base64");
  audit[file] = await auditPage.evaluate(async (b64) => {
    const img = new Image();
    img.src = "data:image/png;base64," + b64;
    await img.decode();
    const w = img.naturalWidth, h = img.naturalHeight;
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const g = c.getContext("2d", { willReadFrequently: true });
    g.drawImage(img, 0, 0);
    const d = g.getImageData(0, 0, w, h).data;
    const lum = (i) => (0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2]);
    // background luminance per row: left edge (x=3) and right edge (x=w-4) median
    const band = 8;
    const emptyRuns = [];
    let runStart = null;
    for (let y0 = 0; y0 < h; y0 += band) {
      const yEnd = Math.min(h, y0 + band);
      let content = 0, total = 0;
      for (let y = y0; y < yEnd; y += 2) {
        const bgL = lum((y * w + 3) * 4), bgR = lum((y * w + w - 4) * 4);
        const bg = (bgL + bgR) / 2;
        for (let x = 0; x < w; x += 2) {
          total++;
          if (Math.abs(lum((y * w + x) * 4) - bg) > 9) content++;
        }
      }
      const frac = total ? content / total : 0;
      const empty = frac < 0.0015;
      if (empty && runStart === null) runStart = y0;
      if (!empty && runStart !== null) { if (y0 - runStart >= 450) emptyRuns.push([runStart, y0]); runStart = null; }
    }
    if (runStart !== null && h - runStart >= 450) emptyRuns.push([runStart, h]);
    return { w, h, emptyRuns };
  }, b64);
}
await auditCtx.close();
const report = {};
for (const [file, st] of Object.entries(audit)) report[file.replace(OUT + "/", "")] = st;
writeFileSync(join(OUT, "qa", "pixel-report.json"), JSON.stringify(report, null, 1));
for (const [f, st] of Object.entries(report)) {
  if (st.emptyRuns.length) console.log("EMPTY-RUNS", f, JSON.stringify(st.emptyRuns));
}
console.log("pixel audit written to artifacts/landing/qa/pixel-report.json;", produced.length, "images");
await browser.close();
