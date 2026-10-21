/* Stores (Phase 5): per-user storefronts provisioned by the provisioner into
   their own namespaces. Members see their own; admins see all. Create asks for
   a display name (the slug is derived server-side); delete confirms inline.
   The list polls every 3s while any store is Provisioning or Deleting so the
   status badge (colour + icon + text, never colour alone) moves live. */
import { useEffect, useRef, useState } from "react";
import { api, type StoreRow } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Topbar } from "../components/Topbar";
import { Icon } from "../components/icons";

function statusChip(status: StoreRow["status"]): { cls: string; icon: "clock" | "check-circle" | "alert" | "x-circle" } {
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

export default function Stores() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [stores, setStores] = useState<StoreRow[]>([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const alive = useRef(true);

  async function load() {
    try {
      const data = await api.listStores();
      if (!alive.current) return;
      setStores(data.stores);
      setErr("");
    } catch (e) {
      if (alive.current) setErr(e instanceof Error ? e.message : String(e));
    } finally {
      if (alive.current) setLoading(false);
    }
  }

  useEffect(() => {
    alive.current = true;
    load();
    return () => {
      alive.current = false;
    };
  }, []);

  // poll while anything is in flight
  const inFlight = stores.some((s) => s.status === "Provisioning" || s.status === "Deleting");
  useEffect(() => {
    if (!inFlight) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [inFlight]);

  async function create() {
    setErr("");
    setBusy(true);
    try {
      await api.createStore(name.trim());
      setName("");
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
      await api.deleteStore(id);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function retry(id: string) {
    setErr("");
    setBusy(true);
    try {
      await api.retryStore(id);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Topbar />
      <main className="content">
        <div className="page-head">
          <div>
            <h1>Stores</h1>
          </div>
          <div className="row wrap">
            <span className="src">one namespace per store · tools are {"<slug>__…"}</span>
          </div>
        </div>
        {err && (
          <div className="note-banner" role="alert">
            {err}
          </div>
        )}
        <section className="card" aria-label="Create a store">
          <div className="card-head">
            <h3 className="card-title">New store</h3>
          </div>
          <div className="row wrap">
            <input
              type="text"
              placeholder="Store name (e.g. Bangalore branch)"
              value={name}
              maxLength={60}
              aria-label="Store name"
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && name.trim() && !busy) void create();
              }}
            />
            <button className="btn btn-primary" type="button" disabled={!name.trim() || busy} onClick={() => void create()}>
              Create store
            </button>
          </div>
          <div className="small muted">
            Provisioning takes a couple of minutes (WordPress + MariaDB + WooCommerce setup). Your store gets its own
            namespace, its own host at {"<slug>"}.localhost, and its tools appear as {"<slug>__list_orders"}.
          </div>
        </section>
        <section className="card" aria-label="Stores">
          <div className="card-head">
            <h3 className="card-title">{isAdmin ? "All stores" : "Your stores"}</h3>
          </div>
          {loading ? (
            <div className="empty">Loading stores...</div>
          ) : stores.length === 0 ? (
            <div className="empty">No stores yet.</div>
          ) : (
            <div className="table-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Slug</th>
                    <th>Status</th>
                    <th>Storefront</th>
                    <th>Created</th>
                    {isAdmin && <th>Owner</th>}
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {stores.map((s) => {
                    const chip = statusChip(s.status);
                    const mine = isAdmin || s.owner_user_id === undefined;
                    return (
                      <tr key={s.id}>
                        <td>{s.display_name}</td>
                        <td className="mono">{s.slug}</td>
                        <td>
                          <span className={`chip ${chip.cls}`}>
                            <Icon name={chip.icon} />
                            {s.status}
                          </span>
                          {s.status === "Failed" && s.failure_reason && (
                            <div className="small muted">{s.failure_reason}</div>
                          )}
                        </td>
                        <td>
                          {s.status === "Ready" && s.url ? (
                            <a href={s.url} target="_blank" rel="noreferrer" className="mono">
                              {s.url.replace("http://", "")}
                            </a>
                          ) : (
                            <span className="small muted">—</span>
                          )}
                        </td>
                        <td className="small muted">{fmtDate(s.created_at)}</td>
                        {isAdmin && <td className="small mono">{s.owner_email || "—"}</td>}
                        <td>
                          {s.status === "Failed" && (
                            <>
                              <button className="btn btn-secondary btn-sm" type="button" disabled={busy} onClick={() => void retry(s.id)}>
                                Retry
                              </button>
                            </>
                          )}
                          {confirmId === s.id ? (
                            <span className="row">
                              <button className="btn btn-danger btn-sm" type="button" disabled={busy} onClick={() => void remove(s.id)}>
                                Confirm delete
                              </button>
                              <button className="btn btn-secondary btn-sm" type="button" onClick={() => setConfirmId(null)}>
                                Cancel
                              </button>
                            </span>
                          ) : s.status !== "Deleting" ? (
                            <button className="btn btn-danger btn-sm" type="button" disabled={busy} onClick={() => setConfirmId(s.id)}>
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
