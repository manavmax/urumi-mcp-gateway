/* Hosted servers (Phase 6, ADR-062): admin adds an MCP server BY CONTAINER
   IMAGE. The provisioner deploys it into its own namespace (no SA token,
   read-only rootfs, capped resources, gateway-only ingress) and the gateway
   registers it as an internal upstream (tools appear as <name>__*). Env values
   are sent once and never returned — the table shows only env NAMES. The list
   polls every 3s while anything is Provisioning/Deleting; status chips pair
   colour with an icon + text. */
import { useEffect, useRef, useState } from "react";
import { api, type HostedRow } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Topbar } from "../components/Topbar";
import { Icon } from "../components/icons";
import { FeatureDisabled } from "../components/FeatureDisabled";

function statusChip(status: HostedRow["status"]): { cls: string; icon: "clock" | "check-circle" | "alert" | "x-circle" } {
  switch (status) {
    case "Ready":
      return { cls: "chip-ok", icon: "check-circle" };
    case "Provisioning":
      return { cls: "chip-warn", icon: "clock" };
    case "Failed":
      return { cls: "chip-danger", icon: "x-circle" };
    case "Deleting":
      return { cls: "chip-neutral", icon: "clock" };
  }
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function Hosted() {
  const { user, features } = useAuth();
  const isAdmin = user?.role === "admin";
  /* RC: with hostedServers disabled the page must not fire API calls (403 by
     design) - show the friendly panel instead, with zero console noise. All
     hooks run unconditionally; the early return sits below them. */
  const disabled = !features.hosted;
  const [rows, setRows] = useState<HostedRow[]>([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", image: "", port: "8000", envText: "" });
  const alive = useRef(true);

  async function load() {
    try {
      const data = await api.listHosted();
      if (!alive.current) return;
      setRows(data.hosted);
      setErr("");
    } catch (e) {
      if (alive.current) setErr(e instanceof Error ? e.message : String(e));
    } finally {
      if (alive.current) setLoading(false);
    }
  }

  useEffect(() => {
    if (disabled) return;
    alive.current = true;
    load();
    return () => {
      alive.current = false;
    };
  }, [disabled]);

  const inFlight = rows.some((r) => r.status === "Provisioning" || r.status === "Deleting");
  useEffect(() => {
    if (!inFlight) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [inFlight]);

  async function create() {
    setErr("");
    setBusy(true);
    try {
      const env: Record<string, string> = {};
      for (const line of form.envText.split("\n")) {
        const t = line.trim();
        if (!t) continue;
        const eq = t.indexOf("=");
        if (eq <= 0) throw new Error(`env line needs NAME=value: ${t}`);
        env[t.slice(0, eq).trim()] = t.slice(eq + 1);
      }
      await api.createHosted({
        name: form.name.trim(),
        image: form.image.trim(),
        port: Number(form.port) || 8000,
        env,
      });
      setForm({ name: "", image: "", port: "8000", envText: "" });
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setErr("");
    setBusy(true);
    setConfirmId(null);
    try {
      await api.deleteHosted(id);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const canCreate = isAdmin && form.name.trim() && form.image.trim() && !busy;

  if (disabled) {
    return (
      <FeatureDisabled
        title="Hosted servers"
        icon="server"
        enableHint="An administrator enables hosted MCP servers on the gateway with: helm upgrade --set hostedServers.enabled=true (admins can then host upstreams from a container image here)."
      />
    );
  }

  return (
    <>
      <Topbar />
      <main className="content">
        <div className="page-head">
          <div>
            <h1>Hosted servers</h1>
          </div>
        </div>
        {err && (
          <div className="note-banner" role="alert">
            {err}
          </div>
        )}
        <section className="card" aria-label="Add a hosted server">
          <div className="card-head">
            <h3 className="card-title">Host a server from an image</h3>
          </div>
          {isAdmin ? (
            <>
              <div className="row wrap">
                <div className="field">
                  <label htmlFor="hosted-name">Name</label>
                  <input
                    id="hosted-name"
                    type="text"
                    placeholder="e.g. time2"
                    value={form.name}
                    maxLength={30}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                  />
                </div>
                <div className="field grow">
                  <label htmlFor="hosted-image">Container image</label>
                  <input
                    id="hosted-image"
                    type="text"
                    placeholder="registry/repo:tag — :latest refused"
                    value={form.image}
                    maxLength={200}
                    onChange={(e) => setForm({ ...form, image: e.target.value })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="hosted-port">Port</label>
                  <input
                    id="hosted-port"
                    type="number"
                    placeholder="8080"
                    value={form.port}
                    min={1}
                    max={65535}
                    onChange={(e) => setForm({ ...form, port: e.target.value })}
                  />
                </div>
                <button className="btn btn-primary" type="button" disabled={!canCreate} onClick={() => void create()}>
                  Host server
                </button>
              </div>
              <div className="row wrap">
                <div className="field grow">
                  <label htmlFor="hosted-env">Environment variables (optional)</label>
                  <textarea
                    id="hosted-env"
                    placeholder={"one NAME=value per line — values are never shown again"}
                    value={form.envText}
                    rows={2}
                    onChange={(e) => setForm({ ...form, envText: e.target.value })}
                  />
                </div>
              </div>
            </>
          ) : (
            <div className="small muted">Admins only.</div>
          )}
        </section>
        <section className="card" aria-label="Hosted servers">
          <div className="card-head">
            <h3 className="card-title">Servers</h3>
          </div>
          {loading ? (
            <div className="empty">Loading hosted servers...</div>
          ) : rows.length === 0 ? (
            <div className="empty">No hosted servers yet.</div>
          ) : (
            <div className="table-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Image</th>
                    <th>Port</th>
                    <th>Env</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((h) => {
                    const chip = statusChip(h.status);
                    return (
                      <tr key={h.id}>
                        <td className="mono">{h.name}</td>
                        <td className="mono small">{h.image}</td>
                        <td className="mono">{h.port}</td>
                        <td className="small muted">
                          {h.env_names.length ? h.env_names.map((n) => <span key={n} className="mono">{n} </span>) : "—"}
                        </td>
                        <td>
                          <span className={`chip ${chip.cls}`}>
                            <Icon name={chip.icon} />
                            {h.status}
                          </span>
                          {h.status === "Failed" && h.failure_reason && (
                            <div className="small muted">{h.failure_reason}</div>
                          )}
                        </td>
                        <td className="small muted">{fmtDate(h.created_at)}</td>
                        <td>
                          {confirmId === h.id ? (
                            <span className="row">
                              <button className="btn btn-danger btn-sm" type="button" disabled={busy} onClick={() => void remove(h.id)}>
                                Confirm delete
                              </button>
                              <button className="btn btn-secondary btn-sm" type="button" onClick={() => setConfirmId(null)}>
                                Cancel
                              </button>
                            </span>
                          ) : h.status !== "Deleting" ? (
                            <button className="btn btn-danger btn-sm" type="button" disabled={busy} onClick={() => setConfirmId(h.id)}>
                              <Icon name="x-circle" sm />Delete
                            </button>
                          ) : (
                            <span className="small muted">deleting…</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </>
  );
}
