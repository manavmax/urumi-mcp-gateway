import { useState, useRef } from "react";
import { api } from "../lib/api";

type Msg = { role: "user" | "assistant" | "tool"; content: string; tool?: string; outcome?: string; truncated?: boolean };

// Tool output is JSON from the MCP server, so it must be pretty-printed for a human to
// read it. It is collapsed by default (a <details> block) and truncated when long, so a
// 500-product listing cannot take over the chat log.
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
        // SSE streaming
        const reader = res.body?.getReader();
        const decoder = new TextDecoder();
        // No empty assistant bubble is created up front: until the model actually emits
        // a token (or finishes), the log shows the user message and the tool chips only.
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
                assistant += evt.content || "";
                commitAssistant();
              }
            } catch {
              // ignore
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
    <div className="chat">
      <h2>Chat — store assistant</h2>
      {servingModel && <p className="muted small mono">serving model: {servingModel}</p>}
      <p className="muted small">Chat uses server-side tool loop; upstream credentials never reach the browser. Tool calls are audited as your user.</p>
      {err && <div className="alert alert-error">{err}</div>}
      <div ref={logRef} className="chat-log">
        {messages.length === 0 && <div className="muted">Try: “Create product Urumi Tee $29.99” or “What orders came in today?”</div>}
        {messages.map((m, i) => (
          <div key={i} className={`chat-msg chat-${m.role}`}>
            {m.role === "tool" ? (
              <div className="tool-chip">
                <span className="mono">{m.tool}</span> <span className={`badge ${m.outcome === "success" ? "badge-connected" : "badge-unreachable"}`}>{m.outcome || "tool"}</span>
                {m.content && (
                  <details>
                    <summary>output{m.truncated ? " (truncated)" : ""}</summary>
                    <pre className="small">{m.content}</pre>
                  </details>
                )}
              </div>
            ) : m.content ? (
              <div className={`bubble ${m.role}`}>{m.content}</div>
            ) : null}
          </div>
        ))}
      </div>
      <form onSubmit={send} className="row gap">
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask the store assistant..." className="flex1" disabled={busy} />
        <button type="submit" disabled={busy || !input.trim()}>
          {busy ? "..." : "Send"}
        </button>
      </form>
    </div>
  );
}
