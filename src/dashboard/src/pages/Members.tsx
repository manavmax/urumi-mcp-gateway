/* Members and keys, exact port of design/mockups/members.html (family F) with
   real data from GET /api/users, GET /api/keys and GET /api/me. Admins see
   every user and every key (owner email resolved from /api/users); members see
   only their own keys, exactly as the mockup's note-banner describes. The
   mockup's Admin/Member view switcher and SAMPLE DATA chip are mockup-only
   chrome and are not shipped; the role comes from the signed-in session. */
import { useEffect, useMemo, useState } from "react";
import { api, type ApiKeyRow } from "../lib/api";
import { useAuth } from "../lib/auth";
import { initials, useSearch } from "../lib/search";
import { useMockupMotion } from "../lib/motion";
import { Topbar } from "../components/Topbar";
import { Icon } from "../components/icons";

type UserRow = { id: string; email: string; role: string; is_active: boolean; created_at: string };

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export default function Members() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { query } = useSearch();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [emailById, setEmailById] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState("member");
  const [lastKey, setLastKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function load() {
    setErr("");
    setLoading(true);
    try {
      const k = await api.listKeys();
      setKeys(k.keys);
      if (isAdmin) {
        const u = await api.listUsers();
        setUsers(u.users);
        setEmailById(Object.fromEntries(u.users.map((x) => [x.id, x.email])));
      } else {
        setUsers([]);
        setEmailById({});
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useMockupMotion(loading);

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
    setErr("");
    try {
      const res = await api.createKey();
      setLastKey(res.key);
      setCopied(false);
      await load();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  const activeKeys = useMemo(() => keys.filter((k) => !k.revoked_at), [keys]);
  const revokedKeys = useMemo(() => keys.filter((k) => k.revoked_at), [keys]);
  const adminCount = useMemo(() => users.filter((u) => u.role === "admin").length, [users]);
  const memberCount = users.length - adminCount;

  /* the topbar search narrows both tables client-side */
  const q = query.trim().toLowerCase();
  const matches = (text: string) => !q || text.toLowerCase().includes(q);
  const shownUsers = q ? users.filter((u) => matches(u.email)) : users;
  const shownKeys = q
    ? keys.filter((k) => matches(`${emailById[k.user_id] || ""} ${k.prefix} ${k.last4}`))
    : keys;

  return (
    <>
      <Topbar />
      <main className="content">
        <div className="page-head">
          <div>
            <h1>Members &amp; keys</h1>
          </div>
          <div className="row wrap">
            {isAdmin && (
              <button className="btn btn-primary" type="button" onClick={() => document.getElementById("iv-email")?.focus()}>
                <Icon name="plus" sm />Invite member
              </button>
            )}
          </div>
        </div>

        {err && <div className="alert alert-error" role="alert">{err}</div>}

        {/* stats */}
        <section className="grid-4" aria-label="Membership summary">
          {isAdmin && (
            <div className="card stat">
              <div className="stat-label">Members</div>
              <div className="stat-num">{loading ? <span className="sk num" style={{ width: 60 }} /> : users.length}</div>
              <div className="stat-foot">
                <span className="chip chip-accent"><Icon name="users" />{adminCount} admin · {memberCount} members</span>
              </div>
            </div>
          )}
          {isAdmin && (
            <div className="card stat">
              <div className="stat-label">Active accounts</div>
              <div className="stat-num">{users.filter((u) => u.is_active).length} <span className="stat-unit">of {users.length}</span></div>
              <div className="stat-foot">
                <span className="chip chip-neutral"><Icon name="dot" />{users.filter((u) => !u.is_active).length} deactivated</span>
              </div>
            </div>
          )}
          {!isAdmin && (
            <div className="card stat">
              <div className="stat-label">Your role</div>
              <div className="stat-num" style={{ fontSize: 26 }}>Member</div>
              <div className="stat-foot"><span className="chip chip-accent">can chat · audit own rows · own keys</span></div>
            </div>
          )}
          <div className="card stat">
            <div className="stat-label">API keys</div>
            <div className="stat-num">{activeKeys.length} <span className="stat-unit">active</span></div>
            <div className="stat-foot">
              <span className="chip chip-neutral"><Icon name="pause" />{revokedKeys.length} revoked</span>
            </div>
          </div>
          <div className="card stat">
            <div className="stat-label">Key storage</div>
            <div className="stat-num" style={{ fontSize: 26 }}>SHA-256</div>
            <div className="stat-foot"><span className="chip chip-accent"><Icon name="lock" />raw key shown once</span></div>
          </div>
        </section>

        {/* users (admin) */}
        {isAdmin && (
          <section className="card">
            <div className="card-head">
              <div>
                <div className="card-title"><Icon name="users" />Users</div>
              </div>
            </div>
            <form className="invite" onSubmit={createUser}>
              <div className="field" style={{ flex: 2 }}>
                <label htmlFor="iv-email">Email</label>
                <input id="iv-email" type="email" placeholder="new.member@urumi.local" required
                  value={newEmail} onChange={(e) => setNewEmail(e.target.value)} />
              </div>
              <div className="field" style={{ flex: 2 }}>
                <label htmlFor="iv-pw">Password (≥ 8)</label>
                <input id="iv-pw" type="password" placeholder="••••••••" required minLength={8}
                  value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
              </div>
              <div className="field" style={{ flex: 1, minWidth: 120 }}>
                <label htmlFor="iv-role">Role</label>
                <select id="iv-role" value={newRole} onChange={(e) => setNewRole(e.target.value)}>
                  <option value="member">member</option>
                  <option value="admin">admin</option>
                </select>
              </div>
              <button className="btn btn-primary" type="submit"><Icon name="plus" sm />Invite / create</button>
            </form>
            <table aria-label="Users">
              <thead>
                <tr><th>Email</th><th>Role</th><th>Since</th><th>Active</th><th>Actions</th></tr>
              </thead>
              <tbody>
                {shownUsers.map((u) => (
                  <tr key={u.id}>
                    <td data-label="Email">
                      <div className="row">
                        <div className="avatar" style={{ width: 28, height: 28, fontSize: 10 }}>{initials(u.email)}</div>
                        <span className="email mono">{u.email}</span>
                      </div>
                    </td>
                    <td data-label="Role">
                      <span className={`chip ${u.role === "admin" ? "chip-accent" : "chip-neutral"}`}>
                        {u.role === "admin" && <Icon name="shield" />}{u.role}
                      </span>
                    </td>
                    <td data-label="Since" className="small muted">{fmtDate(u.created_at)}</td>
                    <td data-label="Active" className="small">{u.is_active ? "yes" : "no"}</td>
                    <td data-label="Actions">
                      {u.id === user?.id ? (
                        <span className="small muted" title="cannot delete self">this is you</span>
                      ) : (
                        <button className="btn btn-danger btn-sm" type="button"
                          onClick={async () => {
                            if (!confirm(`Delete ${u.email}?`)) return;
                            await api.deleteUser(u.id);
                            await load();
                          }}>
                          <Icon name="trash" sm />Delete
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {!loading && shownUsers.length === 0 && (
                  <tr><td colSpan={5}><span className="small muted">No users match the filter.</span></td></tr>
                )}
              </tbody>
            </table>
          </section>
        )}

        {/* keys */}
        <section className="card">
          <div className="card-head">
            <div>
              <div className="card-title"><Icon name="key" />{isAdmin ? "API keys" : "Your API keys"}</div>
              <div className="card-sub">Keys are shown once at creation.</div>
            </div>
            <button className="btn btn-primary" type="button" onClick={createKey}>
              <Icon name="plus" sm />{isAdmin ? "Create API key" : "Create key for me"}
            </button>
          </div>

          {lastKey && (
            <div className="reveal">
              <div className="row"><Icon name="lock" style={{ color: "var(--primary-hover)" }} /><b>New key: copy now, shown once</b></div>
              <div className="row">
                <div className="keybox"><code>{lastKey}</code></div>
                <button className="btn btn-secondary" type="button"
                  onClick={async () => {
                    if (!lastKey) return;
                    await navigator.clipboard.writeText(lastKey);
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1400);
                  }}>
                  <Icon name="copy" sm />{copied ? "Copied" : "Copy"}
                </button>
              </div>
              <div className="small muted">This key will not be shown again. Store it in your secret manager, the gateway only keeps a SHA-256 digest.</div>
            </div>
          )}

          <table aria-label="API keys">
            <thead>
              <tr>
                {isAdmin && <th>Owner</th>}
                <th>Prefix</th><th>Last4</th><th>Created</th><th>Expires</th><th>Status</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {shownKeys.map((k) => (
                <tr key={k.id}>
                  {isAdmin && <td data-label="Owner" className="small mono">{emailById[k.user_id] || k.user_id.slice(0, 8)}</td>}
                  <td data-label="Prefix" className="mono-cell">{k.prefix}</td>
                  <td data-label="Last4" className="mono-cell">…{k.last4}</td>
                  <td data-label="Created" className="small muted">{fmtDate(k.created_at)}</td>
                  <td data-label="Expires" className="small muted">{k.expires_at ? fmtDate(k.expires_at) : "never"}</td>
                  <td data-label="Status">
                    {k.revoked_at ? (
                      <span className="chip chip-neutral"><Icon name="pause" />Revoked</span>
                    ) : (
                      <span className="chip chip-ok"><Icon name="check-circle" />Active</span>
                    )}
                  </td>
                  <td data-label="Actions">
                    {!k.revoked_at ? (
                      <button className="btn btn-danger btn-sm" type="button" onClick={() => revokeKey(k.id)}>
                        <Icon name="pause" sm />Revoke
                      </button>
                    ) : (
                      <span className="small muted">none</span>
                    )}
                  </td>
                </tr>
              ))}
              {!loading && shownKeys.length === 0 && (
                <tr>
                  <td colSpan={isAdmin ? 7 : 6}><span className="small muted">No keys yet. Create one for API access via /mcp.</span></td>
                </tr>
              )}
            </tbody>
          </table>
          <div className="small faint" style={{ marginTop: "var(--s3)" }}>
            Revoking is permanent: callers using the key get 401 on <span className="mono">/mcp</span>.
          </div>
        </section>
      </main>
    </>
  );
}
