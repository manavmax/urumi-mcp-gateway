// Fetch wrapper that always sends cookies + CSRF header when we have it.
let csrfToken = "";

export function setCsrf(token: string) {
  csrfToken = token;
}
export function getCsrf() {
  return csrfToken;
}

type ApiOpts = RequestInit & { csrf?: boolean };

async function request<T>(path: string, opts: ApiOpts = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(opts.headers as Record<string, string> | undefined),
  };
  if (opts.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  if (opts.csrf !== false && csrfToken && opts.method && opts.method !== "GET") {
    headers["X-CSRF-Token"] = csrfToken;
  }
  const res = await fetch(path, {
    ...opts,
    headers,
    credentials: "include",
  });
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    const detail =
      typeof body === "object" && body !== null && "detail" in (body as Record<string, unknown>)
        ? String((body as Record<string, unknown>).detail)
        : typeof body === "string"
          ? body
          : res.statusText;
    throw Object.assign(new Error(detail), { status: res.status, body });
  }
  if (res.status === 204) return undefined as unknown as T;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json() as Promise<T>;
  return res.text() as unknown as T;
}

// ---- typed helpers ----
export type Me = { user: { id: string; email: string; role: string }; csrf_token: string };
export type Server = {
  id: string;
  slug: string;
  url: string;
  auth_type: string;
  header_name: string | null;
  credential: string | null;
  enabled: boolean;
  status: string;
  last_error: string | null;
  timeout_ms: number;
  created_at: string;
  updated_at: string;
  /* observability (docs/11_OBSERVABILITY.md) - admins only; members never get them */
  last_checked_at?: string | null;
  last_ok_at?: string | null;
  last_latency_ms?: number | null;
  last_error_category?: string | null;
};
export type Tool = {
  name: string;
  description?: string;
  inputSchema?: unknown;
  server_slug?: string;
};
export type PermissionTool = {
  name: string;
  description?: string;
  member_denied: boolean;
};
export type PermissionServer = {
  slug: string;
  enabled: boolean;
  status: string;
  tools: PermissionTool[];
};
export type AuditRow = {
  id: number;
  ts: string;
  user_id: string | null;
  user_email?: string | null;
  api_key_id: string | null;
  server_slug: string;
  tool_exposed_name: string;
  tool_upstream_name: string;
  request_id: string;
  duration_ms: number;
  outcome: string;
  error_code: string | null;
  client_ip: string | null;
};

/* GET /api/stats (new with the Overview page). Admin scope sees every user's
   calls; a member only ever sees their own, enforced server-side. */
export type StatsRange = "day" | "week" | "month" | "14d";
export type StatsDayPoint = { date: string; calls: number; errors: number; p95_ms: number };
export type Stats = {
  range: string;
  window_days: number;
  audit: {
    calls: number;
    prev_calls: number;
    success: number;
    errors: number;
    success_rate: number | null;
    p50_ms: number;
    p95_ms: number;
    per_day: StatsDayPoint[];
  };
  own_keys_active?: number;
  own_api_key_calls?: number;
  own_calls_total?: number;
};
export type ApiKeyRow = {
  id: string;
  user_id: string;
  prefix: string;
  last4: string;
  revoked_at: string | null;
  expires_at: string | null;
  created_at: string;
};

export const api = {
  me: () => request<Me>("/api/me"),
  login: (email: string, password: string) =>
    request<Me>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST", csrf: true }),

  listServers: () => request<{ servers: Server[] }>("/api/servers"),
  createServer: (data: Record<string, unknown>) =>
    request<Server>("/api/servers", { method: "POST", body: JSON.stringify(data), csrf: true }),
  updateServer: (id: string, data: Record<string, unknown>) =>
    request<Server>(`/api/servers/${id}`, { method: "PATCH", body: JSON.stringify(data), csrf: true }),
  deleteServer: (id: string) =>
    request<void>(`/api/servers/${id}`, { method: "DELETE", csrf: true }),
  enableServer: (id: string) =>
    request<Server>(`/api/servers/${id}/enable`, { method: "POST", csrf: true }),
  disableServer: (id: string) =>
    request<Server>(`/api/servers/${id}/disable`, { method: "POST", csrf: true }),
  /* Admin "Check now": immediate health probe of one server, rate limited server-side. */
  checkServer: (id: string) =>
    request<Server>(`/api/servers/${id}/check`, { method: "POST", csrf: true }),

  listUsers: () => request<{ users: { id: string; email: string; role: string; is_active: boolean; created_at: string }[] }>("/api/users"),
  createUser: (data: { email: string; password: string; role: string }) =>
    request<{ id: string; email: string; role: string }>("/api/users", {
      method: "POST",
      body: JSON.stringify(data),
      csrf: true,
    }),
  deleteUser: (id: string) => request<void>(`/api/users/${id}`, { method: "DELETE", csrf: true }),

  listKeys: () => request<{ keys: ApiKeyRow[] }>("/api/keys"),
  createKey: () =>
    request<{ id: string; key: string; prefix: string; last4: string; created_at: string }>("/api/keys", {
      method: "POST",
      body: JSON.stringify({}),
      csrf: true,
    }),
  revokeKey: (id: string) => request<{ revoked: boolean }>(`/api/keys/${id}`, { method: "DELETE", csrf: true }),

  listTools: () => request<{ tools: Tool[]; warnings: string[] }>("/api/tools"),

  /* Per-role tool permissions (admin only; members get 403 server-side).
     GET returns servers + tools with member-denied flags; PUT replaces the member
     deny policy and is CSRF-protected by the wrapper. */
  listPermissions: () => request<{ servers: PermissionServer[]; restricted_count: number }>("/api/permissions"),
  putPermissions: (rules: { server_slug: string; tool_name: string | null }[]) =>
    request<{ servers: PermissionServer[]; restricted_count: number }>("/api/permissions", {
      method: "PUT",
      body: JSON.stringify({ rules }),
      csrf: true,
    }),

  /* Overview aggregates (new endpoint, admin/member scoping enforced server-side). */
  stats: (range?: StatsRange) =>
    request<Stats>(`/api/stats${range ? `?range=${encodeURIComponent(range)}` : ""}`),

  /* Admin-only CSV export of the current audit filters. The server enforces the
     role check and hard-caps the export at 5000 rows; the browser just saves the
     attachment. */
  exportAuditCsv: async (params: Record<string, string | number | undefined> = {}): Promise<void> => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
    const res = await fetch(`/api/audit/export${qs.toString() ? `?${qs.toString()}` : ""}`, {
      credentials: "include",
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(body.slice(0, 300) || res.statusText);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "audit-export.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  listAudit: (params: Record<string, string | number | undefined>) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
    const q = qs.toString();
    return request<{ logs: AuditRow[]; total: number; limit: number; offset: number }>(`/api/audit${q ? `?${q}` : ""}`);
  },

  // Chat SSE: caller handles EventSource/fetch stream
  chatCompletions: (messages: { role: string; content: string }[]) =>
    fetch("/api/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
      credentials: "include",
      body: JSON.stringify({ messages }),
    }),
};
