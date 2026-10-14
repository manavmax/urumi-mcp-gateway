import { NavLink, Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./lib/auth";
import Login from "./pages/Login";
import Servers from "./pages/Servers";
import Members from "./pages/Members";
import Audit from "./pages/Audit";
import Chat from "./pages/Chat";

function Shell() {
  const { user, logout } = useAuth();
  return (
    <div className="layout">
      <nav className="sidebar" aria-label="Primary">
        <div className="brand">Urumi</div>
        <NavLink to="/servers">Servers</NavLink>
        <NavLink to="/members">Members & Keys</NavLink>
        <NavLink to="/audit">Audit</NavLink>
        <NavLink to="/chat">Chat</NavLink>
        <div className="spacer" />
        <div className="userbox">
          <div className="small mono break">{user?.email}</div>
          <div className="small muted" style={{ textTransform: "capitalize" }}>{user?.role}</div>
          <button className="secondary small" onClick={logout}>
            Sign out
          </button>
        </div>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/servers" replace />} />
          <Route path="/servers" element={<Servers />} />
          <Route path="/members" element={<Members />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/chat" element={<Chat />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <div className="center muted">Loading…</div>;
  if (!user) return <Login />;
  return <Shell />;
}
