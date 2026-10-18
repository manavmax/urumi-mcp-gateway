/* Chat, exact port of design/mockups/chat.html (family O) with the real SSE
   loop against POST /api/chat/completions: events model, token, tool_call,
   text, [DONE]; tool output is truncated at 2000 chars in the UI. The history
   rail is the STAGE 1 decision: browser-only localStorage (last 20 sessions
   per user, cleared on sign out), replacing the mockup's NEEDS DECISION note.

   FIX 1: Supports prefill state from OverviewMember "Try in chat" cards:
   navigate("/chat", { state: { prefill: text } }) pre-fills the composer without
   sending, and clears the state so a refresh doesn't replay it.

   F3 image attachments: attach button + drag/drop on the composer, in-memory
   preview thumbnail with a remove button, client-side type/size checks with
   clear error text. Upload happens at send time (POST /api/chat/uploads) and
   only the returned upload id is referenced in the message — history in
   localStorage stores only an "[image]" placeholder, never the bytes. */
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, type ChatContentPart } from "../lib/api";
import { outcomeChip } from "../lib/audit-outcome";
import { useAuth } from "../lib/auth";
import { displayName } from "../lib/search";
import { clearHistory, loadHistory, saveSession, type ChatSession, type ChatTurn } from "../lib/history";
import { useMockupMotion } from "../lib/motion";
import { Icon } from "../components/icons";

type Msg = { role: "user" | "assistant" | "tool"; content: string; tool?: string; outcome?: string; truncated?: boolean };

const MAX_TOOL_OUTPUT = 2000;

/* F3 image attachments: client-side pre-check mirrors the server rules
   (magic bytes are re-checked server-side; these checks are instant UX). */
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];
const IMAGE_MAX_BYTES = 5 * 1024 * 1024;

const STARTERS = [
  { tile: "var(--sky)", icon: "cart" as const, title: "Orders today", text: "What orders came in today?" },
  { tile: "var(--butter)", icon: "plus" as const, title: "Create a product", text: "Create product Urumi Tee $29.99 (write)" },
  { tile: "var(--lilac)", icon: "globe" as const, title: "World clock", text: "What time is it in Tokyo?" },
];

