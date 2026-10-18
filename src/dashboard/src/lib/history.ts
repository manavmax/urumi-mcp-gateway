/* Chat thread persistence (FIX PASS F1-4): browser-only localStorage, per user.
   One thread per conversation, not one entry per message: sending continues the
   ACTIVE thread, "New chat" (or opening the chat page) starts a new one. A
   thread is titled by its first user message, carries the updated time and the
   message count, and keeps the last turns; the store keeps the last 20 threads
   per user and is cleared on sign out. LLM error turns are never stored (the
   UI shows errors inline instead). Every access is wrapped in try/catch: a
   disabled or full localStorage must never break chat. */

export type ChatTurn = { role: "user" | "assistant"; content: string };
export type ChatThread = { id: string; title: string; snippet: string; ts: number; count: number; turns: ChatTurn[] };

const MAX_TURNS = 40;
const MAX_THREADS = 20;
/* Prior-context cap for the API call: last 10 turns (user+assistant text only)
   plus a total character cap so a long thread cannot balloon the request. */
export const MAX_CONTEXT_TURNS = 10;
export const MAX_CONTEXT_CHARS = 12000;

function keyFor(email: string): string {
  return `urumi.chat.${email || "anon"}`;
}

function readThreads(email: string): ChatThread[] {
  try {
    const raw = localStorage.getItem(keyFor(email));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((t): t is ChatThread => !!t && typeof t === "object" && typeof (t as ChatThread).id === "string" && typeof (t as ChatThread).title === "string")
      .map((s) => ({
        ...s,
        ts: typeof s.ts === "number" ? s.ts : 0,
        count: typeof s.count === "number" ? s.count : (Array.isArray(s.turns) ? s.turns.length : 0),
        turns: (Array.isArray(s.turns) ? s.turns : []).filter(
          (t) => t && (t.role === "user" || t.role === "assistant") && typeof t.content === "string",
        ),
      }));
  } catch {
    return [];
  }
}

function writeThreads(email: string, threads: ChatThread[]): void {
  try {
    localStorage.setItem(keyFor(email), JSON.stringify(threads.slice(0, MAX_THREADS)));
  } catch {
    /* storage disabled or full: history is best-effort, never blocking */
  }
}

export function loadHistory(email: string): ChatThread[] {
  return readThreads(email);
}

export function clearHistory(email: string): void {
  try {
    localStorage.removeItem(keyFor(email));
  } catch {
    /* ignore */
  }
}

function lastAssistantText(turns: ChatTurn[]): string {
  for (let i = turns.length - 1; i >= 0; i--) {
    const t = turns[i];
    if (t && t.role === "assistant" && t.content.trim()) return t.content;
  }
  return "";
}

/* Save one exchange into a thread. With threadId the turns APPEND to that
   thread (it moves to the top with a fresh updated time); with null a new
   thread starts, titled by its first user message. The title never becomes an
   LLM error string: error turns are not handed to this function, the UI shows
   them inline instead. */
export function saveThread(email: string, threadId: string | null, turns: ChatTurn[]): { id: string; threads: ChatThread[] } {
  const clean = turns.filter((t) => t && (t.role === "user" || t.role === "assistant") && typeof t.content === "string" && t.content.trim());
  const existing = readThreads(email);
  const prior = threadId ? existing.find((t) => t.id === threadId) : undefined;
  const all = prior ? [...prior.turns, ...clean] : clean;
  const id = threadId && prior ? threadId : `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const firstUser = all.find((t) => t.role === "user");
  const thread: ChatThread = {
    id,
    // title stays the FIRST user message, never an LLM error string
    title: (prior?.title || firstUser?.content || "New chat").slice(0, 60),
    snippet: (lastAssistantText(all) || prior?.snippet || "").replace(/\s+/g, " ").slice(0, 80),
    ts: Date.now(),
    count: all.length,
    turns: all.slice(-MAX_TURNS),
  };
  const next: ChatThread[] = [{ ...thread }, ...existing.filter((t) => t.id !== id)].slice(0, MAX_THREADS);
  writeThreads(email, next);
  return { id, threads: next };
}

/* Build the payload for the chat API from the visible thread: user and
   assistant text only (tool chips never go back), at most MAX_CONTEXT_TURNS
   turns and MAX_CONTEXT_CHARS characters, so a long thread cannot flood the
   request while the model still sees the recent context. */
export function chatPayloadTurns(turns: ChatTurn[]): ChatTurn[] {
  const kept = turns.length > MAX_TURNS ? turns.slice(-MAX_TURNS) : turns.slice();
  const out: ChatTurn[] = [];
  let size = 0;
  for (let i = kept.length - 1; i >= 0; i--) {
    const t = kept[i];
    const sizeNext = size + t.content.length;
    if (out.length >= MAX_CONTEXT_TURNS || sizeNext > MAX_CONTEXT_CHARS) break;
    size = sizeNext;
    out.unshift({ role: t.role, content: t.content });
  }
  return out;
}

export const CHAT_MAX_TURNS = MAX_TURNS;
