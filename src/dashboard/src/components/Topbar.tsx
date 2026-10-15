/* Fleet topbar, ported verbatim from design/mockups/{servers,members,audit}.html:
   page search pill (with the mockup's kbd hint), notifications button, and the
   account menu with the real signed-in user. The search drives the shared
   client-side page search (search.tsx), the decision recorded for the mockup's
   "Search behaviour: NEEDS DECISION" marker. */
import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import { Icon } from "./icons";
import { useAuth } from "../lib/auth";
import { initials, useSearch } from "../lib/search";

export function Topbar() {
  const { user, logout } = useAuth();
  const { query, setQuery } = useSearch();
  const nav = useNavigate();
  const inputRef = React.useRef<HTMLInputElement>(null);
  const roleLabel = user?.role === "admin" ? "Administrator" : user?.role === "member" ? "Member" : "";

  /* Cmd/Ctrl+K focuses the page search, as the kbd hint promises. */
  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function signOut() {
    await logout();
    nav("/login", { replace: true });
  }

  return (
    <header className="topbar">
      <label className="search">
        <Icon name="search" sm />
        <input
          ref={inputRef}
          type="search"
          placeholder="Search servers, tools, audit…"
          aria-label="Search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      <button className="icon-btn" type="button" aria-label="Notifications">
        <Icon name="bell" />
        <span className="dot"></span>
      </button>
      <div className="user-menu">
        <button type="button" aria-label="Account menu">
          <div className="avatar">{initials(user?.email)}</div>
          <div className="um-name"><b>{user?.email}</b><span>{roleLabel}</span></div>
          <Icon name="chevron" sm />
        </button>
        <div className="menu-pop">
          <div className="head">
            <div className="avatar">{initials(user?.email)}</div>
            <div>
              <b style={{ fontSize: "var(--t-md)" }}>{user?.email}</b>
              <div className="small muted">{roleLabel}</div>
            </div>
          </div>
          <Link to="/members"><Icon name="users" sm />Members &amp; keys</Link>
          <Link to="/audit"><Icon name="shield" sm />Audit trail</Link>
          <button type="button" onClick={signOut}><Icon name="logout" sm />Sign out</button>
        </div>
      </div>
    </header>
  );
}
