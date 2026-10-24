/* Admin Overview: real data only, from GET /api/stats (calls, success rate,
   p95, per-day series, by_server, top_tools), GET /api/servers,
   GET /api/audit, GET /api/keys and GET /api/users. Hand-written inline SVG
   (bar chart with hover tooltip, donut, sparkline, per-server sparklines), a
   restrained token palette and the shared bento spacing/type grid. No static
   copy cards, no fake numbers; empty states are short and honest. */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type ApiKeyRow, type AuditRow, type Server, type Stats, type StatsRange } from "../lib/api";
import { outcomeChip } from "../lib/audit-outcome";
import { useAuth } from "../lib/auth";
import { displayName, initials } from "../lib/search";
import { useMockupMotion, useCountUp } from "../lib/motion";
import AlertBanner from "../components/AlertBanner";
import { Icon } from "../components/icons";

const RANGES: { key: StatsRange; label: string }[] = [
  { key: "day", label: "Day" },
  { key: "week", label: "Week" },
  { key: "month", label: "Month" },
];
const DEFAULT_RANGE: StatsRange = "week";

const STATUS_CHIP = (status: string): { cls: string; icon: "check-circle" | "x-circle" | "pause" | "dot" } => {
  if (status === "Connected") return { cls: "chip-ok", icon: "check-circle" };
  if (status === "Unreachable") return { cls: "chip-danger", icon: "x-circle" };
  if (status === "Disabled") return { cls: "chip-warn", icon: "pause" };
  return { cls: "chip-neutral", icon: "dot" };
};

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
  const [recent, setRecent] = useState<AuditRow[]>([]);
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [members, setMembers] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [hoverBar, setHoverBar] = useState<string | null>(null);
  const [tipPos, setTipPos] = useState({ x: 0, y: 0 });

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setErr("");
      try {
        const [s, srv, audit] = await Promise.all([
          api.stats(range),
          api.listServers(),
          api.listAudit({ limit: 8 }),
        ]);
        if (!alive) return;
        setStats(s);
        setServers(srv.servers);
        setRecent(audit.logs);
        setKeys([]);
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

  /* admin team size for the account card (members never fetch /api/users) */
  useEffect(() => {
    if (!isAdmin) return;
    let alive = true;
    api
      .listUsers()
      .then((u) => {
        if (alive) setMembers(u.users.length);
      })
      .catch(() => {
        if (alive) setMembers(null);
      });
    return () => {
      alive = false;
    };
  }, [isAdmin]);

  useMockupMotion(loading);

  const connected = useMemo(() => servers.filter((s) => s.status === "Connected").length, [servers]);
  const unreachable = useMemo(() => servers.filter((s) => s.status === "Unreachable").length, [servers]);
  const disabled = useMemo(() => servers.filter((s) => !s.enabled).length, [servers]);
  const activeKeys = useMemo(() => keys.filter((k) => !k.revoked_at).length, [keys]);

  const perDay = stats?.audit.per_day ?? [];
  const windowDays = stats?.window_days ?? 14;
  const calls = stats?.audit.calls ?? 0;
  const errors = stats?.audit.errors ?? 0;
  const rate = stats?.audit.success_rate;
  const topTools = stats?.top_tools ?? [];

  const delta = useMemo(() => {
    const cur = stats?.audit.calls ?? 0;
    const prev = stats?.audit.prev_calls ?? 0;
    if (!prev) return cur > 0 ? { dir: "up" as const, text: `new vs previous ${windowDays}d` } : null;
    const pct = Math.round(((cur - prev) / prev) * 100);
    return { dir: pct >= 0 ? ("up" as const) : ("down" as const), text: `${Math.abs(pct)}% vs previous ${windowDays}d` };
  }, [stats, windowDays]);

  /* ---------- chart geometry ---------- */
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

  /* success-rate donut: window rate as one arc on a 6px ring */
  const donut = useMemo(() => {
    const r = 18;
    const c = 2 * Math.PI * r;
    return { r, c, dash: ((rate ?? 0) / 100) * c };
  }, [rate]);

  const p95 = fmtMsValue(stats?.audit.p95_ms ?? 0);

  /* count-up on stat tiles: 700ms, exact real value at the end (reduced motion
     shows the final value at 0ms). */
  const callsCount = useCountUp(calls);
  const rateCount = useCountUp(rate ?? 0, 700, 1);
  const errorsCount = useCountUp(errors);

  return (
    <main className="content">
      <header className="page-head">
        <div>
          <h1>Hello, {displayName(user?.email) || "there"}</h1>
        </div>
        <div className="head-actions">
          <form className="search" onSubmit={(e) => e.preventDefault()}>
            <input type="search" placeholder="Search…" aria-label="Search" />
            <button className="search-go" type="submit" aria-label="Search"><Icon name="search" sm /></button>
          </form>
        </div>
      </header>

      {err && <div className="alert alert-error" role="alert">{err}</div>}

      {/* next-best-action banner (admin, docs/11_OBSERVABILITY.md §3) */}
      <AlertBanner role="admin" />

      <div className="row wrap" style={{ gap: 8, justifyContent: "flex-end" }}>
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

      {/* row 1: KPI tiles, one gradient hero (gradient use a) */}
      <section className="bento row1" aria-label="Key metrics">
        <div className="card stat hero">
          <div className="stat-label">Tool calls, {windowDays} days</div>
          <div className="stat-num">{stats ? callsCount.toLocaleString("en-US") : <span className="sk num" style={{ width: 120 }} />}</div>
          <div className="stat-foot">
            {delta && (
              <span className="delta on-grad delta-pop">
                <Icon name="arrow-up" style={delta.dir === "down" ? { transform: "rotate(180deg)" } : undefined} />{delta.text}
              </span>
            )}
          </div>
        </div>
        <div className="card stat">
          <div className="stat-label">Success rate, {windowDays} days</div>
          <div className="row" style={{ gap: 16, alignItems: "center" }}>
            <div className="stat-num">{rate == null ? "n/a" : `${rateCount}%`}</div>
            <svg width="44" height="44" viewBox="0 0 44 44" role="img" aria-label={`Success rate donut: ${rate ?? "n/a"}%`}>
              <title>Success rate (live data)</title>
              <circle cx="22" cy="22" r={donut.r} fill="none" stroke="var(--chart-track)" strokeWidth="6" />
              <circle
                className="donut-seg"
                cx="22" cy="22" r={donut.r}
                fill="none"
                stroke="var(--chart-bar)"
                strokeWidth="6"
                strokeLinecap="round"
                strokeDasharray={`${donut.dash.toFixed(1)} ${donut.c.toFixed(1)}`}
                transform="rotate(-90 22 22)"
              />
            </svg>
          </div>
          <div className="stat-foot">
            <span className="small muted">{stats ? `${errors} errors` : <span className="sk" style={{ width: 60 }} />}</span>
          </div>
        </div>
        <div className="card stat">
          <div className="stat-label">p95 latency, {windowDays} days</div>
          <div className="stat-num">{stats ? <>{p95.value}<span className="stat-unit">{p95.unit}</span></> : <span className="sk num" style={{ width: 72 }} />}</div>
          <svg width="100%" height="34" viewBox="0 0 140 34" preserveAspectRatio="none" role="img" aria-label="Line squiggle of p95 latency">
            <title>p95 latency trend (live data)</title>
            {perDay.length > 1 && (
              <polyline
                className="draw"
                points={perDay.map((d, i) => `${2 + (i * 136) / (perDay.length - 1)},${30 - Math.min(1, d.p95_ms / Math.max(...perDay.map((x) => x.p95_ms), 1)) * 26}`).join(" ")}
                fill="none"
                stroke="var(--chart-text)"
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
                fill="var(--chart-text)"
              />
            )}
          </svg>
          <div className="stat-foot">
            <span className="chip chip-neutral">{stats ? `p50 ${fmtMs(stats.audit.p50_ms)}` : <span className="sk chip" />}</span>
          </div>
        </div>
        <div className="card stat">
          <div className="stat-label">Errors, {windowDays} days</div>
          <div className="stat-num">
            {stats ? <span style={errors > 0 ? { color: "var(--bad-text)" } : undefined}>{errorsCount.toLocaleString("en-US")}</span> : <span className="sk num" style={{ width: 72 }} />}
          </div>
          <div className="small muted">
            {stats
              ? (calls ? `${rate}% success of ${calls.toLocaleString("en-US")} calls` : "no calls in this window")
              : <span className="sk" style={{ width: 120 }} />}
          </div>
        </div>
      </section>

      {/* row 2: wide chart + top tools */}
      <section className="bento row2" aria-label="Calls over time">
        <div className="card chart-card">
          <div className="card-head">
            <div>
              <div className="card-title">Tool calls per day</div>
            </div>
            <div className="row small muted">
              <span className="row" style={{ gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: "var(--chart-bar)", display: "inline-block" }}></span>calls</span>
              <span className="row" style={{ gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: "var(--chart-bar-err)", display: "inline-block" }}></span>errors</span>
            </div>
          </div>
          {stats && calls === 0 ? (
            <div className="chart-empty" role="status">
              <b>No tool calls in this window yet.</b>
              <span>Call a tool from Chat or an MCP client to see activity here.</span>
            </div>
          ) : (
            <>
              <svg viewBox="0 0 640 205" width="100%" role="img" aria-label="Bar chart of tool calls per day over the selected range">
                <title>Tool calls per day (live data)</title>
                <g stroke="var(--chart-axis)" strokeWidth="1">
                  <line x1="36" y1="168" x2="624" y2="168" />
                  <line x1="36" y1="114.7" x2="624" y2="114.7" />
                  <line x1="36" y1="61.3" x2="624" y2="61.3" />
                  <line x1="36" y1="8" x2="624" y2="8" />
                </g>
                <g fill="var(--chart-axis-label)" fontSize="10" fontFamily="ui-monospace, Menlo, monospace" textAnchor="end">
                  <text x="30" y="171">0</text>
                  <text x="30" y="118">{Math.round(chart.niceMax / 3)}</text>
                  <text x="30" y="65">{Math.round((chart.niceMax * 2) / 3)}</text>
                  <text x="30" y="12">{chart.niceMax}</text>
                </g>
                <g fill="var(--chart-bar)">
                  {chart.bars.map((b) => (
                    <rect key={`${range}-${b.day.date}`} className={`bar${hoverBar && hoverBar !== b.day.date ? " dimmed" : ""}${hoverBar === b.day.date ? " hl" : ""}`} x={b.x} y={b.y} width={b.w} height={Math.max(b.h, 0.5)} rx="5"
                      data-calls={b.day.calls} data-errors={b.day.errors} data-date={b.day.date}
                      onMouseEnter={(e) => { setHoverBar(b.day.date); setTipPos({ x: e.clientX, y: e.clientY }); }}
                      onMouseMove={(e) => setTipPos({ x: e.clientX, y: e.clientY })}
                      onMouseLeave={() => setHoverBar(null)}
                      onFocus={() => setHoverBar(b.day.date)}
                      onBlur={() => setHoverBar(null)}
                      tabIndex={0} role="img" aria-label={`${b.day.date}: ${b.day.calls} calls, ${b.day.errors} errors`}>
                      <title>{b.day.date}: {b.day.calls} calls, {b.day.errors} errors</title>
                    </rect>
                  ))}
                </g>
                <g fill="var(--chart-bar-err)">
                  {chart.bars.map((b) =>
                    b.day.errors > 0 ? (
                      <rect key={`${range}-${b.day.date}-cap`} className={`cap${hoverBar && hoverBar !== b.day.date ? " dimmed" : ""}`} x={b.x} y={b.capY} width={b.w} height={b.capH} rx="1.6">
                        <title>{b.day.errors} errors</title>
                      </rect>
                    ) : null,
                  )}
                </g>
                <g fill="var(--chart-axis-label)" fontSize="10" fontFamily="ui-monospace, Menlo, monospace" textAnchor="middle">
                  {chart.labels.map((l, i) =>
                    i % chart.labelEvery === 0 || i === chart.labels.length - 1 ? (
                      <text key={i} x={l.x} y="188">{l.text}</text>
                    ) : null,
                  )}
                </g>
              </svg>
              {hoverBar && (() => {
                const b = chart.bars.find((x) => x.day.date === hoverBar);
                if (!b) return null;
                return (
                  <div className="chart-tip on" style={{ left: tipPos.x + 12, top: tipPos.y - 10 }} role="status">
                    {b.day.date}: {b.day.calls} calls, {b.day.errors} errors
                  </div>
                );
              })()}
            </>
          )}
        </div>

        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Top tools</div>
            </div>
            <Link className="link" to="/audit">Audit<Icon name="arrow-right" sm /></Link>
          </div>
          {stats && topTools.length === 0 && <div className="small muted">No tool calls in this window yet.</div>}
          {!stats && <span className="sk" style={{ width: "60%" }} />}
          {topTools.map((t) => {
            const max = Math.max(...topTools.map((x) => x.calls), 1);
            return (
              <div className="tt-row" key={t.tool}>
                <div style={{ minWidth: 0 }}>
                  <div className="tt-name mono" title={t.tool}>{t.tool}</div>
                  <div className="tt-track" aria-hidden="true">
                    <span className="tt-bar" style={{ width: `${(t.calls / max) * 100}%` }}>
                      {t.errors > 0 && <span className="tt-err" style={{ width: `${Math.max((t.errors / t.calls) * 100, 8)}%` }} />}
                    </span>
                  </div>
                </div>
                <div className="tt-meta">
                  <b>{t.calls.toLocaleString("en-US")}</b>
                  {t.errors > 0 && <span className="tt-err-count">{t.errors} err</span>}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* row 3: activity, fleet status, account & team */}
      <section className="bento row3" aria-label="Recent activity and fleet">
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Recent activity</div>
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

        <div className="card stat">
          <div className="card-title" style={{ fontSize: "var(--t-md)" }}>Fleet status</div>
          <div className="stat-foot" style={{ marginTop: 8 }}>
            {stats ? (
              <>
                <span className="chip chip-ok"><span className="dot-pulse" aria-hidden="true"></span>{connected} Connected</span>
                <span className="chip chip-danger"><Icon name="x-circle" />{unreachable} Unreachable</span>
                <span className="chip chip-warn"><Icon name="pause" />{disabled} Disabled</span>
              </>
            ) : (
              <span className="sk chip" style={{ width: 220 }} />
            )}
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
        </div>

        <div className="card stat">
          <div className="card-title" style={{ fontSize: "var(--t-md)" }}>Account & team</div>
          <div className="row" style={{ gap: 12, marginTop: 6, minWidth: 0 }}>
            <span className="avatar" style={{ width: 44, height: 44, background: "var(--lilac)", color: "var(--on-tint)", boxShadow: "none" }}>{initials(user?.email)}</span>
            <div style={{ minWidth: 0 }}>
              <b style={{ fontSize: "var(--t-md)", display: "block" }}>{displayName(user?.email) || user?.email}</b>
              <span className="small muted account-email">{user?.email}</span>
            </div>
          </div>
          <div className="stat-foot" style={{ marginTop: 4 }}>
            <span className="chip chip-neutral"><Icon name="user" />{isAdmin ? "Administrator" : "Member"}</span>
            {isAdmin && members !== null && (
              <span className="chip chip-neutral"><Icon name="users" />{members} members</span>
            )}
            <span className="chip chip-accent"><Icon name="key" />{activeKeys} active keys</span>
          </div>
          <Link className="link" to="/members" style={{ marginTop: 6 }}>Manage keys<Icon name="arrow-right" sm /></Link>
        </div>
      </section>

      {/* Servers card (admin, docs/11_OBSERVABILITY.md §2): per-server calls,
          error rate, p95 and a daily sparkline from /api/stats by_server. Sorted by
          calls (descending); real data only - servers with no rows in the range
          still show their status badge with zeros. */}
      {isAdmin && (
        <section className="card" aria-label="Servers">
          <div className="card-head">
            <div>
              <div className="card-title"><Icon name="server" />Servers</div>
            </div>
            <Link className="link" to="/servers">Open servers<Icon name="arrow-right" sm /></Link>
          </div>
          {loading && <span className="sk" style={{ width: "60%" }} />}
          {!loading && servers.length === 0 && <div className="small muted">No servers registered yet.</div>}
          {!loading && servers.length > 0 && (
            <div className="table-wrap">
              <table aria-label="Per-server calls">
                <thead>
                  <tr><th>Server</th><th>Status</th><th>Calls</th><th>Error rate</th><th>p95</th><th>Trend</th></tr>
                </thead>
                <tbody>
                  {[...servers]
                    .map((s) => {
                      const stat = (stats?.by_server ?? []).find((b) => b.server === s.slug) ?? null;
                      return {
                        s,
                        stat,
                        calls: stat?.calls ?? 0,
                      };
                    })
                    .sort((a, b) => b.calls - a.calls || a.s.slug.localeCompare(b.s.slug))
                    .map(({ s, stat }) => {
                      const st = STATUS_CHIP(!s.enabled ? "Disabled" : s.status);
                      const spark = stat?.sparkline ?? [];
                      const maxSpark = Math.max(...spark.map((p) => p.calls), 1);
                      return (
                        <tr key={s.id}>
                          <td data-label="Server"><span className="mono">{s.slug}</span></td>
                          <td data-label="Status">
                            <span className={`chip ${st.cls}`}><Icon name={st.icon} />{!s.enabled ? "Disabled" : s.status}</span>
                          </td>
                          <td data-label="Calls">{stat?.calls ?? 0}</td>
                          <td data-label="Error rate">{stat?.error_rate == null ? "-" : `${stat.error_rate}%`}</td>
                          <td data-label="p95">{fmtMs(stat?.p95_ms ?? 0)}</td>
                          <td data-label="Trend">
                            <svg width="120" height="28" viewBox="0 0 120 28" preserveAspectRatio="none" role="img" aria-label={`Daily calls sparkline for ${s.slug}`}>
                              <title>{s.slug} daily calls</title>
                              <g fill="var(--chart-bar)">
                                {spark.map((p, i) => {
                                  const h = maxSpark ? (p.calls / maxSpark) * 24 : 1;
                                  return (
                                    <rect key={p.date} x={1 + i * (118 / Math.max(spark.length, 1))}
                                      y={26 - h} width={Math.min(10, 118 / Math.max(spark.length, 1) - 2)} height={Math.max(h, 1)} rx="2" />
                                  );
                                })}
                              </g>
                            </svg>
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </main>
  );
}
