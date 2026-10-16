/* Servers, exact port of design/mockups/servers.html (family F) with real data
   from GET /api/servers and GET /api/tools. Admin CRUD (add/edit/delete,
   enable/disable) is unchanged; the mockup's Admin/Member view switcher and
   SAMPLE DATA chip are mockup-only chrome and are not shipped (see the STAGE 1
   report), the role comes from the signed-in session. Admins also get the
   tool-permissions panel (GET/PUT /api/permissions): tools grouped by server,
   Admin column locked on, Member toggle, one Save button. */
import { useEffect, useMemo, useState } from "react";
import { api, type PermissionServer, type Server, type Tool } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSearch } from "../lib/search";
import { useMockupMotion } from "../lib/motion";
import { Topbar } from "../components/Topbar";
import { ServerForm, type ServerFormValues } from "../components/ServerForm";
import { Icon } from "../components/icons";

const STATUS_CHIP = (status: string): { cls: string; icon: "check-circle" | "x-circle" | "pause" | "dot" } => {
  if (status === "Connected") return { cls: "chip-ok", icon: "check-circle" };
  if (status === "Unreachable") return { cls: "chip-danger", icon: "x-circle" };
  if (status === "Disabled") return { cls: "chip-warn", icon: "pause" };
  return { cls: "chip-neutral", icon: "dot" };
};

/* Health-detail line for the admin Servers row: "<category>, checked X ago,
   last ok Y ago, Z ms" with unknown parts omitted. Category human labels come
   from the server-safe label (last_error). */
function relative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs} s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

function healthLine(s: Server): string {
  const parts: string[] = [];
  if (s.last_error_category) parts.push(s.last_error || s.last_error_category);
  if (s.last_checked_at) parts.push(`checked ${relative(s.last_checked_at)}`);
  if (s.last_ok_at) parts.push(`last ok ${relative(s.last_ok_at)}`);
  if (typeof s.last_latency_ms === "number") {
    parts.push(s.last_latency_ms >= 1000 ? `${(s.last_latency_ms / 1000).toFixed(1)} s` : `${s.last_latency_ms} ms`);
  }
  return parts.join(", ");
}

