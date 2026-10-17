/* Safe hand-written markdown renderer (FIX PASS F1-8): NO new dependency and
   NO dangerouslySetInnerHTML anywhere. It renders a parsed tree as React
   elements, so nothing from the model's output is ever passed to the browser
   as HTML. Supported: paragraphs, bold, italic, inline code, lists (ul/ol),
   tables, links (http and https ONLY, always rel="noopener noreferrer" +
   target="_blank").
   Deliberately NOT supported (untrusted LLM output is an exfiltration vector):
   - markdown images are dropped entirely
   - no HTML pass-through: "<script>" and friends stay literal escaped text
   - links with javascript:/data:/vbscript: schemes render as plain text */

import * as React from "react";

export type MdInline =
  | { t: "text"; v: string }
  | { t: "bold"; v: MdInline[] }
  | { t: "italic"; v: MdInline[] }
  | { t: "code"; v: string }
  | { t: "link"; href: string; v: MdInline[] };

export type MdBlock =
  | { t: "p"; v: MdInline[] }
  | { t: "ul"; items: MdInline[][] }
  | { t: "ol"; items: MdInline[][] }
  | { t: "table"; head: MdInline[][]; rows: MdInline[][][] }
  | { t: "hr" };

/* http and https only; anything else (javascript:, data:, mailto:, //) is not a link */
const SAFE_HREF = /^https?:\/\//i;
const LINK_RE = /^\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/;
const IMAGE_RE = /^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/;
const TABLE_DIVIDER = /^:?-{1,}:?$/;

function parseInline(src: string): MdInline[] {
  const out: MdInline[] = [];
  let buf = "";
  let i = 0;
  const push = () => {
    if (buf) {
      out.push({ t: "text", v: buf });
      buf = "";
    }
  };
  while (i < src.length) {
    // markdown image: DROPPED, never rendered
    if (src.startsWith("![", i)) {
      const m = IMAGE_RE.exec(src.slice(i));
      if (m) {
        i += m[0].length;
        continue;
      }
    }
    // bold before italic so ** is never read as an empty italic pair
    if (src.startsWith("**", i)) {
      const end = src.indexOf("**", i + 2);
      if (end > i + 1) {
        push();
        out.push({ t: "bold", v: parseInline(src.slice(i + 2, end)) });
        i = end + 2;
        continue;
      }
    }
    if (src[i] === "`") {
      const end = src.indexOf("`", i + 1);
      if (end > i) {
        push();
        out.push({ t: "code", v: src.slice(i + 1, end) });
        i = end + 1;
        continue;
      }
    }
    if (src[i] === "*" || src[i] === "_") {
      const mark = src[i];
      const end = src.indexOf(mark, i + 1);
      if (end > i + 1) {
        push();
        out.push({ t: "italic", v: parseInline(src.slice(i + 1, end)) });
        i = end + 1;
        continue;
      }
    }
    if (src[i] === "[") {
      const m = LINK_RE.exec(src.slice(i));
      if (m) {
        i += m[0].length;
        if (SAFE_HREF.test(m[2])) {
          push();
          out.push({ t: "link", href: m[2], v: parseInline(m[1]) });
        } else {
          // unsafe scheme: keep the raw characters as plain text, no anchor
          buf += m[0];
        }
        continue;
      }
    }
    buf += src[i];
    i += 1;
  }
  push();
  return out;
}

function cells(line: string): string[] {
  return line.slice(1, -1).split("|").map((c) => c.trim());
}

function isDivider(row: string[]): boolean {
  return row.length > 0 && row.every((c) => TABLE_DIVIDER.test(c));
}

function isPipeRow(trimmed: string): boolean {
  return trimmed.length > 1 && trimmed.startsWith("|") && trimmed.endsWith("|");
}

const LIST_ITEM = /^(\d+)[.)]\s+(.*)$/;
const BULLET_ITEM = /^[-*]\s+(.*)$/;

