#!/usr/bin/env node
// FIX PASS F1-8 unit tests for the safe markdown renderer
// (src/dashboard/src/lib/markdown.tsx): hand-written, no new dependency.
// The test bundles the renderer with esbuild (already a vite dependency) and
// renders with react-dom/server, then asserts:
//   - bold/italic/inline code/lists/tables/links render as elements
//   - <script> payloads stay ESCAPED TEXT (no HTML pass-through)
//   - markdown images are dropped (exfiltration vector)
//   - javascript:/data: links are never anchors; http/https links get
//     rel="noopener noreferrer" target="_blank"
// Run: node scripts/verify-markdown.mjs
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { writeFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const esbuild = require("../src/dashboard/node_modules/esbuild");

const here = dirname(fileURLToPath(import.meta.url));
const dash = join(here, "..", "src", "dashboard");
const TESTSRC = join(dash, ".md-test-src.mjs");
const OUT = join(dash, ".md-test-bundle.cjs");

const testSource = `
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Markdown, parseMarkdown } from "./src/lib/markdown";
import assert from "node:assert";

const html = (text) => renderToStaticMarkup(React.createElement(Markdown, { text }));
const BT = "\\x60"; // a backtick, without breaking this generated source

// 1) basic inline formatting
const h = html("Orders **today** are *paid* via " + BT + "woo__list_orders" + BT);
assert(h.includes("<strong>today</strong>"), "bold renders as <strong>");
assert(h.includes("<em>paid</em>"), "italic renders as <em>");
assert(h.includes("<code"), "inline code renders as <code>");
assert(!h.includes("**"), "no raw ** markers left");

// 2) paragraphs and lists
const listHtml = html("Intro line\\n\\n- first\\n- second\\n\\n1. one\\n2. two");
assert(listHtml.includes("<p>Intro line</p>"), "paragraph block");
assert(listHtml.includes("<ul>") && listHtml.includes("<li>"), "bullet list");
assert(listHtml.includes("<ol>"), "ordered list");

// 3) tables
const t = html("| Order | Status | Total |\\n|---|---|---|\\n| #89 | processing | $209.98 |");
assert(t.includes("<table>") && t.includes("<th>") && t.includes("<td>"), "markdown table renders");
assert(t.includes("#89") && t.includes("$209.98"), "table cell content");

// 4) XSS payloads stay text
const s = html("<script>alert(1)</script>");
assert(!/<script/i.test(s), "script tag never rendered as an element: " + s);
assert(s.includes("&lt;script&gt;"), "script payload stays escaped text");
const s2 = html('<img src=x onerror="alert(1)">');
assert(!/<img/i.test(s2), "raw html img never rendered: " + s2);

// 5) markdown images are DROPPED entirely
const img = html("before ![evil](http://127.0.0.1:9/exfil.png) after");
assert(!/<img/i.test(img), "image element must not render");
assert(!img.includes("exfil.png"), "image URL must not appear at all");

// 6) unsafe link schemes never become anchors; the characters stay as text
const js = html("[click](javascript:alert(1))");
assert(!js.includes("<a "), "javascript: payload must not become an anchor");
assert(!js.includes('href="javascript:'), "javascript: href must not appear");
assert(js.includes("[click](javascript:alert(1))"), "unsafe link stays literal inert text");
const dt = html("[d](data:text/html,alert(1))");
assert(!dt.includes("<a "), "data: link suppressed");

// 7) real links carry the safe attributes
const a = html("[store](https://example.com/x)");
assert(a.includes("<a "), "https link renders as an anchor");
assert(a.includes('href="https://example.com/x"'), "https href kept");
assert(a.includes('rel="noopener noreferrer"'), "rel noopener noreferrer present");
assert(a.includes('target="_blank"'), "target blank");
assert(html("[b](http://example.com)").includes('href="http://example.com"'), "http link allowed");

// 8) parser tree sanity
const blocks = parseMarkdown("plain **bold** text");
assert(blocks.length === 1 && blocks[0].t === "p", "single paragraph block");
assert(JSON.stringify(blocks[0].v[1]) === '{"t":"bold","v":[{"t":"text","v":"bold"}]}', "bold parsed to inline node");

console.log("ALL MARKDOWN UNIT CHECKS PASSED");
`;

let failed = false;
try {
  rmSync(TESTSRC, { force: true });
  rmSync(OUT, { force: true });
  writeFileSync(TESTSRC, testSource);
  esbuild.buildSync({
    entryPoints: [TESTSRC],
    bundle: true,
    outfile: OUT,
    platform: "node",
    format: "cjs",
    jsx: "automatic",
    logLevel: "silent",
  });
  const out = execFileSync(process.execPath, [OUT], { encoding: "utf8", cwd: dash });
  console.log(out.trim());
} catch (e) {
  failed = true;
  console.error(String(e.stdout || "") + String(e.stderr || e.message || e));
} finally {
  rmSync(TESTSRC, { force: true });
  rmSync(OUT, { force: true });
}
if (failed) process.exit(1);
