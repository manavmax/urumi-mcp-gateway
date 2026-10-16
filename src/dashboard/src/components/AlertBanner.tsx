/* Next-best-action banner (docs/11_OBSERVABILITY.md §3).
   Fetches /api/alerts and renders:
     - ADMIN: one dismissible banner when any enabled server is Unreachable or its
       last-hour error rate is >20% with >= 5 calls; message "<server> is
       unreachable since <time>. Reason: <category>." with "Open server" (navigates
       to /servers) and "Check now" buttons.
     - MEMBER: a calm notice "Some tools are temporarily unavailable: <slugs>"
       with no internal details.
   No banner when everything is healthy. Dismissal is per session only
   (sessionStorage - a fresh tab shows the banner again). */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type AlertsPayload, type AdminAlert } from "../lib/api";
import { Icon } from "./icons";

export type { AdminAlert };

const DISMISS_KEY = "urumi.alert.dismissed";

function relative(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m`;
  return `${Math.round(mins / 60)}h`;
}

export default function AlertBanner({ role }: { role: "admin" | "member" }) {
  const nav = useNavigate();
  const [alerts, setAlerts] = useState<AlertsPayload | null>(null);
  const [checking, setChecking] = useState(false);
  const [dismissed, setDismissed] = useState(() => {
    try {
      return sessionStorage.getItem(DISMISS_KEY) === "1";
    } catch {
      return false;
    }
  });

  const load = useCallback(async () => {
    try {
      const res = await api.alerts();
      setAlerts(res);
    } catch {
      setAlerts(null);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const adminRows = "admin" in (alerts ?? {}) ? (alerts as { admin: AdminAlert[] }).admin : [];
  const memberSlugs = "member" in (alerts ?? {}) ? (alerts as { member: { slugs: string[] } }).member.slugs : [];

  if (!alerts) return null;
  if (role === "admin") {
    if (adminRows.length === 0 || dismissed) return null;
    const primary = adminRows[0];
    const extra = adminRows.length - 1;
    const since = relative(primary.unreachable_since);
    const reason = primary.category || primary.reason;
    return (
      <div className="banner" role="alert" aria-label="Server alert">
        <Icon name="alert" />
        <div className="banner-body">
          <b>{primary.slug}</b> is unreachable{since ? ` since ${since}` : ""}
          {reason ? `. Reason: ${reason}.` : "."}
          {extra > 0 && <span className="banner-more"> (+{extra} more)</span>}
          <span className="banner-actions">
            <button className="btn btn-secondary btn-sm" type="button" onClick={() => nav("/servers")}>
              Open server
            </button>
            <button className="btn btn-primary btn-sm" type="button" disabled={checking} onClick={async () => {
              setChecking(true);
              try {
                await Promise.all(adminRows.map((a) => api.checkServerBySlug(a.slug).catch(() => undefined)));
                await load();
              } finally {
                setChecking(false);
              }
            }}>
              {checking ? "Checking..." : "Check now"}
            </button>
          </span>
        </div>
        <button className="banner-close" type="button" aria-label="Dismiss" onClick={() => {
          setDismissed(true);
          try {
            sessionStorage.setItem(DISMISS_KEY, "1");
          } catch {
            /* sessionStorage unavailable: dismissal just lasts the render */
          }
        }}>
          <Icon name="x" sm />
        </button>
      </div>
    );
  }

  /* member: calm notice, no internal details */
  if (memberSlugs.length === 0 || dismissed) return null;
  return (
    <div className="banner banner-calm" role="note" aria-label="Service notice">
      <Icon name="alert" />
      <div className="banner-body">
        Some tools are temporarily unavailable: <span className="mono">{memberSlugs.join(", ")}</span>
      </div>
      <button className="banner-close" type="button" aria-label="Dismiss" onClick={() => {
        setDismissed(true);
        try {
          sessionStorage.setItem(DISMISS_KEY, "1");
        } catch {
          /* ignore */
        }
      }}>
        <Icon name="x" sm />
      </button>
    </div>
  );
}
