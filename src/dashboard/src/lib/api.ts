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
  // FormData must keep the browser-generated multipart boundary header.
  if (opts.body && !headers["Content-Type"] && !(opts.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
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
export type AdminEventRow = {
  id: number;
  ts: string;
  actor_user_id: string | null;
  actor_email: string | null;
  action: string;
  target_type: string;
  target_ref: string;
  outcome: string;
  details: Record<string, unknown>;
};

/* GET /api/stats (new with the Overview page). Admin scope sees every user's
   calls; a member only ever sees their own, enforced server-side. */
export type StatsRange = "day" | "week" | "month" | "14d";
export type StatsDayPoint = { date: string; calls: number; errors: number; p95_ms: number };
export type ServerStatSpark = { date: string; calls: number; errors: number };
export type ServerStat = {
  server: string;
  calls: number;
  errors: number;
  error_rate: number | null;
  p50_ms: number;
  p95_ms: number;
  sparkline: ServerStatSpark[];
};
export type FailureReason = { reason: string; count: number };
export type AuditMetricsRow = {
  server: string;
  calls: number;
  errors: number;
  error_rate: number | null;
  p50_ms: number;
  p95_ms: number;
  top_failures: FailureReason[];
};
export type AuditMetrics = { window_hours: number; servers: AuditMetricsRow[] };
export type StoreRow = {
  id: string;
  slug: string;
  display_name: string;
  namespace: string;
  status: "Provisioning" | "Ready" | "Failed" | "Deleting";
  failure_reason: string | null;
  url: string | null;
  created_at: string;
  updated_at: string;
  owner_user_id?: string;
  owner_email?: string | null;
};
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
  /* admin only - members never receive by_server (docs/11_OBSERVABILITY.md §2) */
  by_server?: ServerStat[];
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
  rate_limit_per_minute: number | null;
  created_at: string;
};

export type AdminAlert = {
  slug: string;
  kind: string;
  status: string;
  category: string | null;
  reason: string;
  unreachable_since: string | null;
  calls_1h?: number;
  errors_1h?: number;
};
export type AlertsPayload = { admin: AdminAlert[] } | { member: { slugs: string[] } };

/* Notification bell items (FIX PASS F1-6): computed server-side from existing
   data; shape is id, kind, severity, title, short detail, at, href. Members
   only ever receive their own items; no key material ever appears. */
export type NotificationItem = {
  id: string;
  kind: string;
  severity: "critical" | "warning" | "info";
  title: string;
  detail: string;
  at: string;
  href: string;
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
  /* Look up a server by slug to get its id for checkServer (alerts carry slug only). */
  checkServerBySlug: async (slug: string) => {
    const res = await request<{ servers: Server[] }>("/api/servers");
    const srv = res.servers.find((s) => s.slug === slug);
    if (!srv) throw new Error(`server ${slug} not found`);
    return request<Server>(`/api/servers/${srv.id}/check`, { method: "POST", csrf: true });
  },

  /* Next-best-action banner state (docs/11_OBSERVABILITY.md §3). */
  alerts: () => request<AlertsPayload>("/api/alerts"),

  /* Notification bell items (FIX PASS F1-6). */
  listNotifications: () => request<{ notifications: NotificationItem[] }>("/api/notifications"),

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
  // Admin per-key rate limit override (ADR-057): null clears back to the default.
  updateKeyLimit: (id: string, perMinute: number | null) =>
    request<{ id: string; rate_limit_per_minute: number | null }>(`/api/keys/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ rate_limit_per_minute: perMinute }),
      csrf: true,
    }),

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

  listAdminEvents: (params: Record<string, string | number | undefined> = {}) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
    const q = qs.toString();
    return request<{ events: AdminEventRow[]; total: number; limit: number; offset: number }>(`/api/admin-events${q ? `?${q}` : ""}`);
  },

  // Metrics page: per-server 24h aggregates computed from the audit table
  // (admin-only server-side; members get 403). No Prometheus server needed.
  auditMetrics: () => request<AuditMetrics>("/api/metrics"),

  // Stores (Phase 5): members manage their own, admins manage all. Polling
  // while any store is Provisioning/Deleting happens on the page.
  listStores: () => request<{ stores: StoreRow[] }>("/api/stores"),
  createStore: (displayName: string) =>
    request<StoreRow>("/api/stores", { method: "POST", body: JSON.stringify({ display_name: displayName }), csrf: true }),
  deleteStore: (id: string) =>
    request<{ id: string; status: string }>(`/api/stores/${id}`, { method: "DELETE", csrf: true }),
  retryStore: (id: string) =>
    request<{ id: string; status: string }>(`/api/stores/${id}/retry`, { method: "POST", csrf: true }),

  // Chat SSE: caller handles the fetch stream. tz = the browser's IANA
  // timezone (FIX PASS F1-8): the server validates it and puts the user's
  // local date/time into the system prompt so "today" means the user's today.
  // F3: a message's content may be a part list when the turn carries an upload
  // reference — the gateway resolves + expands it server-side; the browser never
  // persists image bytes (history stores only an "[image]" placeholder).
  chatCompletions: (messages: { role: string; content: string | ChatContentPart[] }[], tz?: string) =>
    fetch("/api/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
      credentials: "include",
      body: JSON.stringify(tz ? { messages, tz } : { messages }),
    }),

  // F3: multipart upload (csrf-protected, rate limited 10/min server-side).
  // Returns the server's owner-bound upload id, valid for 15 minutes.
  uploadChatImage: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<ChatUploadResult>("/api/chat/uploads", {
      method: "POST",
      body: fd,
      csrf: true,
    });
  },
};

export type ChatUploadResult = { upload_id: string; mime: string; size: number; expires_at: string };
export type ChatContentPart =
  | { type: "text"; text: string }
  | { type: "image_upload"; upload_id: string };
