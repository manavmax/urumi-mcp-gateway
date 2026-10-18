/* Notification bell (FIX PASS F1-6): fetches GET /api/notifications and opens
   a popover. The dot shows only when items exist that are newer than the
   per-user lastSeen timestamp in localStorage; "Mark all read" updates it.
   Esc and outside click close the popover and focus returns to the bell.
   An empty list shows a "No notifications" empty state instead of doing
   nothing (the reported bug). */
import * as React from "react";
import { Link } from "react-router-dom";
import { api, type NotificationItem } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Icon } from "./icons";

const SEVERITY_CHIP: Record<string, { cls: string; icon: "x-circle" | "pause" | "dot" }> = {
  critical: { cls: "chip-danger", icon: "x-circle" },
  warning: { cls: "chip-warn", icon: "pause" },
  info: { cls: "chip-neutral", icon: "dot" },
};

function relTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

function readSeen(email: string): string {
  try {
    return localStorage.getItem(`urumi.notif.seen.${email}`) || "";
  } catch {
    return "";
  }
}

export function NotificationBell() {
  const { user } = useAuth();
  const email = user?.email || "anon";
  const [open, setOpen] = React.useState(false);
  const [items, setItems] = React.useState<NotificationItem[] | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [err, setErr] = React.useState("");
  const [lastSeen, setLastSeen] = React.useState<string>("");
  const btnRef = React.useRef<HTMLButtonElement>(null);
  const popRef = React.useRef<HTMLDivElement>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.listNotifications();
      setItems(res.notifications || []);
      setErr("");
    } catch (e: unknown) {
      setItems([]);
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  // per-user lastSeen: re-read when the signed-in user changes
  React.useEffect(() => {
    setLastSeen(readSeen(email));
  }, [email]);

  // fetch once on mount (drives the dot) and every time the popover opens
  React.useEffect(() => {
    load();
  }, [load]);

  function close() {
    setOpen(false);
    btnRef.current?.focus();
  }

  function markAllRead() {
    const now = new Date().toISOString();
    try {
      localStorage.setItem(`urumi.notif.seen.${email}`, now);
    } catch {
      /* ignore */
    }
    setLastSeen(now);
  }

  /* Esc closes and returns focus to the bell; a click outside closes it. */
  React.useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    function onDown(e: MouseEvent) {
      const pop = popRef.current;
      if (pop && !pop.contains(e.target as Node) && btnRef.current && !btnRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const unread = !!items && items.some((i) => i.at && i.at > lastSeen);

  return (
    <div className="notif" style={{ position: "relative" }}>
      <button
        className="icon-btn"
        type="button"
        aria-label="Notifications"
        aria-haspopup="true"
        aria-expanded={open}
        ref={btnRef}
        onClick={() => setOpen((v) => !v)}
      >
        <Icon name="bell" />
        {unread && <span className="dot" />}
      </button>
      {open && (
        <div className="notif-pop" role="dialog" aria-label="Notifications" ref={popRef}>
          <div className="card-head" style={{ margin: 0, marginBottom: 8 }}>
            <div className="card-title" style={{ fontSize: "var(--t-md)" }}><Icon name="bell" />Notifications</div>
            {unread && (
              <button className="btn btn-ghost btn-sm" type="button" onClick={markAllRead}>
                Mark all read
              </button>
            )}
          </div>
          <div className="notif-list">
            {loading && <span className="sk" style={{ width: "70%" }} />}
            {!loading && err && <div className="alert alert-error" role="alert">{err}</div>}
            {!loading && !err && (items || []).length === 0 && (
              <div className="notif-empty"><b>No notifications</b><span>Everything looks calm right now</span></div>
            )}
            {!loading && (items || []).map((n) => {
              const chip = SEVERITY_CHIP[n.severity] || { cls: "chip-neutral", icon: "dot" as const };
              return (
                <Link key={n.id} to={n.href || "/"} className="notif-item" onClick={() => setOpen(false)}>
                  <span className={`chip ${chip.cls}`}><Icon name={chip.icon} />{n.severity}</span>
                  <span className="notif-main">
                    <b>{n.title}</b>
                    {n.detail && <span>{n.detail}</span>}
                    {n.at && <span className="faint small">{relTime(n.at)}</span>}
                  </span>
                </Link>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
