import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

export default function Members() {
  const { user } = useAuth();
  const [users, setUsers] = useState<{ id: string; email: string; role: string; is_active: boolean }[]>([]);
  const [keys, setKeys] = useState<{ id: string; user_id: string; prefix: string; last4: string; revoked_at: string | null; created_at: string }[]>([]);
  const [err, setErr] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState("member");
  const [lastKey, setLastKey] = useState<string | null>(null);

  async function load() {
    setErr("");
    try {
      // /api/users is admin-only: a member requesting it gets 403, which used to
      // fail this whole load() and hide the member's own keys behind an error.
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
    await load();
  }

  async function createKey() {
    setLastKey(null);
    const res = await api.createKey();
    setLastKey(res.key);
    await load();
  }

  const isAdmin = user?.role === "admin";

  return (
    <div>
      <h2>Members & API keys</h2>
      {err && <div className="alert alert-error">{err}</div>}

      <h3>Users</h3>
      <table className="table">
        <thead>
          <tr>
            <th>Email</th>
            <th>Role</th>
            <th>Active</th>
            {isAdmin && <th>Actions</th>}
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>{u.email}</td>
              <td>{u.role}</td>
              <td>{u.is_active ? "yes" : "no"}</td>
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
          ))}
        </tbody>
      </table>

      {isAdmin && (
        <form onSubmit={createUser} className="card row gap wrap">
          <input placeholder="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} />
          <input placeholder="password (≥8)" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
          <select value={newRole} onChange={(e) => setNewRole(e.target.value)}>
            <option value="member">member</option>
            <option value="admin">admin</option>
          </select>
          <button type="submit">Invite / Create</button>
        </form>
      )}

      <h3>API keys</h3>
      <p className="muted small">Keys are shown once at creation. Store them safely.</p>
      {lastKey && (
        <div className="alert alert-success">
          <div>New key (copy now — shown once):</div>
          <code className="mono break">{lastKey}</code>
        </div>
      )}
      <button onClick={createKey}>Create API key for me</button>
      <table className="table">
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
              <td>{!k.revoked_at && <button className="danger small" onClick={() => revokeKey(k.id)}>Revoke</button>}</td>
            </tr>
          ))}
          {keys.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
                No keys yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
