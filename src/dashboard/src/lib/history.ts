/* Chat history persistence (STAGE 1 decision): browser-only localStorage.
   The mockup marked persistence as NEEDS DECISION between localStorage and new
   /api/chats endpoints; the decision is localStorage, so the thread survives a
   reload, is scoped per user, keeps the last 20 turns and is cleared on sign
   out. Every access is wrapped in try/catch: a disabled or full localStorage
   must never break chat. */

export type ChatTurn = { role: "user" | "assistant"; content: string };
export type ChatSession = { id: string; title: string; snippet: string; ts: number; turns: ChatTurn[] };

const MAX_TURNS = 20;
const MAX_SESSIONS = 20;

function keyFor(email: string): string {
  return `urumi.chat.${email || "anon"}`;
}

function readSessions(email: string): ChatSession[] {
  try {
    const raw = localStorage.getItem(keyFor(email));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (s): s is ChatSession =>
        !!s && typeof s === "object" && typeof (s as ChatSession).id === "string" && typeof (s as ChatSession).title === "string",
    ).map((s) => ({ ...s, turns: Array.isArray(s.turns) ? s.turns.filter((t) => t && (t.role === "user" || t.role === "assistant") && typeof t.content === "string") : [] }));
  } catch {
    return [];
  }
}

function writeSessions(email: string, sessions: ChatSession[]): void {
  try {
    localStorage.setItem(keyFor(email), JSON.stringify(sessions.slice(0, MAX_SESSIONS)));
  } catch {
    /* storage disabled or full: history is best-effort, never blocking */
  }
}

export function loadHistory(email: string): ChatSession[] {
  return readSessions(email);
}

export function clearHistory(email: string): void {
  try {
    localStorage.removeItem(keyFor(email));
  } catch {
    /* ignore */
  }
}

export function saveSession(email: string, turns: ChatTurn[]): ChatSession[] {
  const firstUser = turns.find((t) => t.role === "user");
  const firstAssistant = turns.find((t) => t.role === "assistant");
  const title = (firstUser?.content || "New chat").slice(0, 60);
  const snippet = (firstAssistant?.content || "").replace(/\s+/g, " ").slice(0, 80);
  const next: ChatSession[] = [
    { id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, title, snippet, ts: Date.now(), turns: turns.slice(0, MAX_TURNS) },
    ...readSessions(email),
  ].slice(0, MAX_SESSIONS);
  writeSessions(email, next);
  return next;
}

export const CHAT_MAX_TURNS = MAX_TURNS;
