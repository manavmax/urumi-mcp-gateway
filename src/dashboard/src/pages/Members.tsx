import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { TableWrap } from "../components/ui/Table";
import { EmptyState, InlineError, LoadingRows } from "../components/ui/EmptyState";
import { Modal } from "../components/ui/Modal";

function CopyBox({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="copybox">
      <code className="mono small break flex1">{value}</code>
      <button
        className="secondary small"
        onClick={async () => {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1400);
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

export default function Members() {
  const { user } = useAuth();
  const [users, setUsers] = useState<{ id: string; email: string; role: string; is_active: boolean }[]>([]);
  const [keys, setKeys] = useState<{ id: string; user_id: string; prefix: string; last4: string; revoked_at: string | null; created_at: string }[]>([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState("member");
  const [lastKey, setLastKey] = useState<string | null>(null);
  const [revokeId, setRevokeId] = useState<string | null>(null);

  async function load() {
    setErr("");
    setLoading(true);
    try {
      const k = await api.listKeys();
      setKeys(k.keys);
      if (user?.role === "admin") {
        const u = await api.listUsers();
        setUsers(u.users);
      } else {
        setUsers([]);
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function createUser(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    try {
      await api.createUser({ email: newEmail, password: newPassword, role: newRole });
      setNewEmail("");
      setNewPassword("");
      await load();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function revokeKey(id: string) {
    await api.revokeKey(id);
    setRevokeId(null);
    await load();
  }

  async function createKey() {
    setLastKey(null);
    const res = await api.createKey();
    setLastKey(res.key);
    await load();
  }

  const isAdmin = user?.role === "admin";
  const revokeKeyMeta = revokeId ? keys.find((k) => k.id === revokeId) : null;

  return (
    <div className="stack">
      <div className="page-head">
        <h2>Members & API keys</h2>
        <span className="small muted">Invite members, manage API keys</span>
      </div>

      {err && <InlineError message={err} onRetry={load} />}

      <h3 style={{ margin: "8px 0 0" }}>Users</h3>
      {loading ? (
        <div className="card"><LoadingRows rows={3} /></div>
      ) : (
        <TableWrap>
          <table className="table" aria-label="Users">
            <thead>
              <tr>
                <th>Email</th>
                <th>Role</th>
                <th>Active</th>
                {isAdmin && <th>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {users.length === 0 && !isAdmin ? (
                <tr><td colSpan={isAdmin ? 4 : 3}><EmptyState title="No users listed" hint="Members cannot list users — only admins can." /></td></tr>
              ) : users.length === 0 ? (
                <tr><td colSpan={4} className="muted small">No users yet.</td></tr>
              ) : (
                users.map((u) => (
                  <tr key={u.id}>
                    <td className="mono small">{u.email}</td>
                    <td><span className="small" style={{ textTransform: "capitalize" }}>{u.role}</span></td>
                    <td className="small">{u.is_active ? "yes" : "no"}</td>
                    {isAdmin && (
                      <td>
                        <button
                          className="danger small"
                          disabled={u.id === user?.id}
                          onClick={async () => {
                            if (!confirm(`Delete ${u.email}?`)) return;
                            await api.deleteUser(u.id);
                            await load();
                          }}
                        >
                          Delete
                        </button>
                      </td>
                    )}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </TableWrap>
      )}

      {isAdmin && (
        <form onSubmit={createUser} className="card row gap wrap" aria-label="Invite user">
          <input placeholder="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} aria-label="New user email" />
          <input placeholder="password (≥8)" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} aria-label="New user password" />
          <select value={newRole} onChange={(e) => setNewRole(e.target.value)} aria-label="Role">
            <option value="member">member</option>
            <option value="admin">admin</option>
          </select>
          <button type="submit">Invite / Create</button>
        </form>
      )}

      <h3 style={{ margin: "8px 0 0" }}>API keys</h3>
      <p className="small muted" style={{ margin: 0 }}>Keys are shown once at creation. Store them safely.</p>
      {lastKey && (
        <div className="card" style={{ borderColor: "#065f46", background: "#06261e" }}>
          <div className="small" style={{ fontWeight: 800, color: "#a7f3d0", marginBottom: 8 }}>New key — copy now, shown once</div>
          <div className="alert alert-info" style={{ marginTop: 0 }}>This key will not be shown again. Copy it now and store it safely.</div>
          <CopyBox value={lastKey} />
          <div className="row gap" style={{ marginTop: 10 }}>
            <button className="ghost small" onClick={() => setLastKey(null)}>Dismiss</button>
          </div>
        </div>
      )}
      <div className="row gap">
        <button onClick={createKey}>Create API key for me</button>
        <span className="small muted">Creates a key for your own user</span>
      </div>

      <TableWrap>
        <table className="table" aria-label="API keys">
          <thead>
            <tr>
              <th>Prefix</th>
              <th>Last4</th>
              <th>Created</th>
              <th>Revoked</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.id}>
                <td className="mono small">{k.prefix}</td>
                <td className="mono small">…{k.last4}</td>
                <td className="small">{new Date(k.created_at).toLocaleString()}</td>
                <td className="small">{k.revoked_at ? new Date(k.revoked_at).toLocaleString() : "—"}</td>
                <td>{!k.revoked_at && <button className="danger small" onClick={() => setRevokeId(k.id)}>Revoke</button>}</td>
              </tr>
            ))}
            {keys.length === 0 && (
              <tr>
                <td colSpan={5}><EmptyState title="No keys yet" hint="Create one for API access via /mcp." /></td>
              </tr>
            )}
          </tbody>
        </table>
      </TableWrap>

      <Modal open={!!revokeId} onClose={() => setRevokeId(null)} title="Revoke API key?">
        <p className="small muted">Revoke key <span className="mono">{revokeKeyMeta ? `${revokeKeyMeta.prefix}…${revokeKeyMeta.last4}` : revokeId}</span>? This cannot be undone — callers using it will get 401.</p>
        <div className="row gap" style={{ justifyContent: "flex-end", marginTop: 12 }}>
          <button className="ghost small" onClick={() => setRevokeId(null)}>Cancel</button>
          <button className="danger" onClick={() => revokeId && revokeKey(revokeId)}>Revoke key</button>
        </div>
      </Modal>
    </div>
  );
}
