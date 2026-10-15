/* Servers, exact port of design/mockups/servers.html (family F) with real data
   from GET /api/servers and GET /api/tools. Admin CRUD (add/edit/delete,
   enable/disable) is unchanged; the mockup's Admin/Member view switcher and
   SAMPLE DATA chip are mockup-only chrome and are not shipped (see the STAGE 1
   report), the role comes from the signed-in session. */
import { useEffect, useMemo, useState } from "react";
import { api, type Server, type Tool } from "../lib/api";
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
              <button className="btn btn-primary" type="button" onClick={() => setModal({ mode: "add" })}>
                <Icon name="plus" sm />Add server
              </button>
            )}
          </div>
        </div>

        {!isAdmin && (
          <div className="note-banner">
            <Icon name="eye" />
            <div>
              <b>Viewing as member.</b> Only admins can add, edit, enable/disable or delete servers, the controls below are
              hidden for this role. <span className="src">GET /api/servers · role from /api/me</span>
            </div>
          </div>
        )}

        {err && <div className="alert alert-error" role="alert">{err}</div>}

        {/* summary */}
        <section className="card" style={{ display: "flex", gap: "var(--s4)", alignItems: "center", flexWrap: "wrap", justifyContent: "space-between" }}>
          <div className="row wrap" style={{ gap: "var(--s3)" }}>
            <span className="card-title" style={{ fontSize: "var(--t-md)" }}><Icon name="server" />{servers.length} registered</span>
            <span className="chip chip-ok"><Icon name="check-circle" />{counts.connected} connected</span>
            <span className="chip chip-danger"><Icon name="x-circle" />{counts.unreachable} unreachable</span>
            <span className="chip chip-neutral"><Icon name="dot" />{counts.unknown} unknown</span>
            <span className="chip chip-warn"><Icon name="pause" />{counts.disabled} disabled</span>
          </div>
          <span className="src">GET /api/servers, counted client-side, no new endpoint</span>
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
                        {s.last_error && <div className="err">last error: {s.last_error.slice(0, 160)}</div>}
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
