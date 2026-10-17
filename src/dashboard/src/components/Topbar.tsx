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
import { useSharedTheme } from "../lib/theme";
import type { Theme } from "../lib/theme";

const SunIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="5"/>
    <line x1="12" y1="1" x2="12" y2="3"/>
    <line x1="12" y1="21" x2="12" y2="23"/>
    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
    <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
    <line x1="1" y1="12" x2="3" y2="12"/>
    <line x1="21" y1="12" x2="23" y2="12"/>
    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
    <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
  </svg>
);
const MoonIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
  </svg>
);

const THEME_OPTIONS: { value: Theme; label: string; Icon: React.FC }[] = [
  { value: "light", label: "Light", Icon: SunIcon },
  { value: "dark", label: "Dark", Icon: MoonIcon },
];

export function Topbar() {
  const { user, logout } = useAuth();
  const { query, setQuery } = useSearch();
  const { theme, setTheme } = useSharedTheme();
  const nav = useNavigate();
  const inputRef = React.useRef<HTMLInputElement>(null);
  const roleLabel = user?.role === "admin" ? "Administrator" : user?.role === "member" ? "Member" : "";

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
          <div className="theme-row">
            {THEME_OPTIONS.map(({ value, label, Icon: ThemeIcon }) => (
              <button
                key={value}
                type="button"
                className={`theme-btn${theme === value ? " on" : ""}`}
                onClick={() => setTheme(value)}
                aria-pressed={theme === value}
                title={label}
              >
                <ThemeIcon />
                <span>{label}</span>
              </button>
            ))}
          </div>
          <Link to="/members"><Icon name="users" sm />Members &amp; keys</Link>
          <Link to="/audit"><Icon name="shield" sm />Audit trail</Link>
          <button type="button" onClick={signOut}><Icon name="logout" sm />Sign out</button>
        </div>
      </div>
    </header>
  );
}
