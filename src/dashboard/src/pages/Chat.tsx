import { useState, useRef } from "react";
import { api } from "../lib/api";
import { OutcomeBadge } from "../components/ui/Badge";

type Msg = { role: "user" | "assistant" | "tool"; content: string; tool?: string; outcome?: string; truncated?: boolean };

const MAX_TOOL_OUTPUT = 2000;

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

export default function Chat() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [servingModel, setServingModel] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setErr("");
    const next: Msg[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setBusy(true);
    try {
      const res = await api.chatCompletions(next.filter((m) => m.role !== "tool").map((m) => ({ role: m.role, content: m.content })));
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
          const parts = buf.split("\n\n");
          buf = parts.pop() || "";
          for (const part of parts) {
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
                setMessages((prev) => [...prev, { role: "tool", content: out.text, truncated: out.truncated, tool: evt.tool || evt.name, outcome: evt.outcome || evt.status }]);
              } else if (evt.type === "text") {
                // Error/category text from the gateway (LLM failure, timeout, fallback cap, etc.)
                const label = evt.category ? ` [${evt.category}]` : "";
                assistant += (evt.content || "") + label;
                commitAssistant();
              }
            } catch {
              // ignore malformed SSE line
            }
          }
        }
      } else {
        const data = await res.json();
        const content = data.content || data.message || JSON.stringify(data).slice(0, 4000);
        const toolCalls: Msg[] = (data.tool_calls || []).map((tc: { tool: string; outcome: string; output: unknown }) => {
          const out = toolOutput(tc.output);
          return {
            role: "tool" as const,
            content: out.text,
            truncated: out.truncated,
            tool: tc.tool,
            outcome: tc.outcome,
          };
        });
        setMessages((prev) => [...prev, ...toolCalls, { role: "assistant", content: String(content) }]);
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      setTimeout(() => logRef.current?.scrollTo(0, logRef.current.scrollHeight), 50);
    }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <h2>Chat — store assistant</h2>
        {servingModel && <span className="badge badge-unknown mono small" title="Model serving this turn">Serving: {servingModel}</span>}
      </div>
      <p className="small muted" style={{ marginTop: -6 }}>Chat uses server-side tool loop; upstream credentials never reach the browser. Tool calls are audited as your user.</p>
      {err && <div className="alert alert-error" role="alert">{err}</div>}
      <div ref={logRef} className="chat-log" aria-live="polite">
        {messages.length === 0 && <div className="empty">Try: “Create product Urumi Tee $29.99” or “What orders came in today?”<div className="small muted" style={{ marginTop: 6 }}>Tool calls appear as chips — tap output to expand.</div></div>}
        {messages.map((m, i) => (
          <div key={i} className={`chat-msg chat-${m.role}`}>
            {m.role === "tool" ? (
              <div className="tool-chip">
                <div className="row gap wrap">
                  <span className="mono small" style={{ fontWeight: 750 }}>{m.tool}</span>
                  <OutcomeBadge outcome={m.outcome || "tool"} />
                </div>
                {m.content && (
                  <details style={{ marginTop: 6 }}>
                    <summary className="small muted">output{m.truncated ? " (truncated)" : ""}</summary>
                    <pre className="small" style={{ marginTop: 6 }}>{m.content}</pre>
                  </details>
                )}
              </div>
            ) : m.content ? (
              <div className={`bubble ${m.role}`}>{m.content}</div>
            ) : null}
          </div>
        ))}
        {busy && <div className="small muted">Assistant is thinking…</div>}
      </div>
      <form onSubmit={send} className="row gap">
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask the store assistant..." className="flex1" disabled={busy} aria-label="Chat message" />
        <button type="submit" disabled={busy || !input.trim()}>
          {busy ? "…" : "Send"}
        </button>
      </form>
    </div>
  );
}