export function parseMarkdown(src: string): MdBlock[] {
  const lines = (src || "").replace(/\r\n/g, "\n").split("\n");
  const blocks: MdBlock[] = [];
  let para: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let pipes: string[] | null = null;

  const flushPara = () => {
    if (para.length) {
      blocks.push({ t: "p", v: parseInline(para.join(" ")) });
      para = [];
    }
  };
  const flushList = () => {
    if (list) {
      blocks.push({ t: list.ordered ? "ol" : "ul", items: list.items.map(parseInline) });
      list = null;
    }
  };
  const flushTable = () => {
    if (pipes) {
      if (pipes.length >= 2 && isDivider(cells(pipes[1]))) {
        const head = cells(pipes[0]);
        const rows = pipes.slice(2).map(cells);
        blocks.push({ t: "table", head: head.map(parseInline), rows: rows.map((r) => r.map(parseInline)) });
      } else {
        // not a real table (no divider row): keep the characters as text
        for (const p of pipes) para.push(p);
      }
      pipes = null;
    }
  };
  const flushAll = () => {
    flushPara();
    flushList();
    flushTable();
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (isPipeRow(trimmed)) {
      flushPara();
      flushList();
      (pipes ||= []).push(trimmed);
      continue;
    }
    flushTable();
    if (!trimmed) {
      flushAll();
      continue;
    }
    if (/^(---|\*\*\*|___)\s*$/.test(trimmed)) {
      flushAll();
      blocks.push({ t: "hr" });
      continue;
    }
    const ol = LIST_ITEM.exec(trimmed);
    const ul = BULLET_ITEM.exec(trimmed);
    if (ol || ul) {
      flushPara();
      const ordered = !!ol;
      if (!list || list.ordered !== ordered) {
        flushList();
        list = { ordered, items: [] };
      }
      list.items.push((ol ? ol[2] : ul![1]).trim());
      continue;
    }
    flushList();
    para.push(trimmed);
  }
  flushAll();
  return blocks;
}

function Inline({ v }: { v: MdInline[] }) {
  return (
    <>
      {v.map((n, i) => {
        switch (n.t) {
          case "text":
            return <React.Fragment key={i}>{n.v}</React.Fragment>;
          case "bold":
            return <strong key={i}><Inline v={n.v} /></strong>;
          case "italic":
            return <em key={i}><Inline v={n.v} /></em>;
          case "code":
            return <code key={i} className="md-code">{n.v}</code>;
          case "link":
            return (
              <a key={i} href={n.href} target="_blank" rel="noopener noreferrer">
                <Inline v={n.v} />
              </a>
            );
          default:
            return null;
        }
      })}
    </>
  );
}

/* The chat bubble renderer: parses on every text change (cheap for reply-sized
   strings) and returns React elements only. */
export function Markdown({ text }: { text: string }) {
  const blocks = React.useMemo(() => parseMarkdown(text), [text]);
  return (
    <div className="md">
      {blocks.map((b, i) => {
        switch (b.t) {
          case "p":
            return <p key={i}><Inline v={b.v} /></p>;
          case "ul":
            return <ul key={i}>{b.items.map((it, j) => <li key={j}><Inline v={it} /></li>)}</ul>;
          case "ol":
            return <ol key={i}>{b.items.map((it, j) => <li key={j}><Inline v={it} /></li>)}</ol>;
          case "table":
            return (
              <table key={i}>
                <thead>
                  <tr>{b.head.map((h, j) => <th key={j}><Inline v={h} /></th>)}</tr>
                </thead>
                <tbody>
                  {b.rows.map((r, ri) => (
                    <tr key={ri}>{r.map((c, ci) => <td key={ci}><Inline v={c} /></td>)}</tr>
                  ))}
                </tbody>
              </table>
            );
          case "hr":
            return <hr key={i} />;
          default:
            return null;
        }
      })}
    </div>
  );
}
