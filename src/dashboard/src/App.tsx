/* App shell: exact port of the STAGE 0.6 mockups. The floating pill sidebar is
   shared; each page owns its own header, exactly as the mockups render them:
   overview/chat carry the search pill in the page head, servers/members/audit
   carry the sticky topbar with search, bell and account menu. RBAC and routes
   are unchanged; "/" lands on the new Overview ("/overview").

   FIX 1: The /overview route chooses the admin Overview or member OverviewMember
   based on role, so the member sees a distinct page scoped to their own data
   (no team-wide numbers). Both share the same visual system and bento layout. */
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./lib/auth";
import { SearchProvider } from "./lib/search";
import { ThemeProvider } from "./lib/theme";
import { Sidebar, BottomNav } from "./components/Nav";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import OverviewMember from "./pages/OverviewMember";
import Servers from "./pages/Servers";
import Members from "./pages/Members";
import Audit from "./pages/Audit";
import Metrics from "./pages/Metrics";
import Chat from "./pages/Chat";

/* Servers, members and audit use the fleet layout (fam-f): 1280px content,
   24/32/48px gutters, 16px gaps, sticky topbar. Overview and chat use the
   family O layout (1240px, 32px gutters, 20px gaps) exactly as their mockups.
   The pg-* class carries the per-page mockup CSS (servers.html pads table
   cells 12px where members/audit pad them 11px 12px). */
function familyOf(pathname: string): string {
  const base = pathname === "/servers" || pathname === "/members" || pathname === "/audit" || pathname === "/metrics" ? "fam-f" : "fam-o";
  const page = ["/servers", "/members", "/audit", "/metrics", "/chat", "/overview"].includes(pathname)
    ? " pg-" + pathname.slice(1)
    : "";
  return base + page;
}

function Shell() {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  return (
    <ThemeProvider>
      <SearchProvider>
        <div className={`shell-page ${familyOf(pathname)}`}>
          <div className="bg-glow" aria-hidden="true" />
          <Sidebar email={user?.email} role={user?.role} onLogout={logout} />
          <div className="main">
            <Routes>
              <Route path="/" element={<Navigate to="/overview" replace />} />
              <Route path="/overview" element={user?.role === "admin" ? <Overview /> : <OverviewMember />} />
              <Route path="/servers" element={<Servers />} />
              <Route path="/members" element={<Members />} />
              <Route path="/audit" element={<Audit />} />
              <Route path="/metrics" element={<Metrics />} />
              <Route path="/chat" element={<Chat />} />
            </Routes>
          </div>
          <BottomNav />
        </div>
      </SearchProvider>
    </ThemeProvider>
  );
}

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <div className="center muted">Loading…</div>;
  if (!user) return <Login />;
  return <Shell />;
}
