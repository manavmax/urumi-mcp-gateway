import { useEffect, useState } from "react";
import { api, type Server, type Tool } from "../lib/api";
import { useAuth } from "../lib/auth";
import { StatusBadge } from "../components/StatusBadge";
import { ServerForm, type ServerFormValues } from "../components/ServerForm";

export default function Servers() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [servers, setServers] = useState<Server[]>([]);
  const [tools, setTools] = useState<Record<string, Tool[]>>({});
  const [err, setErr] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<Server | null>(null);

  async function load() {
    setErr("");
    try {
      const res = await api.listServers();
      setServers(res.servers);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function loadTools(slug: string) {
    try {
      const res = await api.listTools();
      // group by server_slug if present, else show all
      const grouped: Record<string, Tool[]> = {};
      for (const t of res.tools) {
        const key = (t as unknown as { server_slug?: string }).server_slug || (t.name.includes("__") ? t.name.split("__")[0] : "unknown");
        (grouped[key] ||= []).push(t);
      }
      setTools(grouped);
      // toggle display: if already open for this slug, close; else keep
      if (tools[slug]?.length) {
        const copy = { ...tools };
        delete copy[slug];
        setTools(copy);
      } else {
        setTools(grouped);
      }
    } catch {
      // silent
    }
  }

  async function handleCreate(v: ServerFormValues) {
    const payload: Record<string, unknown> = {
      slug: v.slug,
      url: v.url,
      auth_type: v.auth_type,
      timeout_ms: v.timeout_ms,
      enabled: v.enabled,
    };
    if (v.auth_type === "header") payload.header_name = v.header_name;
    if (v.credential) payload.credential = v.credential;
    await api.createServer(payload);
    setShowAdd(false);
    await load();
  }

  async function handleUpdate(v: ServerFormValues) {
    if (!editing) return;
    const payload: Record<string, unknown> = {
      slug: v.slug,
      url: v.url,
      auth_type: v.auth_type,
      timeout_ms: v.timeout_ms,
      enabled: v.enabled,
    };
    if (v.auth_type === "header") payload.header_name = v.header_name;
    if (v.credential) payload.credential = v.credential;
    await api.updateServer(editing.id, payload);
    setEditing(null);
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

  return (
    <div>
      <div className="row between">
        <h2>Servers</h2>
        {isAdmin ? (
          <button onClick={() => setShowAdd(true)}>Add server</button>
        ) : (
          <span className="muted small">Only admins can add or modify servers</span>
        )}
      </div>
      {err && <div className="alert alert-error">{err}</div>}

      {showAdd && isAdmin && (
        <div className="card">
          <h3>Add server</h3>
          <ServerForm onSubmit={handleCreate} onCancel={() => setShowAdd(false)} submitLabel="Create" />
        </div>
      )}
      {editing && isAdmin && (
        <div className="card">
          <h3>Edit {editing.slug}</h3>
          <ServerForm
            initial={{
              slug: editing.slug,
              url: editing.url,
              auth_type: editing.auth_type,
              header_name: editing.header_name || "",
              credential: "",
              timeout_ms: editing.timeout_ms,
              enabled: editing.enabled,
            }}
            onSubmit={handleUpdate}
            onCancel={() => setEditing(null)}
          />
        </div>
      )}

      <table className="table">
        <thead>
          <tr>
            <th>Slug</th>
            <th>URL</th>
            <th>Status</th>
            <th>Enabled</th>
            <th>Tools</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {servers.map((s) => (
            <tr key={s.id}>
              <td>{s.slug}</td>
              <td className="mono small">{s.url}</td>
              <td>
                <StatusBadge status={s.status} />
                {s.last_error && <div className="small muted">{s.last_error.slice(0, 120)}</div>}
              </td>
              <td>
                {isAdmin ? (
                  <label className="switch">
                    <input
                      type="checkbox"
                      checked={s.enabled}
                      onChange={() => toggleEnable(s)}
                    />
                    <span>{s.enabled ? "yes" : "no"}</span>
                  </label>
                ) : (
                  <span>{s.enabled ? "yes" : "no"}</span>
                )}
              </td>
              <td>
                <button className="secondary small" onClick={() => loadTools(s.slug)}>
                  {tools[s.slug] ? `Hide (${tools[s.slug].length})` : "Show tools"}
                </button>
                {tools[s.slug] && (
                  <div className="tool-list">
                    {tools[s.slug].map((t) => (
                      <div key={t.name} className="tool-chip">
                        <span className="mono">{t.name}</span>
                        {t.description && <span className="muted small"> — {t.description.slice(0, 80)}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </td>
              <td className="row gap">
                {isAdmin ? (
                  <>
                    <button className="secondary small" onClick={() => setEditing(s)}>
                      Edit
                    </button>
                    <button className="danger small" onClick={() => remove(s)}>
                      Delete
                    </button>
                  </>
                ) : (
                  <span className="muted small">Admin only</span>
                )}
              </td>
            </tr>
          ))}
          {servers.length === 0 && (
            <tr>
              <td colSpan={6} className="muted">
                No servers yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
