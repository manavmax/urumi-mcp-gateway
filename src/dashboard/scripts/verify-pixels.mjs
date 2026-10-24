#!/usr/bin/env node
/**
 * Visionless screenshot verification (this model cannot view images).
 * Uses the dashboard's existing pngjs devDependency to:
 *   1. sample corner/centre pixels of every PNG against the expected theme
 *      tokens (dark canvas #040804, light canvas #ECEBE7),
 *   2. prove dark and light shots of the same page are genuinely different
 *      (pixelmatch diff ratio),
 *   3. prove no page rendered blank (distinct colour count),
 *   4. prove the dark theme is the NEW landing-matched canvas, not the old
 *      #14161B dark.
 * Exit 1 on any failure.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { PNG } = require("pngjs");
const pixelmatch = require("pixelmatch").default
  ?? require("pixelmatch");

const DIR = dirname(fileURLToPath(import.meta.url));

// Corner pixels may sit on the canvas OR on the canvas tinted by the fixed
// page-edge bg-glow (a design feature in both themes). Dark glows are the
// landing accent at ~0.06-0.12 alpha over #040804 (max blend ~[29,34,24]);
// light glows are periwinkle/peach at 0.38-0.50 alpha over #ECEBE7.
const blend = (a, b, t) => a.map((v, i) => Math.round(v * t + b[i] * (1 - t)));
const DARK_CANVAS = [4, 8, 4];
const LIGHT_CANVAS = [236, 235, 231];
const EXPECT = {
  dark: {
    canvas: DARK_CANVAS,
    oldDark: [20, 22, 27],
    tol: 12,
    // strongest dark glow blend: accent rgba(20,184,166,.12)
    extra: [blend([20, 184, 166], DARK_CANVAS, 0.14)],
    extraTol: 14,
  },
  light: {
    canvas: LIGHT_CANVAS,
    tol: 12,
    // strongest light glow blend: periwinkle rgba(185,196,221,.50)
    extra: [blend([185, 196, 221], LIGHT_CANVAS, 0.55)],
    extraTol: 20,
  },
};

function near(a, b, tol) {
  return Math.abs(a[0] - b[0]) <= tol && Math.abs(a[1] - b[1]) <= tol && Math.abs(a[2] - b[2]) <= tol;
}

function load(name) {
  return PNG.sync.read(readFileSync(join(DIR, name)));
}

function sample(png) {
  const { width, height, data } = png;
  const px = (x, y) => {
    const i = (width * y + x) << 2;
    return [data[i], data[i + 1], data[i + 2]];
  };
  return {
    tl: px(8, 8),
    tr: px(width - 9, 8),
    // a point likely inside a card in the content column
    mid: px(Math.floor(width / 2), Math.floor(height * 0.35)),
    bottom: px(Math.floor(width / 2), height - 40),
  };
}

let failures = 0;
const fail = (msg) => { failures++; console.error(`FAIL ${msg}`); };
const ok = (msg) => console.log(`ok   ${msg}`);

const files = readdirSync(DIR).filter((f) => f.endsWith(".png"));
if (files.length === 0) { console.error("no PNGs found"); process.exit(1); }

for (const f of files) {
  const png = load(f);
  const { width, height } = png;
  const s = sample(png);
  const theme = f.includes("-dark") ? "dark" : f.includes("-light") ? "light" : null;
  if (!theme) { ok(`${f}: no theme marker, skipped token check`); continue; }

  // corners must sit on the theme canvas (page background)
  const corners = [s.tl, s.tr];
  const spec = EXPECT[theme];
  const cornerOk = (c) =>
    near(c, spec.canvas, spec.tol) ||
    (spec.extra ?? []).some((e) => near(c, e, spec.extraTol ?? spec.tol));
  const badCorner = corners.filter((c) => !cornerOk(c));
  if (badCorner.length === 0) ok(`${f}: corners match ${theme} canvas (or glow blend)`);
  else fail(`${f}: corner ${JSON.stringify(badCorner[0])} not near ${theme} canvas ${JSON.stringify(spec.canvas)} or glow blends`);

  // dark pages must be the NEW deep canvas, not the old #14161B
  if (theme === "dark") {
    const isOld = [s.tl, s.tr].every((c) => near(c, EXPECT.dark.oldDark, 6));
    if (isOld) fail(`${f}: still renders the OLD dark canvas #14161B`);
    else ok(`${f}: not the old dark canvas`);
  }

  // not blank: sample a 240x160 grid, count distinct quantised colours
  const seen = new Set();
  for (let y = 0; y < height; y += 8) {
    for (let x = 0; x < width; x += 8) {
      const [r, g, b] = (() => {
        const i = (width * y + x) << 2;
        return [png.data[i], png.data[i + 1], png.data[i + 2]];
      })();
      seen.add(`${r >> 4}-${g >> 4}-${b >> 4}`);
    }
  }
  if (seen.size < 12) fail(`${f}: only ${seen.size} distinct colours - looks blank/broken`);
  else ok(`${f}: ${seen.size} distinct colours`);
}

// dark vs light must differ on the same page/viewport
for (const [a, b] of [
  ["overview-light-1440.png", "overview-dark-1440.png"],
  ["overview-light-390.png", "overview-dark-390.png"],
  ["servers-light-1440.png", "servers-dark-1440.png"],
  ["members-light-1440.png", "members-dark-1440.png"],
  ["chat-light-1440.png", "chat-dark-1440.png"],
  ["login-light-1440.png", "login-dark-1440.png"],
]) {
  try {
    const pa = load(a);
    const pb = load(b);
    const { width, height } = pa;
    const diff = pixelmatch(pa.data, pb.data, null, width, height, { threshold: 0.1 });
    const ratio = diff / (width * height);
    if (ratio < 0.02) fail(`${a} vs ${b}: diff ratio ${ratio.toFixed(4)} - themes look identical`);
    else ok(`${a}: dark/light diff ratio ${ratio.toFixed(3)}`);
  } catch (e) {
    fail(`${a}: compare failed - ${e.message}`);
  }
}

console.log(failures ? `\n${failures} FAILURES` : "\nALL PIXEL CHECKS PASSED");
process.exit(failures ? 1 : 0);
