/* Sign in, exact port of design/mockups/login.html: soft gradient glow
   background (gradient use c) with three drifting pastel shapes, a 440px white
   card with 40px padding and 24px radius, stacked logo block (mark, "Urumi"
   wordmark, muted "Gateway" beneath, left aligned per the STAGE 1 acceptance
   contract), full-width ink pill button with the check icon, centered footer
   line and the bottom-left tagline. */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { Icon } from "../components/icons";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("admin@urumi.local");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    if (!email.trim() || !password) {
      setErr("Enter email and password.");
      return;
    }
    setBusy(true);
    try {
      await login(email.trim(), password);
      nav("/overview", { replace: true });
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stage">
      {/* three drifting pastel shapes (login art, gradient use c); the mockup
          defines no glow element, so the port ships exactly these three */}
      <div className="shape arch drift-a" aria-hidden="true" style={SHAPES.arch} />
      <div className="shape drift-b" aria-hidden="true" style={SHAPES.lilac} />
      <div className="shape drift-c" aria-hidden="true" style={SHAPES.peach} />

      <p className="tagline" aria-hidden="true">
        One gateway for every tool your team uses.
      </p>

      <form onSubmit={submit} className="login-card" aria-label="Sign in">
        <div className="login-logo">
          <span className="mark-40" style={{ color: "var(--text)", display: "inline-flex" }}>
            <Icon name="logo" size={40} />
          </span>
          <div className="wordmark">
            Urumi
            <span className="sub">Gateway</span>
          </div>
        </div>
        <h1>Sign in</h1>
        <p className="helper">Use your workspace account to reach the gateway console.</p>

        <div className={`alert${err ? " on" : ""}`} role="alert">
          <Icon name="alert" sm />
          <span>{err || "Invalid email or password."}</span>
        </div>

        <div className="field">
          <label htmlFor="email">Email</label>
          <input id="email" type="email" autoComplete="username" placeholder="admin@urumi.local"
            value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="pw">Password</label>
          <input id="pw" type="password" autoComplete="current-password" placeholder="••••••••••••"
            value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>

        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
          <Icon name="check" sm />
        </button>

        <p className="foot">Access is managed by your administrator</p>
      </form>
    </div>
  );
}

/* Login art: soft tinted shapes drifting slowly behind the glow. */
const SHAPES: Record<string, React.CSSProperties> = {
  arch: {
    top: "8%", right: "6%", width: 220, height: 200, opacity: 0.35,
    borderRadius: "44% 44% 8% 8% / 60% 60% 6% 6%",
    background: "var(--grad-a)",
  },
  lilac: {
    top: "58%", left: "4%", width: 300, height: 300, opacity: 0.45,
    borderRadius: "50%", background: "var(--lilac)",
  },
  peach: {
    top: "12%", left: "18%", width: 120, height: 120, opacity: 0.4,
    borderRadius: "50%", background: "var(--peach)",
  },
};
