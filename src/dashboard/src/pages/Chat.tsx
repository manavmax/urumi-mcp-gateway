/* Chat, exact port of design/mockups/chat.html (family O) with the real SSE
   loop against POST /api/chat/completions: events model, token, tool_call,
   text, [DONE]; tool output is truncated at 2000 chars in the UI. The history
   rail is the STAGE 1 decision: browser-only localStorage threads (FIX PASS
   F1-4: one thread per conversation, the ACTIVE thread continues on send,
   "New chat" or opening the page starts a new one, last 20 threads per user,
   cleared on sign out). Assistant replies render through the safe markdown
   renderer (FIX PASS F1-8); LLM error text is shown inline and never stored
   in a thread.

   FIX 1: Supports prefill state from OverviewMember "Try in chat" cards:
   navigate("/chat", { state: { prefill: text } }) pre-fills the composer without
   sending, and clears the state so a refresh doesn't replay it. */
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { outcomeChip } from "../lib/audit-outcome";
import { useAuth } from "../lib/auth";
import { displayName } from "../lib/search";
import { chatPayloadTurns, loadHistory, saveThread, type ChatThread } from "../lib/history";
import { useMockupMotion } from "../lib/motion";
import { Icon } from "../components/icons";

type Msg = { role: "user" | "assistant" | "tool"; content: string; tool?: string; outcome?: string; truncated?: boolean };

const MAX_TOOL_OUTPUT = 2000;

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
  const [activeId, setActiveId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [servingModel, setServingModel] = useState<string | null>(null);
  const [history, setHistory] = useState<ChatThread[]>([]);
  const [histFilter, setHistFilter] = useState("");
  const logRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    setHistory(loadHistory(email));
  }, [email]);

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

  /* Clicking a thread restores the WHOLE conversation and continues it: the
     next send appends to this thread id. */
  function openThread(t: ChatThread) {
    setErr("");
    setServingModel(null);
    setActiveId(t.id);
    setMessages(t.turns.map((turn) => ({ role: turn.role, content: turn.content })));
  }

  /* Opening the chat page or pressing "New chat" always starts a new thread:
     activeId goes back to null, so the next send creates a fresh thread. */
  function newChat() {
    setMessages([]);
    setActiveId(null);
    setErr("");
    setServingModel(null);
  }

  async function send(text: string) {
    const prompt = text.trim();
    if (!prompt || busy) return;
    setErr("");
    const next: Msg[] = [...messages, { role: "user", content: prompt }];
    setMessages(next);
    setInput("");
    setBusy(true);
    const threadId = activeId;
    // Prior context: user and assistant text only (tool chips never go back),
    // last 10 turns and a total size cap (see chatPayloadTurns).
    const payload = chatPayloadTurns(next.filter((m): m is Msg & { role: "user" | "assistant" } => m.role !== "tool").map((m) => ({ role: m.role, content: m.content })));
    try {
      const res = await api.chatCompletions(payload);
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body.slice(0, 500) || res.statusText);
      }
      const ct = res.headers.get("content-type") || "";
      if (ct.includes("text/event-stream")) {
        const reader = res.body?.getReader();
        const decoder = new TextDecoder();
        let assistant = "";
        let errorText = "";
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
          const parts = buf.split("\n\n");
          buf = parts.pop() || "";
          for (const part of parts) {
            const line = part.trim();
            if (!line.startsWith("data:")) continue;
            const sse = line.slice(5).trim();
            if (sse === "[DONE]") break;
            try {
              const evt = JSON.parse(sse);
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
                // A category means an abnormal turn end (quota, timeout, write
                // caveat...): show it inline, never store it in the thread.
                if (evt.category) {
                  errorText = evt.content || "The assistant could not finish this turn.";
                  setErr(errorText);
                } else {
                  assistant += evt.content || "";
                  commitAssistant();
                }
              }
            } catch {
              /* ignore malformed SSE line */
            }
          }
        }
        // Only a clean answer is committed to the thread; an error turn stays
        // inline and is never saved as thread title or reply.
        if (assistant && !errorText) {
          const saved = saveThread(email, threadId, [
            { role: "user", content: prompt },
            { role: "assistant", content: assistant },
          ]);
          setActiveId(saved.id);
          setHistory(saved.threads);
        }
      } else {
        const data = await res.json();
        const content = data.content || data.message || JSON.stringify(data).slice(0, 4000);
        const toolCalls: Msg[] = (data.tool_calls || []).map((tc: { tool: string; outcome: string; output: unknown }) => {
          const out = toolOutput(tc.output);
          return { role: "tool" as const, content: out.text, truncated: out.truncated, tool: tc.tool, outcome: tc.outcome };
        });
        setMessages((prev) => [...prev, ...toolCalls, { role: "assistant", content: String(content) }]);
        const saved = saveThread(email, threadId, [
          { role: "user", content: prompt },
          { role: "assistant", content: String(content) },
        ]);
        setActiveId(saved.id);
        setHistory(saved.threads);
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

          <form className="composer" onSubmit={(e) => { e.preventDefault(); send(input); }}>
            <input placeholder="Ask the store assistant" aria-label="Chat message" value={input}
              onChange={(e) => setInput(e.target.value)} disabled={busy} />
            <button className="send" type="submit" aria-label="Send" disabled={busy}><Icon name="send" /></button>
          </form>
        </section>

        {/* right-hand chat history panel: one row per THREAD */}
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
                <div className={`hist-item${h.id === activeId ? " on" : ""}`} key={h.id} onClick={() => openThread(h)} role="button" tabIndex={0}
                  onKeyDown={(e) => { if (e.key === "Enter") openThread(h); }}>
                  <b>{h.title}</b>
                  <span>{h.snippet || "No reply text"}</span>
                  <span className="faint">{h.count} messages · {relTime(h.ts)}</span>
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
