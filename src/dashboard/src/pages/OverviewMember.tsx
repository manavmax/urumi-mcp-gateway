/* Member Overview (FIX 1): a distinct page for members built from the admin
   overview visual system. Reuses existing card, tile, badge, sparkline and
   motion components. No team-wide numbers; every number is the logged-in
   user's own from /api/stats (member scope), /api/audit and /api/keys.

   Contents, in a bento layout like the admin page:
     1. Greeting row ("Hello, <name>") + pill search
     2. "Getting started" card — 3 steps, real state, hidden once all done
     3. "Connect your client" card — MCP URL, usage note, active key count
     4. "My activity" — 3 tiles: calls (hero), success rate, p95 latency
     5. "Tools I can use" — grouped by server, status badge, click for description
     6. "Recent activity" — last 8 audit rows
     7. "Try in chat" — 3 suggestion cards, navigate with prefill (not sent)
*/
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type AuditRow, type Server, type Stats, type StatsRange, type Tool } from "../lib/api";
import { outcomeChip } from "../lib/audit-outcome";
import { useAuth } from "../lib/auth";
import { displayName } from "../lib/search";
import { useMockupMotion } from "../lib/motion";
import { Icon } from "../components/icons";

const RANGES: { key: StatsRange; label: string }[] = [
  { key: "day", label: "Day" },
  { key: "week", label: "Week" },
  { key: "month", label: "Month" },
];
const DEFAULT_RANGE: StatsRange = "week";

const STARTERS = [
  { tile: "var(--sky)", icon: "cart" as const, title: "Orders today", text: "What orders came in today?" },
  { tile: "var(--butter)", icon: "plus" as const, title: "Create a product", text: "Create product Urumi Tee $29.99 (write)" },
  { tile: "var(--lilac)", icon: "globe" as const, title: "World clock", text: "What time is it in Tokyo?" },
];

function fmtMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(ms >= 10000 ? 1 : 2)} s`;
  return `${ms} ms`;
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

const STATUS_CHIP = (status: string): { cls: string; icon: "check-circle" | "x-circle" | "pause" | "dot" } => {
  if (status === "Connected") return { cls: "chip-ok", icon: "check-circle" };
  if (status === "Unreachable") return { cls: "chip-danger", icon: "x-circle" };
  if (status === "Disabled") return { cls: "chip-warn", icon: "pause" };
  return { cls: "chip-neutral", icon: "dot" };
};

export default function OverviewMember() {
  const { user } = useAuth();
  const nav = useNavigate();
  const [range, setRange] = useState<StatsRange>(DEFAULT_RANGE);
  const [stats, setStats] = useState<Stats | null>(null);
  const [servers, setServers] = useState<Server[]>([]);
  const [tools, setTools] = useState<Record<string, Tool[]>>({});
  const [recent, setRecent] = useState<AuditRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [copiedMcp, setCopiedMcp] = useState(false);
  const [expandedTool, setExpandedTool] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setErr("");
      try {
        const [s, srv, auditRes, toolRes] = await Promise.all([
          api.stats(range),
          api.listServers().catch(() => ({ servers: [] as Server[] })),
          api.listAudit({ limit: 8 }),
          api.listTools().catch(() => ({ tools: [] as Tool[], warnings: [] as string[] })),
        ]);
        if (!alive) return;
        setStats(s);
        setServers(srv.servers);
        setRecent(auditRes.logs);
        const grouped: Record<string, Tool[]> = {};
        for (const t of toolRes.tools) {
          const key = t.server_slug || (t.name.includes("__") ? t.name.split("__")[0] : "unknown");
          (grouped[key] ||= []).push(t);
        }
        setTools(grouped);
      } catch (e: unknown) {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [range]);

  useMockupMotion(loading);

  const ownKeysActive = stats?.own_keys_active ?? 0;
  const ownApiKeyCalls = stats?.own_api_key_calls ?? 0;
  const ownCallsTotal = stats?.own_calls_total ?? 0;
  const myCalls = stats?.audit.calls ?? 0;
  const mySuccessRate = stats?.audit.success_rate;
  const myP95 = stats?.audit.p95_ms ?? 0;

  // Getting-started step state. Steps 2 and 3 read ALL-TIME account counters so
  // onboarding never un-completes when the chart range changes; the windowed
  // audit numbers only feed the hints and the tiles below.
  const stepCreateKey = ownKeysActive > 0;
  const stepConnectMcp = ownApiKeyCalls > 0;
  const stepFirstCall = ownCallsTotal > 0;
  const allStepsDone = stepCreateKey && stepConnectMcp && stepFirstCall;

  const GETTING_STARTED_STEPS = [
    {
      label: "Create an API key",
      done: stepCreateKey,
      hint: ownKeysActive > 0 ? `${ownKeysActive} active key${ownKeysActive > 1 ? "s" : ""}` : "No active keys yet",
    },
    {
      label: "Connect an MCP client",
      done: stepConnectMcp,
      hint: stepConnectMcp
        ? "You've made calls via an MCP client"
        : "Make your first call from an MCP client to complete this step",
    },
    {
      label: "Make a first call",
      done: stepFirstCall,
      hint: stepFirstCall
        ? (myCalls > 0
            ? `${myCalls} call${myCalls > 1 ? "s" : ""} in the last ${stats?.window_days ?? 14} days`
            : "First call complete")
        : "No calls yet",
    },
  ];

  // My activity sparklines
  const perDay = stats?.audit.per_day ?? [];
  const chartMetrics = useMemo(() => {
    const n = Math.max(perDay.length, 1);
    const maxCalls = Math.max(...perDay.map((d) => d.calls), 1);
    const niceMax = Math.max(50, Math.ceil(maxCalls / 50) * 50);
    const step = 588 / n;
    const barW = Math.min(24, Math.max(6, step - 10));
    return { n, niceMax, step, barW };
  }, [perDay]);

  const chartBars = useMemo(() => {
    const { n, niceMax, step, barW } = chartMetrics;
    return perDay.map((d, i) => {
      const h = (d.calls / niceMax) * 160;
      return { x: 36 + i * step + (step - barW) / 2, y: 168 - h, w: barW, h, day: d };
    });
  }, [perDay, chartMetrics]);

  const chartLabels = useMemo(() => {
    const { n, step } = chartMetrics;
    const le = Math.max(1, Math.ceil(n / 7));
    return perDay.map((d, i) => {
      const date = new Date(`${d.date}T00:00:00`);
      const text = date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
      return { x: 36 + i * step + step / 2, text, dayNum: date.getDate() };
    });
  }, [perDay, chartMetrics]);

  const mcpUrl = typeof window !== "undefined" ? `${window.location.origin}/mcp` : "";

  const windowDays = stats?.window_days ?? 14;

  function copyMcpUrl() {
    navigator.clipboard.writeText(mcpUrl).then(() => {
      setCopiedMcp(true);
      setTimeout(() => setCopiedMcp(false), 1400);
    });
  }

  function navigateWithPrefill(text: string) {
    nav("/chat", { state: { prefill: text } });
  }

  const name = displayName(user?.email) || "there";

  return (
    <main className="content">
      <header className="page-head">
        <div>
          <h1>Hello, {name}</h1>
        </div>
        <div className="head-actions">
          <form className="search" onSubmit={(e) => e.preventDefault()}>
            <input type="search" placeholder="Search my calls, servers, tools" aria-label="Search" />
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

      {/* ── Getting started card ── */}
      {!allStepsDone && (
        <section className="card gs-card" aria-label="Getting started">
          <div className="card-title" style={{ fontSize: "var(--t-md)", marginBottom: 16 }}>
            <Icon name="wrench" />Getting started
          </div>
          <div style={{ display: "grid", gap: 0 }}>
            {GETTING_STARTED_STEPS.map((step, i) => (
              <div
                key={i}
                className="feed-row"
                style={{ opacity: step.done ? 0.6 : 1 }}
              >
                <div
                  style={{
                    width: 28, height: 28, borderRadius: "50%",
                    background: step.done ? "var(--ink)" : "var(--surface-2)",
                    color: step.done ? "#fff" : "var(--text-muted)",
                    display: "grid", placeItems: "center", flex: "none",
                    fontSize: 12, fontWeight: 700,
                  }}
                >
                  {step.done ? <Icon name="check" sm /> : i + 1}
                </div>
                <div className="feed-main">
                  <div className="feed-title" style={{ fontWeight: 650 }}>{step.label}</div>
                  <div className="feed-sub">{step.hint}</div>
                </div>
                {!step.done && i === 0 && (
                  <Link to="/members" className="btn btn-secondary btn-sm">Create key</Link>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── Connect your client card ── */}
      <section className="card connect-card" aria-label="Connect your client">
        <div className="card-title" style={{ fontSize: "var(--t-md)", marginBottom: 12 }}>
          <Icon name="server" />Connect your client
        </div>
        <div style={{ display: "grid", gap: 12 }}>
          <div className="keybox" style={{ cursor: "default" }}>
            <code style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: "var(--t-sm)" }}>
              {mcpUrl || "configure gateway_url to set the MCP endpoint"}
            </code>
            {mcpUrl && (
              <button
                className="btn btn-secondary btn-sm"
                type="button"
                onClick={copyMcpUrl}
                style={{ flex: "none" }}
              >
                <Icon name="copy" sm />{copiedMcp ? "Copied" : "Copy"}
              </button>
            )}
          </div>
          <p className="small muted">
            Point your MCP client at this URL and authenticate with an API key header
            (<span className="mono">Authorization: Bearer &lt;key&gt;</span>).
            The gateway routes calls to enabled servers.
          </p>
          <div className="row wrap" style={{ gap: 8, alignItems: "center" }}>
            <span className="chip chip-accent">
              <Icon name="key" />{ownKeysActive} active key{ownKeysActive !== 1 ? "s" : ""}
            </span>
            <Link to="/members" className="link" style={{ fontSize: "var(--t-sm)" }}>
              Manage keys<Icon name="arrow-right" sm />
            </Link>
          </div>
        </div>
      </section>

      {/* ── My activity tiles ── */}
      <section className="bento activity-row" aria-label="My activity">
        {/* hero: my calls */}
        <div className="card stat hero">
          <div className="stat-label">My calls, {windowDays} days</div>
          <div className="stat-num">
            {stats ? myCalls.toLocaleString("en-US") : <span className="sk num" style={{ width: 100 }} />}
          </div>
          <div className="small" style={{ color: "var(--text)" }}>
            {myCalls === 0 ? "no calls yet" : `${myCalls} call${myCalls !== 1 ? "s" : ""} in ${windowDays} days`}
          </div>
        </div>
        {/* success rate sparkline */}
        <div className="card stat">
          <div className="stat-label">Success rate, {windowDays} days</div>
          <div className="stat-num" style={{ fontSize: 30 }}>
            {mySuccessRate == null ? "n/a" : `${mySuccessRate}%`}
          </div>
          <svg width="100%" height="34" viewBox="0 0 140 34" preserveAspectRatio="none" role="img" aria-label="Success rate sparkline">
            <title>Daily success rate</title>
            <g fill="#C9D2E2">
              {perDay.map((d, i) => {
                const ratio = d.calls ? (d.calls - d.errors) / d.calls : 0;
                const h = 4 + ratio * 26;
                return <rect key={d.date} x={2 + i * (136 / Math.max(perDay.length, 1))} y={32 - h} width={Math.min(12, 136 / Math.max(perDay.length, 1) - 2)} height={h} rx="3" />;
              })}
            </g>
          </svg>
          <div className="stat-foot">
            <span className="small muted">
              {mySuccessRate == null ? "no data" : `${((stats?.audit.errors ?? 0))} error${(stats?.audit.errors ?? 0) !== 1 ? "s" : ""}`}
            </span>
          </div>
        </div>
        {/* p95 latency sparkline */}
        <div className="card stat">
          <div className="stat-label">p95 latency, {windowDays} days</div>
          <div className="stat-num" style={{ fontSize: 30 }}>
            {fmtMs(myP95)}
          </div>
          <svg width="100%" height="34" viewBox="0 0 140 34" preserveAspectRatio="none" role="img" aria-label="p95 latency sparkline">
            <title>p95 latency trend</title>
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
      </section>

      {/* ── My calls per day chart ── */}
      <section className="bento ct-row" aria-label="My calls per day">
        <div className="card chart-card">
          <div className="card-head">
            <div>
              <div className="card-title">Calls per day</div>
              <div className="card-sub">Last {windowDays} days</div>
            </div>
          </div>
          <svg viewBox="0 0 640 205" width="100%" role="img" aria-label="Bar chart of calls per day">
            <g stroke="rgba(20,23,28,.06)" strokeWidth="1">
              <line x1="36" y1="168" x2="624" y2="168" />
              <line x1="36" y1="114.7" x2="624" y2="114.7" />
              <line x1="36" y1="61.3" x2="624" y2="61.3" />
              <line x1="36" y1="8" x2="624" y2="8" />
            </g>
            <g fill="#5F6673" fontSize="10" fontFamily="ui-monospace, Menlo, monospace" textAnchor="end">
              <text x="30" y="171">0</text>
              <text x="30" y="118">{Math.round(chartMetrics.niceMax / 3)}</text>
              <text x="30" y="65">{Math.round((chartMetrics.niceMax * 2) / 3)}</text>
              <text x="30" y="12">{chartMetrics.niceMax}</text>
            </g>
            <g fill="#C9D2E2">
              {chartBars.map((b) => (
                <rect key={b.day.date} x={b.x} y={b.y} width={b.w} height={Math.max(b.h, 0.5)} rx="5">
                  <title>{b.day.date}: {b.day.calls} calls</title>
                </rect>
              ))}
            </g>
            <g fill="#5F6673" fontSize="10" fontFamily="ui-monospace, Menlo, monospace" textAnchor="middle">
              {chartLabels.map((l, i) =>
                i % Math.max(1, Math.ceil(chartMetrics.n / 7)) === 0 || i === chartLabels.length - 1 ? (
                  <text key={i} x={l.x} y="188">{l.text}</text>
                ) : null,
              )}
            </g>
          </svg>
        </div>
        {/* Tools I can use — same visual as the servers page tool list */}
        <div className="card">
          <div className="card-head">
            <div className="card-title" style={{ fontSize: "var(--t-md)" }}><Icon name="wrench" />Tools I can use</div>
          </div>
          {servers.length === 0 && (
            <div className="small muted" style={{ padding: "12px 0" }}>No servers registered.</div>
          )}
          {servers.map((srv) => {
            const list = tools[srv.slug] || [];
            const st = STATUS_CHIP(!srv.enabled ? "Disabled" : srv.status);
            return (
              <details key={srv.id} className="tools" style={{ marginBottom: 8 }}>
                <summary>
                  {list.length} tool{list.length !== 1 ? "s" : ""} on <span className="mono">{srv.slug}</span>
                  <span className={`chip ${st.cls}`} style={{ marginLeft: 6 }}><Icon name={st.icon} />{!srv.enabled ? "Disabled" : srv.status}</span>
                  <Icon name="chevron" />
                </summary>
                <div className="tool-list">
                  {list.map((t) => (
                    <div key={t.name} className="tool-item">
                      <button
                        type="button"
                        onClick={() => setExpandedTool(expandedTool === t.name ? null : t.name)}
                        style={{ background: "none", border: "none", cursor: "pointer", padding: 0, font: "inherit", color: "var(--text)", fontWeight: 750, fontSize: "var(--t-xs)" }}
                        title={expandedTool === t.name ? "hide" : "show"}
                      >
                        {t.name}
                        <Icon name="chevron" style={{ width: 10, height: 10, display: "inline", marginLeft: 2 }} />
                      </button>
                      {expandedTool === t.name && t.description && (
                        <span style={{ display: "block", marginTop: 4, color: "var(--text-muted)", fontSize: "var(--t-xs)" }}>
                          {t.description}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </details>
            );
          })}
        </div>
      </section>

      {/* ── Recent activity ── */}
      <section className="card" aria-label="Recent activity">
        <div className="card-head">
          <div>
            <div className="card-title"><Icon name="clock" />Recent activity</div>
            <div className="card-sub">Latest tool calls</div>
          </div>
          <Link className="link" to="/audit">Audit<Icon name="arrow-right" sm /></Link>
        </div>
        {recent.length === 0 && (
          <div className="small muted" style={{ padding: "12px 0" }}>
            No tool calls in the audit trail yet.&nbsp;
            <Link to="/chat" style={{ color: "var(--primary-hover)" }}>Start in Chat</Link> to make your first call.
          </div>
        )}
        {recent.map((r) => (
          <div key={r.id} className="feed-row">
            <div className="feed-main">
              <div className="feed-title mono">{r.tool_exposed_name}</div>
              <div className="feed-sub">{r.server_slug} · {relative(r.ts)}</div>
            </div>
            <div className="feed-meta">
              <span className={`chip ${outcomeChip(r.outcome).cls}`}>
                <Icon name={outcomeChip(r.outcome).icon} />{r.outcome}
              </span>
              <span className="small faint mono">{fmtMs(r.duration_ms)}</span>
            </div>
          </div>
        ))}
      </section>

      {/* ── Try in chat ── */}
      <section className="card" aria-label="Try in chat">
        <div className="card-head">
          <div>
            <div className="card-title" style={{ fontSize: "var(--t-md)" }}><Icon name="chat" />Try in chat</div>
            <div className="card-sub">Pick a starter or ask anything, the model has access to all your tools.</div>
          </div>
        </div>
        <div className="suggestion-grid">
          {STARTERS.map((s) => (
            <div
              key={s.title}
              className="starter"
              role="button"
              tabIndex={0}
              onClick={() => navigateWithPrefill(s.text)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") navigateWithPrefill(s.text); }}
            >
              <span className="tile" style={{ background: s.tile }}><Icon name={s.icon} /></span>
              <b>{s.title}</b>
              <span>{s.text}</span>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