export default function Servers() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { query } = useSearch();
  const [servers, setServers] = useState<Server[]>([]);
  const [tools, setTools] = useState<Record<string, Tool[]>>({});
  const [filter, setFilter] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState<null | { mode: "add" } | { mode: "edit"; server: Server }>(null);
  const [permOpen, setPermOpen] = useState(false);
  const [perm, setPerm] = useState<PermissionServer[]>([]);
  const [permCount, setPermCount] = useState(0);
  const [permDraft, setPermDraft] = useState<Record<string, boolean>>({});
  const [permLoading, setPermLoading] = useState(false);
  const [permSaving, setPermSaving] = useState(false);
  const [permSaved, setPermSaved] = useState(false);
  const [permErr, setPermErr] = useState("");
  const [checkingId, setCheckingId] = useState<string | null>(null);
  const [checkError, setCheckError] = useState("");

  /* member tool access draft: true = allowed, false = restricted (denied) */
  function draftFromPayload(servers: PermissionServer[]) {
    const draft: Record<string, boolean> = {};
    for (const s of servers) for (const t of s.tools) draft[t.name] = !t.member_denied;
    return draft;
  }

  async function openPermissions() {
    setPermErr("");
    setPermSaved(false);
    setPermOpen(true);
    setPermLoading(true);
    try {
      const res = await api.listPermissions();
      setPerm(res.servers);
      setPermCount(res.restricted_count);
      setPermDraft(draftFromPayload(res.servers));
    } catch (e: unknown) {
      setPermErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPermLoading(false);
    }
  }

  async function savePermissions() {
    setPermSaving(true);
    setPermErr("");
    try {
      const rules: { server_slug: string; tool_name: string | null }[] = [];
      for (const s of perm) {
        const denied = s.tools.filter((t) => permDraft[t.name] === false);
        if (s.tools.length > 0 && denied.length === s.tools.length) {
          rules.push({ server_slug: s.slug, tool_name: null });
        } else {
          for (const t of denied) rules.push({ server_slug: s.slug, tool_name: t.name });
        }
      }
      const res = await api.putPermissions(rules);
      setPerm(res.servers);
      setPermCount(res.restricted_count);
      setPermDraft(draftFromPayload(res.servers));
      setPermSaved(true);
      setTimeout(() => setPermSaved(false), 2500);
    } catch (e: unknown) {
      setPermErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPermSaving(false);
    }
  }

  async function load() {
    setErr("");
    setLoading(true);
    try {
      const res = await api.listServers();
      setServers(res.servers);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  useMockupMotion(loading);

  async function toggleTools(slug: string) {
    if (tools[slug]) {
      const copy = { ...tools };
      delete copy[slug];
      setTools(copy);
      return;
    }
    try {
      const res = await api.listTools();
      const grouped: Record<string, Tool[]> = {};
      for (const t of res.tools) {
        const key = t.server_slug || (t.name.includes("__") ? t.name.split("__")[0] : "unknown");
        (grouped[key] ||= []).push(t);
      }
      setTools(grouped);
    } catch {
      /* tools stay collapsed when the probe fails */
    }
  }

  async function handleCreate(v: ServerFormValues) {
    const payload: Record<string, unknown> = {
      slug: v.slug, url: v.url, auth_type: v.auth_type, timeout_ms: v.timeout_ms, enabled: v.enabled,
    };
    if (v.auth_type === "header") payload.header_name = v.header_name;
    if (v.credential) payload.credential = v.credential;
    await api.createServer(payload);
    setModal(null);
    await load();
  }

  async function handleUpdate(v: ServerFormValues) {
    if (!modal || modal.mode !== "edit") return;
    const payload: Record<string, unknown> = {
      slug: v.slug, url: v.url, auth_type: v.auth_type, timeout_ms: v.timeout_ms, enabled: v.enabled,
    };
    if (v.auth_type === "header") payload.header_name = v.header_name;
    if (v.credential) payload.credential = v.credential;
    await api.updateServer(modal.server.id, payload);
    setModal(null);
    await load();
  }

  async function toggleEnable(s: Server) {
    if (s.enabled) await api.disableServer(s.id);
    else await api.enableServer(s.id);
    await load();
  }

  async function remove(s: Server) {
    if (!confirm(`Delete server ${s.slug}?`)) return;
    await api.deleteServer(s.id);
    await load();
  }

  async function checkNow(s: Server) {
    if (checkingId) return;
    setCheckingId(s.id);
    setCheckError("");
    try {
      await api.checkServer(s.id);
      await load();
    } catch (e: unknown) {
      setCheckError(e instanceof Error ? e.message : String(e));
      await load();
    } finally {
      setCheckingId(null);
    }
  }

  const counts = useMemo(() => {
    let connected = 0, unreachable = 0, unknown = 0, disabled = 0;
    for (const s of servers) {
      if (!s.enabled) disabled += 1;
      else if (s.status === "Connected") connected += 1;
      else if (s.status === "Unreachable") unreachable += 1;
      else unknown += 1;
    }
    return { connected, unreachable, unknown, disabled };
  }, [servers]);

  /* the topbar search and the card filter both narrow the table client-side */
  const q = (query + " " + filter).trim().toLowerCase();
  const rows = q
    ? servers.filter((s) => `${s.slug} ${s.url} ${s.status}`.toLowerCase().includes(q))
    : servers;

  return (
    <>
      <Topbar />
      <main className="content">
        <div className="page-head">
          <div>
            <h1>Servers</h1>
          </div>
          <div className="row wrap">
            {isAdmin && (
              <button className="btn btn-secondary" type="button" onClick={openPermissions}>
                <Icon name="lock" sm />Permissions
              </button>
            )}
            {isAdmin && (
              <button className="btn btn-primary" type="button" onClick={() => setModal({ mode: "add" })}>
                <Icon name="plus" sm />Add server
              </button>
            )}
          </div>
        </div>

        {err && <div className="alert alert-error" role="alert">{err}</div>}
        {checkError && <div className="alert alert-error" role="alert">{checkError}</div>}

        {/* summary */}
        <section className="card" style={{ display: "flex", gap: "var(--s4)", alignItems: "center", flexWrap: "wrap", justifyContent: "space-between" }}>
          <div className="row wrap" style={{ gap: "var(--s3)" }}>
            <span className="card-title" style={{ fontSize: "var(--t-md)" }}><Icon name="server" />{servers.length} registered</span>
            <span className="chip chip-ok"><Icon name="check-circle" />{counts.connected} connected</span>
            <span className="chip chip-danger"><Icon name="x-circle" />{counts.unreachable} unreachable</span>
            <span className="chip chip-neutral"><Icon name="dot" />{counts.unknown} unknown</span>
            <span className="chip chip-warn"><Icon name="pause" />{counts.disabled} disabled</span>
          </div>
        </section>

        {/* table */}
        <section className="card">
          <div className="card-head">
            <div className="card-title"><Icon name="server" />All servers</div>
            <label className="search" style={{ maxWidth: 280, padding: "6px 14px" }}>
              <Icon name="search" sm />
              <input type="search" placeholder="Filter by slug or URL…" aria-label="Filter servers"
                style={{ fontSize: "var(--t-sm)" }} value={filter} onChange={(e) => setFilter(e.target.value)} />
            </label>
          </div>
          <div className="table-wrap">
            <table aria-label="Servers">
              <thead>
                <tr>
                  <th>Server</th><th>Status</th><th>Enabled</th><th>Tools</th>{isAdmin && <th>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr>
                    <td colSpan={isAdmin ? 5 : 4}><span className="sk" style={{ width: "40%" }} /></td>
                  </tr>
                )}
                {!loading && rows.length === 0 && (
                  <tr>
                    <td colSpan={isAdmin ? 5 : 4}>
                      <span className="small muted">{servers.length === 0 ? "No servers registered yet." : "No servers match the filter."}</span>
                    </td>
                  </tr>
                )}
                {rows.map((s) => {
                  const st = STATUS_CHIP(!s.enabled ? "Disabled" : s.status);
                  const list = tools[s.slug];
                  return (
                    <tr key={s.id}>
                      <td data-label="Server">
                        <div className="slug">{s.slug}</div>
                        <div className="url">{s.url}</div>
                        {isAdmin && healthLine(s) && <div className="url health-line" data-health-line>{healthLine(s)}</div>}
                      </td>
                      <td data-label="Status">
                        <span className={`chip ${st.cls}`}><Icon name={st.icon} />{!s.enabled ? "Disabled" : s.status}</span>
                      </td>
                      <td data-label="Enabled">
                        {isAdmin ? (
                          <label className="switch">
                            <input type="checkbox" checked={s.enabled} onChange={() => toggleEnable(s)} aria-label={`Enable ${s.slug}`} />
                            <span className="track"></span>
                            <span className="lbl">{s.enabled ? "yes" : "no"}</span>
                          </label>
                        ) : (
                          <span className="small muted">{s.enabled ? "yes" : "no"}</span>
                        )}
                      </td>
                      <td data-label="Tools">
                        {list ? (
                          <details className="tools" open>
                            <summary>{list.length} tools<Icon name="chevron" /></summary>
                            <div className="tool-list">
                              {list.map((t) => (
                                <div className="tool-item" key={t.name}>
                                  <span className="mono">{t.name}</span>
                                  {t.description && <span>: {t.description.slice(0, 90)}</span>}
                                </div>
                              ))}
                            </div>
                          </details>
                        ) : (
                          <details className="tools">
                            <summary onClick={(e) => { e.preventDefault(); toggleTools(s.slug); }}>Show tools<Icon name="chevron" /></summary>
                          </details>
                        )}
                      </td>
                      {isAdmin && (
                        <td data-label="Actions">
                          <div className="row" style={{ justifyContent: "flex-end" }}>
                            <button className="btn btn-secondary btn-sm" type="button" disabled={checkingId !== null} onClick={() => checkNow(s)}>
                              <Icon name="dot" sm />{checkingId === s.id ? "Checking..." : "Check now"}
                            </button>
                            <button className="btn btn-secondary btn-sm" type="button" onClick={() => setModal({ mode: "edit", server: s })}>
                              <Icon name="edit" sm />Edit
                            </button>
                            <button className="btn btn-danger btn-sm" type="button" onClick={() => remove(s)}>
                              <Icon name="trash" sm />Delete
                            </button>
                          </div>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      </main>

      {permOpen && isAdmin && (
        <div className="modal-back open" onClick={(e) => { if (e.target === e.currentTarget) setPermOpen(false); }}>
          <div className="modal" role="dialog" aria-modal="true" aria-label="Tool permissions" style={{ maxWidth: 720 }}>
            <div className="card-head" style={{ margin: 0 }}>
              <div className="row wrap" style={{ justifyContent: "space-between", width: "100%" }}>
                <div className="card-title"><Icon name="lock" />Permissions</div>
                <span className="chip chip-neutral"><Icon name="deny" />{permCount} restricted for members</span>
              </div>
              <button className="btn btn-ghost btn-sm" type="button" onClick={() => setPermOpen(false)}>Close</button>
            </div>
            {permErr && <div className="alert alert-error" role="alert">{permErr}</div>}
            {permLoading && (
              <span className="sk" style={{ width: "60%" }} />
            )}
            {!permLoading && perm.map((s) => (
              <div key={s.slug} style={{ borderTop: "1px solid var(--hairline)", paddingTop: "var(--s3)" }}>
                <div className="row" style={{ justifyContent: "space-between", marginBottom: 4 }}>
                  <div className="card-title" style={{ fontSize: "var(--t-sm)" }}><Icon name="server" />{s.slug}</div>
                  <span className={`chip ${STATUS_CHIP(!s.enabled ? "Disabled" : s.status).cls}`}>
                    <Icon name={STATUS_CHIP(!s.enabled ? "Disabled" : s.status).icon} />{!s.enabled ? "Disabled" : s.status}
                  </span>
                </div>
                <div className="table-wrap">
                  <table aria-label={`Member tool access for ${s.slug}`}>
                    <thead>
                      <tr>
                        <th>Tool</th><th>Admin</th><th>Member</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s.tools.map((t) => (
                        <tr key={t.name}>
                          <td data-label="Tool">
                            <span className="mono">{t.name}</span>
                            {t.description && <div className="small muted">{t.description.slice(0, 90)}</div>}
                          </td>
                          <td data-label="Admin">
                            <span className="small muted"><Icon name="lock" sm />all tools</span>
                          </td>
                          <td data-label="Member">
                            <label className="switch">
                              <input
                                type="checkbox"
                                checked={permDraft[t.name] !== false}
                                onChange={(e) => setPermDraft({ ...permDraft, [t.name]: e.target.checked })}
                                aria-label={`Member may use ${t.name}`}
                              />
                              <span className="track"></span>
                              <span className="lbl">{permDraft[t.name] === false ? "no" : "yes"}</span>
                            </label>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
            <div className="card-head" style={{ margin: 0 }}>
              <div className="row" style={{ justifyContent: "flex-end", gap: "var(--s3)", width: "100%" }}>
                {permSaved && <span className="chip chip-ok"><Icon name="check-circle" />Policy saved</span>}
                <button className="btn btn-primary" type="button" disabled={permSaving || permLoading} onClick={savePermissions}>
                  {permSaving ? "Saving..." : "Save"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      {modal?.mode === "add" && isAdmin && (
        <div className="modal-back open" onClick={(e) => { if (e.target === e.currentTarget) setModal(null); }}>
          <div className="modal" role="dialog" aria-modal="true" aria-label="Add server">
            <div className="card-head" style={{ margin: 0 }}>
              <div className="card-title"><Icon name="server" />Add server</div>
              <button className="btn btn-ghost btn-sm" type="button" onClick={() => setModal(null)}>Close</button>
            </div>
            <ServerForm onSubmit={handleCreate} onCancel={() => setModal(null)} submitLabel="Create server" />
          </div>
        </div>
      )}
      {modal?.mode === "edit" && isAdmin && (
        <div className="modal-back open" onClick={(e) => { if (e.target === e.currentTarget) setModal(null); }}>
          <div className="modal" role="dialog" aria-modal="true" aria-label={`Edit ${modal.server.slug}`}>
            <div className="card-head" style={{ margin: 0 }}>
              <div className="card-title"><Icon name="server" />Edit {modal.server.slug}</div>
              <button className="btn btn-ghost btn-sm" type="button" onClick={() => setModal(null)}>Close</button>
            </div>
            <ServerForm
              initial={{
                slug: modal.server.slug,
                url: modal.server.url,
                auth_type: modal.server.auth_type,
                header_name: modal.server.header_name || "",
                credential: "",
                timeout_ms: modal.server.timeout_ms,
                enabled: modal.server.enabled,
              }}
              onSubmit={handleUpdate}
              onCancel={() => setModal(null)}
            />
          </div>
        </div>
      )}
    </>
  );
}
