/* Overview, exact port of design/mockups/overview.html with real data:
   GET /api/stats (new), GET /api/servers, GET /api/tools, GET /api/audit,
   GET /api/me and GET /api/keys. Admin sees fleet-wide numbers; a member sees
   their own scoped numbers (the same server-side rule as /api/audit). The
   mockup's demo-only chrome (SAMPLE DATA chip, Auto-refresh chip, Motion
   toggle, skeleton/empty demo cards, interactive chart tooltip) is not shipped
   and is listed in the STAGE 1 report. */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type ApiKeyRow, type AuditRow, type Server, type Stats, type StatsRange, type Tool } from "../lib/api";
import { outcomeChip } from "../lib/audit-outcome";
import { useAuth } from "../lib/auth";
import { displayName, initials } from "../lib/search";
import { useMockupMotion } from "../lib/motion";
import { Icon } from "../components/icons";

const RANGES: { key: StatsRange; label: string }[] = [
  { key: "day", label: "Day" },
  { key: "week", label: "Week" },
  { key: "month", label: "Month" },
];
const DEFAULT_RANGE: StatsRange = "week";

function fmtMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(ms >= 10000 ? 1 : 2)} s`;
  return `${ms} ms`;
}
function fmtMsValue(ms: number): { value: string; unit: string } {
  if (ms >= 1000) return { value: (ms / 1000).toFixed(1), unit: "s" };
  return { value: String(ms), unit: "ms" };
}
function relative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs} sec ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

export default function Overview() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [range, setRange] = useState<StatsRange>(DEFAULT_RANGE);
  const [stats, setStats] = useState<Stats | null>(null);
  const [servers, setServers] = useState<Server[]>([]);
  const [tools, setTools] = useState<{ byServer: Record<string, Tool[]>; total: number }>({ byServer: {}, total: 0 });
  const [recent, setRecent] = useState<AuditRow[]>([]);
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setErr("");
      try {
        const [s, srv, audit, toolRes] = await Promise.all([
          api.stats(range),
          api.listServers(),
          api.listAudit({ limit: 8 }),
          api.listTools(),
        ]);
        if (!alive) return;
        setStats(s);
        setServers(srv.servers);
        setRecent(audit.logs);
        setKeys([]);
        const byServer: Record<string, Tool[]> = {};
        for (const t of toolRes.tools) {
          const slug = t.server_slug || (t.name.includes("__") ? t.name.split("__")[0] : "unknown");
          (byServer[slug] ||= []).push(t);
        }
        setTools({ byServer, total: toolRes.tools.length });
        try {
          const k = await api.listKeys();
          if (alive) setKeys(k.keys);
        } catch {
          if (alive) setKeys([]);
        }
      } catch (e: unknown) {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [range]);

  useMockupMotion(loading);

  const connected = useMemo(() => servers.filter((s) => s.status === "Connected").length, [servers]);
  const unreachable = useMemo(() => servers.filter((s) => s.status === "Unreachable").length, [servers]);
  const disabled = useMemo(() => servers.filter((s) => !s.enabled).length, [servers]);
  const activeKeys = useMemo(() => keys.filter((k) => !k.revoked_at).length, [keys]);

  const perDay = stats?.audit.per_day ?? [];
  const windowDays = stats?.window_days ?? 0;
  const delta = useMemo(() => {
    const cur = stats?.audit.calls ?? 0;
    const prev = stats?.audit.prev_calls ?? 0;
    if (!prev) return cur > 0 ? { dir: "up" as const, text: `new vs previous ${windowDays}d` } : null;
    const pct = Math.round(((cur - prev) / prev) * 100);
    return { dir: pct >= 0 ? ("up" as const) : ("down" as const), text: `${Math.abs(pct)}% vs previous ${windowDays}d` };
  }, [stats, windowDays]);

  /* ---------- chart geometry: same viewBox and axes as the mockup ---------- */
  const chart = useMemo(() => {
    const n = Math.max(perDay.length, 1);
    const maxCalls = Math.max(...perDay.map((d) => d.calls), 1);
    const niceMax = Math.max(50, Math.ceil(maxCalls / 50) * 50);
    const step = 588 / n;
    const barW = Math.min(24, Math.max(6, step - 10));
    const bars = perDay.map((d, i) => {
      const h = (d.calls / niceMax) * 160;
      const capH = Math.max(1.5, (d.errors / niceMax) * 160);
      return {
        x: 36 + i * step + (step - barW) / 2,
        y: 168 - h,
        w: barW,
        h,
        capY: 168 - h,
        capH,
        day: d,
      };
    });
    const labels = perDay.map((d, i) => {
      const date = new Date(`${d.date}T00:00:00`);
      const text = date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
      return { x: 36 + i * step + step / 2, text, dayNum: date.getDate() };
    });
    const labelEvery = Math.max(1, Math.ceil(n / 7));
    return { bars, labels, labelEvery, niceMax };
  }, [perDay]);

  const p95 = fmtMsValue(stats?.audit.p95_ms ?? 0);
  const rate = stats?.audit.success_rate;

  return (
    <main className="content">
      <header className="page-head">
        <div>
          <h1>Hello, {displayName(user?.email) || "there"}</h1>
          <p className="card-sub">
            Fleet health, tool-call volume and outcomes. Every number maps to a live endpoint, see source tags.
          </p>
        </div>
        <div className="head-actions">
          <form className="search" title="Search behaviour: filters the current page" onSubmit={(e) => e.preventDefault()}>
            <input type="search" placeholder="Search servers, tools, audit" aria-label="Search" />
            <button className="search-go" type="submit" aria-label="Search"><Icon name="search" sm /></button>
          </form>
        </div>
      </header>

      {err && <div className="alert alert-error" role="alert">{err}</div>}

      <div className="row wrap" style={{ gap: 8, justifyContent: "space-between" }}>
        <div className="row wrap" style={{ gap: 8 }}>
          {loading && <span className="chip chip-neutral">Loading…</span>}
        </div>
        <div className="row wrap" style={{ gap: 8 }}>
          <div className="seg" role="group" aria-label="Range">
            {RANGES.map((r) => (
              <button
                key={r.key}
                type="button"
                className={range === r.key ? "on" : ""}
                aria-pressed={range === r.key}
                onClick={() => setRange(r.key)}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* row 1: four equal stat tiles, one gradient hero (use a) */}
      <section className="bento row1" aria-label="Key metrics">
        <div className="card stat hero">
          <div className="stat-label">Tool calls, {windowDays} days <span className="src">NEW /api/stats</span></div>
          <div className="stat-num">{stats ? stats.audit.calls.toLocaleString("en-US") : <span className="sk num" style={{ width: 120 }} />}</div>
          <div className="small">across enabled servers</div>
          <div className="stat-foot">
            {delta && <span className={`delta on-grad ${delta.dir}`}><Icon name="arrow-up" />{delta.text}</span>}
          </div>
        </div>
        <div className="card stat">
          <div className="stat-label">Success rate, {windowDays} days <span className="src">NEW /api/stats</span></div>
          <div className="stat-num">{rate == null ? "n/a" : `${rate}%`}</div>
          <svg width="100%" height="34" viewBox="0 0 140 34" preserveAspectRatio="none" role="img" aria-label="Mini bar sparkline of daily success">
            <title>Daily success rate (live data)</title>
            <g fill="#C9D2E2">
              {perDay.map((d, i) => {
                const ratio = d.calls ? (d.calls - d.errors) / d.calls : 0;
                const h = 4 + ratio * 26;
                return <rect key={d.date} className="bar" x={2 + i * (136 / Math.max(perDay.length, 1))} y={32 - h} width={Math.min(12, 136 / Math.max(perDay.length, 1) - 2)} height={h} rx="3" />;
              })}
            </g>
          </svg>
          <div className="stat-foot">
            <span className="small muted">{stats?.audit.errors ?? 0} errors</span>
          </div>
        </div>
        <div className="card stat">
          <div className="stat-label">p95 latency, {windowDays} days <span className="src">NEW /api/stats</span></div>
          <div className="stat-num">{p95.value}<span className="stat-unit">{p95.unit}</span></div>
          <svg width="100%" height="34" viewBox="0 0 140 34" preserveAspectRatio="none" role="img" aria-label="Line squiggle of p95 latency">
            <title>p95 latency trend (live data)</title>
            {perDay.length > 1 && (
              <polyline
                className="draw"
                points={perDay.map((d, i) => `${2 + (i * 136) / (perDay.length - 1)},${30 - Math.min(1, d.p95_ms / Math.max(...perDay.map((x) => x.p95_ms), 1)) * 26}`).join(" ")}
                fill="none"
                stroke="#14171C"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            )}
            {perDay.length > 0 && (
              <circle
                cx={138}
                cy={30 - Math.min(1, perDay[perDay.length - 1].p95_ms / Math.max(...perDay.map((x) => x.p95_ms), 1)) * 26}
                r="2.6"
                fill="#14171C"
              />
            )}
          </svg>
          <div className="stat-foot">
            <span className="chip chip-neutral">p50 {fmtMs(stats?.audit.p50_ms ?? 0)}</span>
          </div>
        </div>
        <div className="card stat">
          <div className="tint-circle" style={{ background: "var(--lilac)" }}><Icon name="server" /></div>
          <div className="stat-label">Servers connected</div>
          <div className="stat-num">{connected} <span className="stat-unit">of {servers.length}</span></div>
          <div className="small muted">{unreachable} unreachable, {disabled} disabled</div>
          <div className="stat-foot"><span className="src">GET /api/servers</span></div>
        </div>
      </section>

      {/* row 2: wide chart with floating mini-cards, half-ring gauge, my account */}
      <section className="bento row2">
        <div className="card chart-card">
          <div className="card-head">
            <div>
              <div className="card-title">Tool calls per day</div>
              <div className="card-sub">Last {windowDays} days, bars = calls, cap = errors · <span className="src">NEW /api/stats</span></div>
            </div>
            <div className="row small muted">
              <span className="row" style={{ gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: "#C9D2E2", display: "inline-block" }}></span>calls</span>
              <span className="row" style={{ gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: "#EFC9C0", display: "inline-block" }}></span>errors</span>
            </div>
          </div>
          <svg viewBox="0 0 640 205" width="100%" role="img" aria-label="Bar chart of tool calls per day over the selected range">
            <title>Tool calls per day (live data)</title>
            <g stroke="rgba(20,23,28,.06)" strokeWidth="1">
              <line x1="36" y1="168" x2="624" y2="168" />
              <line x1="36" y1="114.7" x2="624" y2="114.7" />
              <line x1="36" y1="61.3" x2="624" y2="61.3" />
              <line x1="36" y1="8" x2="624" y2="8" />
            </g>
            <g fill="#5F6673" fontSize="10" fontFamily="ui-monospace, Menlo, monospace" textAnchor="end">
              <text x="30" y="171">0</text>
              <text x="30" y="118">{Math.round(chart.niceMax / 3)}</text>
              <text x="30" y="65">{Math.round((chart.niceMax * 2) / 3)}</text>
              <text x="30" y="12">{chart.niceMax}</text>
            </g>
            <g fill="#C9D2E2">
              {chart.bars.map((b) => (
                <rect key={b.day.date} className="bar" x={b.x} y={b.y} width={b.w} height={Math.max(b.h, 0.5)} rx="5">
                  <title>{b.day.date}: {b.day.calls} calls, {b.day.errors} errors</title>
                </rect>
              ))}
            </g>
            <g fill="#EFC9C0">
              {chart.bars.map((b) =>
                b.day.errors > 0 ? (
                  <rect key={b.day.date} className="cap" x={b.x} y={b.capY} width={b.w} height={b.capH} rx="1.6">
                    <title>{b.day.errors} errors</title>
                  </rect>
                ) : null,
              )}
            </g>
            <g fill="#5F6673" fontSize="10" fontFamily="ui-monospace, Menlo, monospace" textAnchor="middle">
              {chart.labels.map((l, i) =>
                i % chart.labelEvery === 0 || i === chart.labels.length - 1 ? (
                  <text key={i} x={l.x} y="188">{l.text}</text>
                ) : null,
              )}
            </g>
          </svg>
          <div className="float-chip" style={{ right: 24, top: 64 }}>
            <span className="lab">Success rate, {windowDays} days</span>
            <span className="val">{rate == null ? "n/a" : `${rate}%`} {delta && <span className={`delta ${delta.dir}`}><Icon name="arrow-up" />{delta.text}</span>}</span>
          </div>
          <div className="float-chip" style={{ right: 24, bottom: 58 }}>
            <span className="lab">p95 latency</span>
            <span className="val">{p95.value}{p95.unit}</span>
          </div>
        </div>
        {/* gradient use (b): half-ring gauge, very soft gradient fill */}
        <div className="card stat" style={{ alignContent: "center", justifyItems: "center", textAlign: "center" }}>
          <div className="stat-label" style={{ justifySelf: "start" }}>Success rate, {windowDays} days <span className="src">NEW /api/stats</span></div>
          <svg width="200" height="118" viewBox="0 0 200 118" role="img" aria-label="Half-ring gauge showing the success rate">
            <title>Success rate gauge (live data)</title>
            <path d="M16 100 A84 84 0 0 1 184 100" fill="none" stroke="#F0EFEB" strokeWidth="14" strokeLinecap="round" />
            <path
              className="draw"
              d="M16 100 A84 84 0 0 1 184 100"
              fill="none"
              stroke="url(#grad-soft)"
              strokeWidth="14"
              strokeLinecap="round"
              strokeDasharray={`${(((rate ?? 0) / 100) * 254.4).toFixed(1)} 263.9`}
            />
            <defs>
              <linearGradient id="grad-soft" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor="#B9C4DD" />
                <stop offset=".52" stopColor="#D9C8DC" />
                <stop offset="1" stopColor="#EFCBBE" />
              </linearGradient>
            </defs>
            <text x="100" y="86" textAnchor="middle" fontSize="34" fontWeight="650" fill="#14171C" fontFamily="-apple-system, Segoe UI, Roboto, sans-serif">
              {rate == null ? "n/a" : `${rate}%`}
            </text>
            <text x="100" y="106" textAnchor="middle" fontSize="10" fill="#5F6673" fontFamily="-apple-system, Segoe UI, Roboto, sans-serif">
              {stats?.audit.success ?? 0} of {stats?.audit.calls ?? 0} calls succeeded
            </text>
          </svg>
          <div className="stat-foot" style={{ justifyContent: "center" }}>
            <span className="chip chip-danger"><Icon name="x-circle" />{stats?.audit.errors ?? 0} errors</span>
            <span className="chip chip-neutral"><Icon name="clock" />p95 {fmtMs(stats?.audit.p95_ms ?? 0)}</span>
          </div>
        </div>

        <div className="card stat">
          <div className="card-title" style={{ fontSize: "var(--t-md)" }}>My account</div>
          <div className="row" style={{ gap: 12, marginTop: 6, minWidth: 0 }}>
            <span className="avatar" style={{ width: 44, height: 44, background: "var(--lilac)", boxShadow: "none" }}>{initials(user?.email)}</span>
            <div style={{ minWidth: 0 }}>
              <b style={{ fontSize: "var(--t-md)", display: "block" }}>{displayName(user?.email) || user?.email}</b>
              <span className="small muted account-email">{user?.email}</span>
            </div>
          </div>
          <div className="stat-foot" style={{ marginTop: 4 }}>
            <span className="chip chip-neutral"><Icon name="user" />{isAdmin ? "Administrator" : "Member"}</span>
            <span className="chip chip-accent"><Icon name="key" />{activeKeys} active keys</span>
          </div>
          <Link className="link" to="/members" style={{ marginTop: 6 }}>Manage keys<Icon name="arrow-right" sm /></Link>
          <span className="src" style={{ marginTop: 6 }}>GET /api/me · GET /api/keys</span>
        </div>
      </section>

      {/* row 3: activity with accent bars, tools overview, fleet status */}
      <section className="bento row3">
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Recent activity</div>
              <div className="card-sub">Latest tool calls · <span className="src">GET /api/audit?limit=8</span></div>
            </div>
            <Link className="link" to="/audit">Audit<Icon name="arrow-right" sm /></Link>
          </div>
          {recent.length === 0 && <div className="small muted">No tool calls in the audit trail yet.</div>}
          {recent.map((r) => (
            <div className="feed-row" key={r.id}>
              <div className="feed-main">
                <div className="feed-title mono">{r.tool_exposed_name}</div>
                <div className="feed-sub">{r.user_email || "unknown user"} · {relative(r.ts)}</div>
              </div>
              <div className="feed-meta">
                <span className={`chip ${outcomeChip(r.outcome).cls}`}><Icon name={outcomeChip(r.outcome).icon} />{r.outcome}</span>
                <span className="small faint mono">{fmtMs(r.duration_ms)}</span>
              </div>
            </div>
          ))}
        </div>
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Tools overview</div>
              <div className="card-sub">Exposed tools by server · <span className="src">GET /api/tools</span></div>
            </div>
          </div>
          {servers.length === 0 && <div className="small muted">No servers registered yet.</div>}
          {servers.map((s) => {
            const list = tools.byServer[s.slug] || [];
            return (
              <div className="feed-row" key={s.id}>
                <div className="feed-main">
                  <div className="feed-title mono">{s.slug}</div>
                  <div className="feed-sub">{s.last_error ? s.last_error.slice(0, 90) : s.status}</div>
                </div>
                <div className="feed-meta">
                  {s.enabled ? (
                    <span className="chip chip-neutral">{list.length} tools</span>
                  ) : (
                    <span className="chip chip-warn"><Icon name="pause" />Disabled</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div className="card stat">
          <div className="card-title" style={{ fontSize: "var(--t-md)" }}>Fleet status</div>
          <div className="stat-foot" style={{ marginTop: 8 }}>
            <span className="chip chip-ok"><span className="dot-pulse" aria-hidden="true"></span>{connected} Connected</span>
            <span className="chip chip-danger"><Icon name="x-circle" />{unreachable} Unreachable</span>
            <span className="chip chip-warn"><Icon name="pause" />{disabled} Disabled</span>
          </div>
          {servers.filter((s) => s.status !== "Connected" || !s.enabled).map((s) => (
            <div className="feed-row" style={{ marginTop: 8 }} key={s.id}>
              <div className="feed-main">
                <div className="feed-title mono">{s.slug}</div>
                <div className="feed-sub">{s.enabled ? s.last_error || s.status : "disabled by admin"}</div>
              </div>
              <span className={`chip ${s.enabled ? "chip-danger" : "chip-warn"}`}>
                <Icon name={s.enabled ? "x-circle" : "pause"} />{s.enabled ? "Unreachable" : "Disabled"}
              </span>
            </div>
          ))}
          <span className="src" style={{ marginTop: 8 }}>GET /api/servers</span>
        </div>
      </section>

      {/* security posture (static copy, not a metric) */}
      <section className="card" style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div className="tint-circle" style={{ width: 44, height: 44 }}><Icon name="lock" /></div>
        <div style={{ flex: 1, minWidth: 260 }}>
          <div className="card-title" style={{ fontSize: "var(--t-md)" }}>Security posture</div>
          <p className="card-sub" style={{ marginTop: 4 }}>
            Static text, not a metric: upstream credentials are encrypted at rest (Fernet, per-credential key id) and never
            leave the gateway; every tool call is written to the audit trail with user, server, tool and outcome; RBAC is
            enforced server-side on every endpoint.
          </p>
        </div>
        <div className="row wrap">
          <span className="chip chip-neutral"><Icon name="lock" />Credentials masked</span>
          <span className="chip chip-neutral"><Icon name="users" />RBAC server-side</span>
          <span className="chip chip-neutral"><Icon name="shield" />Audit on every call</span>
        </div>
      </section>
    </main>
  );
}
