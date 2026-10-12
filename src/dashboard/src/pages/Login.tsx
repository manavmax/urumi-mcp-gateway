import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("admin@urumi.local");
  const [password, setPassword] = useState("admin123");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      await login(email, password);
      nav("/", { replace: true });
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center">
      <form onSubmit={submit} className="card login-card">
        <h1>Urumi — Sign in</h1>
        <p className="muted">Use the admin seeded by the gateway (admin@urumi.local / admin123 on local).</p>
        {err && <div className="alert alert-error">{err}</div>}
        <label>
          Email
          <input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}
