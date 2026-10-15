/* Audit, exact port of design/mockups/audit.html (family F) with real data
   from GET /api/audit. The mockup's CSV export button was disabled and marked
   NEEDS DECISION; the decision is implemented (GET /api/audit/export,
   admin-only server-side, 5000-row cap, tested in tests/test_stats_scoping.py),
   so the button is live and passes the current filters. Range buttons compute
   from/to on the client exactly as the mockup documents. */
import { useEffect, useMemo, useState } from "react";
import { api, type AuditRow } from "../lib/api";
import { outcomeChip } from "../lib/audit-outcome";
import { useAuth } from "../lib/auth";
import { useSearch } from "../lib/search";
import { useMockupMotion } from "../lib/motion";
import { Topbar } from "../components/Topbar";
import { Icon } from "../components/icons";

const LIMIT = 100;
const RANGES: { label: string; days: number | null }[] = [
  { label: "Day", days: 1 },
  { label: "Week", days: 7 },
  { label: "Month", days: 30 },
];

function fmtTs(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}
function fmtDuration(ms: number): string {
  if (ms < 1000) return `${ms.toLocaleString("en-US")} ms`;
  return `${(ms / 1000).toFixed(ms >= 10000 ? 1 : 2)} s`;
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
export default function Audit() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { query } = useSearch();
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState("");
  const [exporting, setExporting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [rangeIdx, setRangeIdx] = useState(-1);
  const [filters, setFilters] = useState({ user: "", server: "", tool: "", outcome: "", offset: 0 });
  /* text/select filters are a draft until Apply: every keystroke used to refetch
     the whole audit page, and changing a filter while paged deep into the
     results kept a stale offset (empty pages). Range and pagination still apply
     immediately because they are deliberate single actions. */
  const [draft, setDraft] = useState({ user: "", server: "", tool: "", outcome: "" });

  const apiParams = useMemo(() => {
    const params: Record<string, string | number | undefined> = {
      user_id: isAdmin ? filters.user || undefined : undefined,
      server: filters.server || undefined,
      tool: filters.tool || undefined,
      outcome: filters.outcome || undefined,
      limit: LIMIT,
      offset: filters.offset,
    };
    const r = RANGES[rangeIdx];
    if (r) {
      const now = new Date();
      const from = new Date(now.getTime() - r.days! * 86400000);
      params.from = from.toISOString();
      params.to = now.toISOString();
    }
    return params;
  }, [filters, rangeIdx, isAdmin]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setErr("");
    (async () => {
      try {
        const res = await api.listAudit(apiParams);
        if (!alive) return;
        setRows(res.logs);
        setTotal(res.total);
      } catch (e: unknown) {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [apiParams]);

  useMockupMotion(loading);

  /* the topbar search narrows the loaded page client-side */
  const q = query.trim().toLowerCase();
  const shown = q
    ? rows.filter((r) =>
        `${r.user_email || ""} ${r.server_slug} ${r.tool_exposed_name} ${r.tool_upstream_name} ${r.outcome}`.toLowerCase().includes(q))
    : rows;
  const successes = rows.filter((r) => r.outcome === "success").length;

  async function exportCsv() {
    setExporting(true);
    setErr("");
    try {
      /* export exactly what the table is showing: the same committed filters and
         range window the last fetch used, minus the page's limit/offset (the CSV
         is the full result set, admin-only and server-capped at 5000 rows) */
      const { limit, offset, ...csvParams } = apiParams;
      await api.exportAuditCsv(csvParams);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  }

  return (
    <>
      <Topbar />
      <main className="content">
        <div className="page-head">
          <div>
            <h1>Audit</h1>
          </div>
          <div className="row wrap">
            {isAdmin && (
              <button className="btn btn-secondary" type="button" onClick={exportCsv} disabled={exporting}
                title="Exports the current filters, capped at 5000 rows">
                <Icon name="download" sm />{exporting ? "Exporting…" : "CSV export"}
              </button>
            )}
          </div>
        </div>

        <div className="note-banner">
          <Icon name="eye" />
          <div>
            <b>Scoping:</b> admins see all rows and can filter by user; members see only their own rows (enforced server-side).
            The user filter below is hidden for members.
          </div>
        </div>

        {/* filters */}
        <section className="card">
          <div className="card-head">
            <div className="card-title"><Icon name="filter" />Filters</div>
          </div>
          <form className="filters" onSubmit={(e) => { e.preventDefault(); setFilters((f) => ({ ...draft, offset: 0 })); }}>
            {isAdmin && (
              <div className="field grow">
                <label htmlFor="f-user">User (admin)</label>
                <input id="f-user" placeholder="email or id, any" value={draft.user}
                  onChange={(e) => setDraft({ ...draft, user: e.target.value })} />
              </div>
            )}
            <div className="field">
              <label htmlFor="f-server">Server</label>
              <input id="f-server" placeholder="slug, any" value={draft.server}
                onChange={(e) => setDraft({ ...draft, server: e.target.value })} />
            </div>
            <div className="field grow">
              <label htmlFor="f-tool">Tool</label>
              <input id="f-tool" placeholder="exposed name, any" value={draft.tool}
                onChange={(e) => setDraft({ ...draft, tool: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="f-outcome">Outcome</label>
              <select id="f-outcome" value={draft.outcome} onChange={(e) => setDraft({ ...draft, outcome: e.target.value })}>
                <option value="">any outcome</option>
                <option value="success">success</option>
                <option value="timeout">timeout</option>
                <option value="upstream_error">upstream_error</option>
                <option value="circuit_open">circuit_open</option>
                <option value="permission_denied">permission_denied</option>
                <option value="validation_error">validation_error</option>
              </select>
            </div>
            <div className="field" style={{ flex: "0 0 auto" }}>
              <label>Range</label>
              <div className="seg" role="group" aria-label="Range">
                {RANGES.map((r, i) => (
                  <button key={r.label} type="button" className={rangeIdx === i ? "on" : ""} aria-pressed={rangeIdx === i}
                    onClick={() => { setRangeIdx(rangeIdx === i ? -1 : i); setFilters((f) => ({ ...f, offset: 0 })); }}>
                    {r.label}
                  </button>
                ))}
              </div>
            </div>
            <button className="btn btn-primary" type="submit">Apply</button>
            <button className="btn btn-ghost" type="reset"
              onClick={() => { setDraft({ user: "", server: "", tool: "", outcome: "" }); setFilters({ user: "", server: "", tool: "", outcome: "", offset: 0 }); setRangeIdx(-1); }}>
              Clear
            </button>
          </form>
        </section>

        {/* table */}
        <section className="card">
          <div className="card-head">
            <div>
              <div className="card-title"><Icon name="shield" />Tool calls</div>
              <div className="card-sub">
                Total <b className="mono">{total.toLocaleString("en-US")}</b>, showing <b className="mono">{rows.length ? filters.offset + 1 : 0} to {filters.offset + rows.length}</b> (limit {LIMIT}) · sorted newest first
              </div>
            </div>
            <span className="row small muted">
              {rows.length > 0 && (
                <span className="chip chip-ok"><Icon name="check-circle" />{Math.round((successes / rows.length) * 100)}% success</span>
              )}
            </span>
          </div>
          {err && <div className="err" role="alert">{err}</div>}
          {loading ? (
            <div style={{ display: "grid", gap: 10 }}>
              <span className="sk" style={{ width: "90%" }} />
              <span className="sk" style={{ width: "75%" }} />
              <span className="sk" style={{ width: "82%" }} />
            </div>
          ) : shown.length === 0 ? (
            <div className="small muted">No audit rows for the current filters.</div>
          ) : (
            <table aria-label="Audit log">
              <thead>
                <tr><th>Time</th><th>User</th><th>Server</th><th>Tool</th><th>Outcome</th><th>Duration</th><th>Request</th></tr>
              </thead>
              <tbody>
                {shown.map((r) => {
                  const chip = outcomeChip(r.outcome);
                  return (
                    <tr key={r.id}>
                      <td data-label="Time">
                        <div className="small">{fmtTs(r.ts)}</div>
                        <div className="sub">{relative(r.ts)}</div>
                      </td>
                      <td data-label="User">
                        <div className="small mono">{r.user_email || "unknown"}</div>
                        {r.user_id && <div className="sub">{r.user_id.slice(0, 8)}…</div>}
                      </td>
                      <td data-label="Server" className="small mono">{r.server_slug}</td>
                      <td data-label="Tool">
                        <div className="tool-name">{r.tool_exposed_name}</div>
                        <div className="sub">upstream: {r.tool_upstream_name}</div>
                      </td>
                      <td data-label="Outcome">
                        <span className={`chip ${chip.cls}`}><Icon name={chip.icon} />{r.outcome}</span>
                        {r.error_code && r.error_code !== r.outcome && <div className="sub">code: {r.error_code}</div>}
                      </td>
                      <td data-label="Duration" className="small mono">{fmtDuration(r.duration_ms)}</td>
                      <td data-label="Request" className="small mono" title={r.request_id}>{r.request_id.slice(0, 8)}…</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          <div className="pager">
            <span className="small muted">
              Showing {rows.length ? filters.offset + 1 : 0} to {filters.offset + rows.length} of <b className="mono">{total.toLocaleString("en-US")}</b> · offset {filters.offset} · limit {LIMIT}
            </span>
            <div className="row">
              <button className="btn btn-secondary btn-sm" type="button" disabled={filters.offset === 0}
                onClick={() => setFilters((f) => ({ ...f, offset: Math.max(0, f.offset - LIMIT) }))}>Prev</button>
              <button className="btn btn-secondary btn-sm" type="button" disabled={rows.length < LIMIT}
                onClick={() => setFilters((f) => ({ ...f, offset: f.offset + LIMIT }))}>Next</button>
            </div>
          </div>
        </section>
      </main>
    </>
  );
}
