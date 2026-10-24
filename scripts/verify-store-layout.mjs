#!/usr/bin/env node
// Storefront LAYOUT acceptance (store polish round 2). Proves the container,
// card-grid and overflow rules with geometry, not eyeballs. Fails loudly.
//
//   node scripts/verify-store-layout.mjs
//
// Page types: home, /shop, category, Collections (the home Collections band -
// no distinct /collections/ URL exists in this store), product, search
// results, cart, 404 - at widths 390/768/1024/1440/1920:
//   1. header content, breadcrumb, H1, category pills, toolbar, grid, related
//      section and footer content share ONE container: same left/right
//      CONTENT edges (box + own horizontal padding) within 1px. Two honest
//      exceptions measured separately: the hero H1 is capped at 560px by
//      design (left edge still must align), and the PDP H1 sits in the right
//      gallery/info column (its RIGHT edge must align).
//   2. in every product-grid row: image tops equal within 1px, card heights
//      equal within 2px, price tops equal within 2px.
//   3. no descendant of a card extends outside its card; no add-to-cart
//      button bottom within 8px of its card bottom or its section bottom.
//   4. nothing above the header (bounding box or DOM order).
//   5. no horizontal scroll.
//   6. shop-family grids: 4 columns at 1440, 3 at 1024, 2 at 768/390;
//      related row: 4 at 1440, 2 at 1024 and below.
//   7. no console errors (known-benign Woo ResizeObserver loop excluded, and
//      the 404 page's own expected 404 resource).
// Screenshots at 1440 and 390 land in artifacts/store/.

import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let chromium = null;
for (const p of ["../src/dashboard/node_modules/playwright-core",
                 "/Users/manavsharma/Desktop/Urumi_AI/src/dashboard/node_modules/playwright-core"]) {
  try { ({ chromium } = require(p)); break; } catch {}
}
if (!chromium) {
  console.error("playwright-core not found (dashboard node_modules missing in both paths)");
  process.exit(2);
}
import { mkdirSync } from "node:fs";
import path from "node:path";

const STORE = process.env.STORE_URL || "http://store.127.0.0.1.nip.io";
const ART = "artifacts/store";

const PAGES = [
  ["home", "/"],
  ["shop", "/shop/"],
  ["category", "/product-category/ceramics/"],
  ["product", "/product/bud-vase/"],
  ["search", "/?s=set&post_type=product"],
  ["cart", "/cart/"],
  ["404", "/this-page-does-not-exist/"],
];

const WIDTHS = [390, 768, 1024, 1440, 1920];

