/* Floating icon-only pill sidebar and mobile bottom tab bar, ported verbatim
   from design/mockups/*.html (STAGE 0.6 spec section 2.1).
   Collapsed: 72px wide, inset 16px. Hover or keyboard focus-within expands it
   to 248px as an overlay (content margin is fixed, so nothing reflows).
   Expansion is pure CSS: 80ms intent delay on open, 150ms after the pointer
   leaves before collapsing, labels stagger in at 20ms per item. Under
   prefers-reduced-motion the global token rule makes it instant with no
   stagger. Active item is a filled ink circle with a white icon.
   ?expanded=1 forces the expanded state, matching the mockup PNGs. */
import * as React from "react";
import { NavLink, useSearchParams } from "react-router-dom";
import { Icon } from "./icons";
import { initials } from "../lib/search";
import type { IconName } from "./icons";

type NavItem = { to: string; label: string; icon: IconName };

const NAV: NavItem[] = [
  { to: "/overview", label: "Overview", icon: "grid" },
  { to: "/servers", label: "Servers", icon: "server" },
  { to: "/members", label: "Members and keys", icon: "users" },
  { to: "/audit", label: "Audit", icon: "shield" },
  { to: "/chat", label: "Chat", icon: "chat" },
];

const railStyle = (i: number) => ({ "--i": i } as React.CSSProperties);

export function Sidebar({ email, role, onLogout }: { email?: string; role?: string; onLogout: () => void }) {
  const [params] = useSearchParams();
  const forced = params.get("expanded") === "1" ? " force" : "";
  const roleLabel = role === "admin" ? "Administrator" : role === "member" ? "Member" : role || "";
  return (
    <aside className={`sidebar-pill${forced}`} id="rail" aria-label="Primary">
      <NavLink className="brand" to="/overview" aria-label="Urumi home">
        <span className="mark"><Icon name="logo" size={21} /></span>
        <span className="rail-label brand-name" style={railStyle(0)}>
          Urumi<small>Gateway</small>
        </span>
      </NavLink>
      <nav className="rail-nav" aria-label="Primary">
        {NAV.map((item, i) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => `rail-item${isActive ? " active" : ""}`}
            style={railStyle(i + 1)}
          >
            <span className="rail-ic"><Icon name={item.icon} size={20} /></span>
            <span className="rail-label">{item.label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="rail-user">
        <div className="user-card">
          <span className="avatar" aria-hidden="true">{initials(email)}</span>
          <span className="rail-label who" style={railStyle(6)}>
            <b>{email}</b>
            <small>{roleLabel}</small>
          </span>
        </div>
        <button className="signout" type="button" onClick={onLogout} style={railStyle(7)}>
          <span className="rail-ic"><Icon name="logout" size={18} /></span>
          <span className="rail-label">Sign out</span>
        </button>
      </div>
    </aside>
  );
}

/* Mobile: the bottom tab bar replaces the pill entirely (spec section 8). */
export function BottomNav() {
  return (
    <nav className="bottomnav" aria-label="Primary mobile">
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) => (isActive ? "on" : "")}
        >
          <Icon name={item.icon} size={20} />
          <span>{item.label.split(" ")[0]}</span>
        </NavLink>
      ))}
    </nav>
  );
}
