// Colour-presence audit for band-figure QA clips: does each figure contain teal
// (accent), violet, warn and ink strokes as designed? Prints per-clip counts.
import { createRequire } from "node:module";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
const require = createRequire(import.meta.url);
const { chromium } = require("../src/dashboard/node_modules/playwright-core");
const DIR = "artifacts/landing/qa";
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
for (const f of readdirSync(DIR).filter((n) => n.startsWith("fig-") && n.endsWith(".png")).sort()) {
  const b64 = readFileSync(join(DIR, f)).toString("base64");
  const out = await page.evaluate(async (b64) => {
    const img = new Image();
    img.src = "data:image/png;base64," + b64;
    await img.decode();
    const w = img.naturalWidth, h = img.naturalHeight;
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const g = c.getContext("2d", { willReadFrequently: true });
    g.drawImage(img, 0, 0);
    const d = g.getImageData(0, 0, w, h).data;
    let teal = 0, violet = 0, warn = 0, ink = 0, bgish = 0, total = 0;
    for (let i = 0; i < d.length; i += 4) {
      const r = d[i], gg = d[i + 1], b = d[i + 2];
      total++;
      if (gg > r + 30 && gg > b - 40 && gg > 90) teal++;               // accent teal/green
      else if (b > r + 25 && b > gg + 15 && b > 120) violet++;        // purple/blue-violet
      else if (r > 200 && gg > 130 && gg < 215 && b < 130) warn++;    // amber
      else if (Math.abs(r - gg) < 24 && Math.abs(gg - b) < 24 && gg < 200) ink++; // grey strokes
      else bgish++;
    }
    return { w, h, teal, violet, warn, ink, bgish, total };
  }, b64);
  const pct = (n) => ((100 * n) / out.total).toFixed(2) + "%";
  console.log(f, `${out.w}x${out.h}`, "teal", pct(out.teal), "violet", pct(out.violet), "warn", pct(out.warn), "grey", pct(out.ink), "bg", pct(out.bgish));
}
await browser.close();