function prettyJson(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
function toolOutput(output: unknown): { text: string; truncated: boolean } {
  const raw = prettyJson(output);
  if (!raw || raw.length <= MAX_TOOL_OUTPUT) return { text: raw, truncated: false };
  return {
    text: `${raw.slice(0, MAX_TOOL_OUTPUT)}\n… truncated (${raw.length} chars, showing first ${MAX_TOOL_OUTPUT})`,
    truncated: true,
  };
}
function relTime(ts: number): string {
  const secs = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (secs < 60) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "Yesterday" : `${days} days ago`;
}

export default function Chat() {
  const { user } = useAuth();
  const email = user?.email || "";
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [servingModel, setServingModel] = useState<string | null>(null);
  const [history, setHistory] = useState<ChatSession[]>([]);
  const [histFilter, setHistFilter] = useState("");
  // F3: pending attachment held in memory only — the preview is a blob: object
  // URL, never persisted; history stores only an "[image]" placeholder.
  const [pendingImage, setPendingImage] = useState<{ file: File; url: string; name: string } | null>(null);
  const [imgErr, setImgErr] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    setHistory(loadHistory(email));
  }, [email]);

  useEffect(() => () => { if (pendingImage) URL.revokeObjectURL(pendingImage.url); }, [pendingImage]);

  function attachImage(file: File | undefined | null) {
    if (!file || busy) return;
    if (!IMAGE_TYPES.includes(file.type)) {
      setImgErr("Only PNG, JPEG or WEBP images are supported.");
      return;
    }
    if (file.size > IMAGE_MAX_BYTES) {
      setImgErr("Image is too large — the limit is 5 MB.");
      return;
    }
    setImgErr("");
    if (pendingImage) URL.revokeObjectURL(pendingImage.url);
    setPendingImage({ file, url: URL.createObjectURL(file), name: file.name });
  }

  function clearPendingImage() {
    setPendingImage((p) => {
      if (p) URL.revokeObjectURL(p.url);
      return null;
    });
    setImgErr("");
  }

  /* FIX 1 prefill: OverviewMember "Try in chat" navigates here with
     { state: { prefill } } so the composer is primed without sending. Read once
     on mount, then clear the state so a refresh does not replay it. */
  useEffect(() => {
    const prefill = (location.state as { prefill?: string } | null)?.prefill;
    if (prefill) {
      setInput(prefill);
      navigate(location.pathname, { replace: true, state: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useMockupMotion(busy);

  const shownHistory = useMemo(() => {
    const q = histFilter.trim().toLowerCase();
    if (!q) return history;
    return history.filter((h) => `${h.title} ${h.snippet}`.toLowerCase().includes(q));
  }, [history, histFilter]);

  function loadSession(s: ChatSession) {
    setErr("");
    setMessages(s.turns.map((t) => ({ role: t.role, content: t.content })));
  }

  function newChat() {
    setMessages([]);
    setErr("");
    setImgErr("");
    setServingModel(null);
  }

  async function send(text: string) {
    const prompt = text.trim();
    if (busy) return;
    if (!prompt && !pendingImage) return;
    setErr("");

    // F3: upload first; only the server-issued upload id goes into the message.
    let parts: ChatContentPart[] | null = null;
    if (pendingImage) {
      try {
        const up = await api.uploadChatImage(pendingImage.file);
        parts = [
          ...(prompt ? [{ type: "text" as const, text: prompt }] : []),
          { type: "image_upload", upload_id: up.upload_id },
        ];
      } catch (e: unknown) {
        setImgErr(e instanceof Error ? e.message : String(e));
        return;
      } finally {
        clearPendingImage();
      }
    }
    // Thread display + localStorage keep a placeholder, never bytes.
    const displayContent = parts ? (prompt ? `${prompt}\n[image]` : "[image]") : prompt;
    const next: Msg[] = [...messages, { role: "user", content: displayContent }];
    setMessages(next);
    setInput("");
    setBusy(true);
    try {
      const res = await api.chatCompletions([
        ...next.slice(0, -1).filter((m) => m.role !== "tool").map((m) => ({ role: m.role, content: m.content })),
        { role: "user", content: parts ?? prompt },
      ]);
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body.slice(0, 500) || res.statusText);
      }
      const ct = res.headers.get("content-type") || "";
      if (ct.includes("text/event-stream")) {
        const reader = res.body?.getReader();
        const decoder = new TextDecoder();
        let assistant = "";
        const commitAssistant = () =>
          setMessages((prev) => {
            const copy = [...prev];
            const last = copy[copy.length - 1];
            if (last && last.role === "assistant") copy[copy.length - 1] = { ...last, content: assistant };
            else copy.push({ role: "assistant", content: assistant });
            return copy;
          });
        if (!reader) throw new Error("no stream");
        let buf = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const parts2 = buf.split("\n\n");
          buf = parts2.pop() || "";
          for (const part of parts2) {
            const line = part.trim();
            if (!line.startsWith("data:")) continue;
            const payload = line.slice(5).trim();
            if (payload === "[DONE]") break;
            try {
              const evt = JSON.parse(payload);
              if (evt.type === "model") {
                setServingModel(evt.model || null);
              } else if (evt.type === "token") {
                assistant += evt.content || "";
                commitAssistant();
              } else if (evt.type === "tool_call") {
                const out = toolOutput(evt.output);
                setMessages((prev) => [...prev, {
                  role: "tool", content: out.text, truncated: out.truncated,
                  tool: evt.tool || evt.name, outcome: evt.outcome || evt.status,
                }]);
              } else if (evt.type === "text") {
                const label = evt.category ? ` [${evt.category}]` : "";
                assistant += (evt.content || "") + label;
                commitAssistant();
              }
            } catch {
              /* ignore malformed SSE line */
            }
          }
        }
        if (assistant) {
          setHistory(saveSession(email, [
            { role: "user", content: displayContent },
            { role: "assistant", content: assistant },
          ]));
        }
      } else {
        const data = await res.json();
        const content = data.content || data.message || JSON.stringify(data).slice(0, 4000);
        const toolCalls: Msg[] = (data.tool_calls || []).map((tc: { tool: string; outcome: string; output: unknown }) => {
          const out = toolOutput(tc.output);
          return { role: "tool" as const, content: out.text, truncated: out.truncated, tool: tc.tool, outcome: tc.outcome };
        });
        setMessages((prev) => [...prev, ...toolCalls, { role: "assistant", content: String(content) }]);
        setHistory(saveSession(email, [
          { role: "user", content: displayContent },
          { role: "assistant", content: String(content) },
        ]));
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      setTimeout(() => logRef.current?.scrollTo(0, logRef.current.scrollHeight), 50);
    }
  }

  const name = displayName(email) || "there";

  return (
    <main className="content">
      <header className="page-head">
        <div>
          <h1>Hello, {name}</h1>
        </div>
        <div className="row wrap" style={{ gap: 8 }}>
          {servingModel && (
            <span className="chip chip-neutral" title="Model reported by the SSE model event">
              <span className="mono">Serving: {servingModel}</span>
            </span>
          )}
        </div>
      </header>

      {err && <div className="alert alert-error" role="alert">{err}</div>}
      {imgErr && <div className="alert alert-error" role="alert">{imgErr}</div>}

      <div className="chat-layout">
        <section className="thread">
          {messages.length === 0 ? (
            <section className="card empty-state" aria-label="New chat">
              <div className="empty-glow" aria-hidden="true" />
              <div className="empty-mark"><Icon name="logo" size={28} /></div>
              <h2>Hello, {name}</h2>
              <p className="sub">What would you like to do in your store?</p>
              <div className="suggestion-grid">
                {STARTERS.map((s) => (
                  <div key={s.title} className="starter" role="button" tabIndex={0}
                    onClick={() => send(s.text)}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); send(s.text); } }}>
                    <span className="tile" style={{ background: s.tile }}><Icon name={s.icon} /></span>
                    <b>{s.title}</b>
                    <span>{s.text}</span>
                  </div>
                ))}
              </div>
            </section>
          ) : (
            <div className="card thread-card" style={{ padding: 24, display: "grid", gap: 16, minHeight: 420 }}>
              {messages.map((m, i) => (
                <div key={i} className="msg-wrap">
                  {m.role === "tool" ? (
                    <div className="msg assistant">
                      <div className="avatar ai">UR</div>
                      <div className="tool-call">
                        <div className="head">
                          <span className="name">{m.tool}</span>
                          <span className={`chip ${outcomeChip(m.outcome || "").cls}`}><Icon name={outcomeChip(m.outcome || "").icon} />{m.outcome || "tool"}</span>
                        </div>
                        {m.content && (
                          <details className="out">
                            <summary><Icon name="chevron" />output{m.truncated ? " (truncated)" : ""}</summary>
                            <pre>{m.content}</pre>
                          </details>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className={`msg ${m.role}`}>
                      <div className={`avatar${m.role === "assistant" ? " ai" : ""}`}>{m.role === "assistant" ? "UR" : (email.slice(0, 2).toUpperCase() || "ME")}</div>
                      {m.content ? <div className="bubble">{m.content}</div> : null}
                    </div>
                  )}
                </div>
              ))}
              {busy && (
                <div className="typing">
                  <span className="tdot" aria-hidden="true"><i></i><i></i><i></i></span>Assistant is thinking...
                </div>
              )}
            </div>
          )}

          {imgErr && !err && <div className="alert alert-error" role="alert">{imgErr}</div>}

          {/* F3: in-memory preview thumbnail — remove button clears it; nothing is persisted */}
          {pendingImage && (
            <div className="chip chip-neutral" style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "6px 10px", alignSelf: "flex-start" }}>
              <img src={pendingImage.url} alt="" width={28} height={28} style={{ borderRadius: 6, objectFit: "cover" }} />
              <span style={{ maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{pendingImage.name}</span>
              <button type="button" className="chip chip-neutral" aria-label="Remove attached image" style={{ border: "none", cursor: "pointer", padding: 4 }}
                onClick={clearPendingImage} disabled={busy}>
                <Icon name="x" sm />
              </button>
            </div>
          )}

          <form className="composer" onSubmit={(e) => { e.preventDefault(); send(input); }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); attachImage(e.dataTransfer?.files?.[0]); }}>
            <input ref={fileInputRef} type="file" accept="image/png,image/jpeg,image/webp" style={{ display: "none" }}
              onChange={(e) => { attachImage(e.target.files?.[0]); e.currentTarget.value = ""; }} />
            <button className="send" type="button" aria-label="Attach image" title="Attach an image (PNG, JPEG or WEBP, up to 5 MB)"
              style={{ background: "var(--surface)" }} disabled={busy}
              onClick={() => fileInputRef.current?.click()}>
              <Icon name="image" />
            </button>
            <input placeholder="Ask the store assistant" aria-label="Chat message" value={input}
              onChange={(e) => setInput(e.target.value)} disabled={busy} />
            <button className="send" type="submit" aria-label="Send" disabled={busy || (!input.trim() && !pendingImage)}><Icon name="send" /></button>
          </form>
        </section>

        {/* right-hand chat history panel */}
        <aside className="history">
          <div className="card" style={{ padding: 16 }}>
            <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
              <div className="card-title" style={{ fontSize: "var(--t-md)" }}><Icon name="clock" />Chat history</div>
            </div>
            <label className="hist-search" style={{ marginBottom: 8 }}>
              <Icon name="search" sm />
              <input type="search" placeholder="Search chats" aria-label="Search history" value={histFilter}
                onChange={(e) => setHistFilter(e.target.value)} />
            </label>
            <div className="hist-list">
              {shownHistory.map((h) => (
                <div className="hist-item" key={h.id} onClick={() => loadSession(h)} role="button" tabIndex={0}
                  onKeyDown={(e) => { if (e.key === "Enter") loadSession(h); }}>
                  <b>{h.title}</b>
                  <span>{h.snippet || "No reply text"}</span>
                  <span className="faint">{relTime(h.ts)}</span>
                </div>
              ))}
              {shownHistory.length === 0 && (
                <div className="hist-item empty-drift"><b>No chats yet</b><span>Your conversations appear here, stored in this browser only</span></div>
              )}
            </div>
            <button className="btn btn-ink" type="button" style={{ width: "100%", justifyContent: "center", marginTop: 12 }} onClick={newChat}>
              <Icon name="plus" sm />New chat
            </button>
          </div>
        </aside>
      </div>
    </main>
  );
}