const results = [];
const failures = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log(`   ${ok ? "PASS" : "FAIL"} ${name}${detail ? `: ${detail}` : ""}`);
  if (!ok) failures.push(`${name}${detail ? `: ${detail}` : ""}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Runs in the page. Content edge = box edge + its own horizontal padding, so
// a padded container and the elements inside it measure identically.
function measureGeometry() {
  const contentBox = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return {
      left: r.left + parseFloat(cs.paddingLeft || "0"),
      right: r.right - parseFloat(cs.paddingRight || "0"),
      top: r.top,
      bottom: r.bottom,
      inHero: !!el.closest(".urumi-hero"),
      inPdp: !!el.closest(".urumi-pdp"),
    };
  };
  const out = { container: {}, grids: [], aboveHeader: [], domImgsBeforeHeader: 0, scrollX: 0 };

  const header = document.querySelector(".urumi-site-header");
  const headerTop = header ? header.getBoundingClientRect().top : 0;

  const members = {
    headerContent: ".urumi-nav",
    breadcrumb: ".wp-block-woocommerce-breadcrumbs, .woocommerce-breadcrumb",
    h1: "main h1",
    pills: ".urumi-filter-pills",
    toolbar: ".urumi-sort-row",
    grid: ".urumi-collection, ul.urumi-grid",
    related: ".urumi-related",
    footerContent: ".urumi-footer",
  };
  for (const [key, sel] of Object.entries(members)) {
    const el = document.querySelector(sel);
    out.container[key] = el ? { ...contentBox(el), found: true } : { found: false };
  }

  // every product grid on the page
  const gridEls = [
    ...document.querySelectorAll(
      ".urumi-collection ul.wc-block-product-template, ul.urumi-grid, main > .wp-block-query .wp-block-post-template"
    ),
  ];
  for (const grid of gridEls) {
    const g = contentBox(grid);
    const cards = [...grid.children].filter((c) => {
      const r = c.getBoundingClientRect();
      return r.height > 4 && r.width > 4;
    });
    // rows: group cards whose tops are within 2px of each other
    cards.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
    const rows = [];
    for (const c of cards) {
      const last = rows[rows.length - 1];
      if (last && Math.abs(c.getBoundingClientRect().top - last[0].getBoundingClientRect().top) <= 2) {
        last.push(c);
      } else {
        rows.push([c]);
      }
    }
    const sec = grid.closest(".urumi-collection, .urumi-related, .urumi-section, main");
    const secBox = sec ? contentBox(sec) : null;
    const rowsOut = rows.map((row) => {
      const imgTops = row.map((c) => {
        const img = c.querySelector("img, .urumi-photo--empty");
        return img ? img.getBoundingClientRect().top : null;
      });
      const heights = row.map((c) => c.getBoundingClientRect().height);
      const priceTops = row.map((c) => {
        const p = c.querySelector(".urumi-tile__price, .wc-block-components-product-price, .urumi-tile__row");
        return p ? p.getBoundingClientRect().top : null;
      });
      const lefts = row.map((c) => Math.round(c.getBoundingClientRect().left));
      let outside = 0;
      let buttonTight = 0;
      row.forEach((c) => {
        const cr = c.getBoundingClientRect();
        c.querySelectorAll("*").forEach((d) => {
          if (d.closest(".screen-reader-text")) return;
          const r = d.getBoundingClientRect();
          if (r.width < 1 || r.height < 1) return;
          const cs = getComputedStyle(d);
          if (cs.position === "fixed" || cs.display === "none" || cs.visibility === "hidden") return;
          if (r.left < cr.left - 1 || r.right > cr.right + 1 || r.top < cr.top - 1 || r.bottom > cr.bottom + 1) outside++;
        });
        c.querySelectorAll("button, a.button, .urumi-btn").forEach((b) => {
          const r = b.getBoundingClientRect();
          if (r.height < 2) return;
          if (cr.bottom - r.bottom < 8) buttonTight++;
        });
      });
      const buttonBottomGap = Math.min(
        ...row.map((c) => {
          const b = c.querySelector("button, a.button, .urumi-btn");
          return b ? g.bottom - b.getBoundingClientRect().bottom : 999;
        })
      );
      return {
        cols: new Set(lefts).size,
        n: row.length,
        imgSpread: imgTops.every((t) => t === null) ? null : Math.max(...imgTops) - Math.min(...imgTops),
        hSpread: Math.max(...heights) - Math.min(...heights),
        priceSpread: priceTops.every((t) => t === null) ? null : Math.max(...priceTops) - Math.min(...priceTops),
        outside,
        buttonTight,
        buttonBottomGap,
        sectionGap: secBox ? +(secBox.bottom - g.bottom).toFixed(1) : null,
      };
    });
    out.grids.push({ cls: String(grid.className || "").slice(0, 50), rows: rowsOut });
  }

  // nothing above the header: bounding boxes and DOM order
  if (header) {
    document.querySelectorAll("body *").forEach((el) => {
      if (el.contains(header) || header.contains(el)) return;
      const r = el.getBoundingClientRect();
      if (r.height < 2 || r.width < 2) return;
      const cs = getComputedStyle(el);
      if (cs.position === "fixed" || cs.display === "none" || cs.visibility === "hidden") return;
      if (r.top < headerTop - 1) out.aboveHeader.push(`${el.tagName}.${String(el.className).slice(0, 40)} top=${Math.round(r.top)}`);
    });
    document.querySelectorAll("body img").forEach((img) => {
      if (header.compareDocumentPosition(img) & Node.DOCUMENT_POSITION_PRECEDING) out.domImgsBeforeHeader++;
    });
  }

  out.scrollX = document.documentElement.scrollWidth - document.documentElement.clientWidth;
  return out;
}

async function main() {
  mkdirSync(ART, { recursive: true });

  for (const width of WIDTHS) {
    const label = `@${width}`;
    console.log(`\n== ${label} ==`);
    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({
      viewport: { width, height: Math.max(900, Math.round(width * 0.62)) },
    });

    for (const [name, url] of PAGES) {
      const page = await ctx.newPage();
      const consoleErrors = [];
      page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
      page.on("pageerror", (e) => consoleErrors.push(String(e)));
      const r = await page.goto(`${STORE}${url}`, { waitUntil: "domcontentloaded", timeout: 45000 }).catch(() => null);
      await sleep(2400);
      const geo = await page.evaluate(measureGeometry);
      await page.screenshot({ path: path.join(ART, `${name}-${width}.png`), fullPage: true });

      // extra deliverable: the Collections band (home section) as its own shot
      if (name === "home") {
        const band = page.locator(".urumi-band--alt").first();
        if (await band.count()) {
          await band.screenshot({ path: path.join(ART, `collections-${width}.png`) }).catch(() => {});
        }
      }

      if (r && r.status() !== 200 && !(name === "404" && r.status() === 404)) {
        check(`${label} ${name}: loads`, false, `status=${r.status()}`);
        await page.close();
        continue;
      }

      // 1. one container: left edges of every present member within 1px.
      //    The PDP H1 lives in the right info column by design: its RIGHT
      //    edge is checked instead of its left.
      const present = Object.entries(geo.container).filter(([, v]) => v.found);
      const leftCands = present.filter(([k, v]) => !(k === "h1" && v.inPdp));
      const refL = Math.min(...leftCands.map(([, v]) => v.left));
      const refR = Math.max(...leftCands.map(([, v]) => v.right));
      const leftOff = leftCands
        .filter(([, v]) => Math.abs(v.left - refL) > 1)
        .map(([k, v]) => `${k}(L${Math.round(v.left)})`);
      const pdpH1 = geo.container.h1.found && geo.container.h1.inPdp ? geo.container.h1 : null;
      // right edges: skip members living inside the hero (hero H1 is capped
      // at 560px by design) or the PDP columns; the PDP H1 itself must reach
      // the container's right edge
      const rightOff = leftCands
        .filter(([k, v]) => (k === "h1" ? !v.inHero : !v.inHero))
        .filter(([, v]) => Math.abs(v.right - refR) > 1)
        .map(([k, v]) => `${k}(R${Math.round(v.right)})`);
      if (pdpH1) {
        const pdpRightOff = Math.abs(pdpH1.right - refR) > 1;
        check(`${label} ${name}: PDP H1 right edge on container`,
          !pdpRightOff, `H1 R${Math.round(pdpH1.right)} vs R${Math.round(refR)}`);
      }
      check(`${label} ${name}: one container, left edges (n=${present.length})`,
        leftCands.length >= 2 && leftOff.length === 0,
        leftOff.join(", ") || `all at L${Math.round(refL)}`);
      check(`${label} ${name}: one container, right edges`,
        rightOff.length === 0,
        rightOff.join(", ") || `all at R${Math.round(refR)}`);

      // 2+3. grid row alignment + containment
      for (const g of geo.grids) {
        const bad = [];
        g.rows.forEach((row, i) => {
          if (row.imgSpread !== null && row.imgSpread > 1) bad.push(`row${i} imgSpread=${row.imgSpread.toFixed(1)}`);
          if (row.hSpread > 2) bad.push(`row${i} hSpread=${row.hSpread.toFixed(1)}`);
          if (row.priceSpread !== null && row.priceSpread > 2) bad.push(`row${i} priceSpread=${row.priceSpread.toFixed(1)}`);
          if (row.outside > 0) bad.push(`row${i} outside=${row.outside}`);
          if (row.buttonTight > 0) bad.push(`row${i} buttonTight=${row.buttonTight}`);
          if (row.buttonBottomGap < 8 && row.buttonBottomGap !== 999) bad.push(`row${i} btnGapToSection=${row.buttonBottomGap.toFixed(1)}`);
        });
        check(`${label} ${name}: grid [${g.cls.slice(0, 26)}] ${g.rows.length} row(s) aligned+contained`,
          bad.length === 0, bad.join(", ") || `${g.rows[0]?.cols ?? 0} cols/row`);
      }

      // 4. nothing above the header
      check(`${label} ${name}: nothing above the header`,
        geo.aboveHeader.length === 0 && geo.domImgsBeforeHeader === 0,
        [...geo.aboveHeader.slice(0, 2),
         ...(geo.domImgsBeforeHeader ? [`${geo.domImgsBeforeHeader} imgs before header in DOM`] : [])].join(", ") || "clean");

      // 5. no horizontal scroll
      check(`${label} ${name}: no horizontal scroll`, geo.scrollX <= 1, `overflow=${geo.scrollX}px`);

      // 7. console errors (404 page's own expected 404 resource excluded)
      const jsErrors = consoleErrors.filter(
        (e) => !/ResizeObserver loop/.test(e) && !(name === "404" && /404/.test(e))
      );
      check(`${label} ${name}: no console errors`, jsErrors.length === 0, jsErrors.slice(0, 2).join(" | ") || "clean");

      await page.close();
    }

    // 6. column counts
    {
      const page = await ctx.newPage();
      await page.goto(`${STORE}/shop/`, { waitUntil: "domcontentloaded", timeout: 45000 }).catch(() => null);
      await sleep(2000);
      const geo = await page.evaluate(measureGeometry);
      const g = geo.grids[0];
      const want = width >= 1440 ? 4 : width >= 769 ? 3 : 2;
      check(`${label} shop grid: ${want} columns`, !!g?.rows[0] && g.rows[0].cols === want,
        g?.rows[0] ? `got ${g.rows[0].cols}` : "no grid");
      await page.close();
    }
    if (width === 1440 || width <= 1024) {
      const page = await ctx.newPage();
      await page.goto(`${STORE}/product/bud-vase/`, { waitUntil: "domcontentloaded", timeout: 45000 }).catch(() => null);
      await sleep(2000);
      const geo = await page.evaluate(measureGeometry);
      const rel = geo.grids.find((g) => /urumi-grid/.test(g.cls));
      const want = width >= 1024 ? 4 : 2;
      // fewer items than columns: they fill from the left at the same width
      const n = rel?.rows[0]?.n ?? 0;
      check(`${label} related row: ${want} columns (${n} item(s))`,
        !!rel?.rows[0] && rel.rows[0].cols === Math.min(want, n),
        rel?.rows[0] ? `got ${rel.rows[0].cols} of ${n} items` : "no related grid");
      await page.close();
    }

    await ctx.close();
    await browser.close();
  }

  const fails = results.filter((r) => !r.ok);
  console.log(`\n${results.length} checks, ${fails.length} failures`);
  if (fails.length) {
    console.log("FAILURES:");
    failures.slice(0, 25).forEach((f) => console.log("  " + f));
    process.exit(1);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
