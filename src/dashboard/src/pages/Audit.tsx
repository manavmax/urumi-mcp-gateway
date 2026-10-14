import { useEffect, useMemo, useState } from "react";
import { api, type AuditRow } from "../lib/api";
import { OutcomeBadge } from "../components/ui/Badge";
import { EmptyState, InlineError, LoadingRows } from "../components/ui/EmptyState";
import { TableWrap } from "../components/ui/Table";

function fmtTs(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  // Locale-aware, short but readable. Keep date+time.
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
function fmtDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(ms >= 10000 ? 1 : 2)} s`;
}

export default function Audit() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ user: "", server: "", tool: "", outcome: "", limit: 100, offset: 0 });

  const activeFilterCount = useMemo(() => [filters.user, filters.server, filters.tool, filters.outcome].filter(Boolean).length, [filters]);

  async function load(nextOffset = filters.offset) {
    setErr("");
    setLoading(true);
    try {
      const res = await api.listAudit({
        user_id: filters.user || undefined,
        server: filters.server || undefined,
        tool: filters.tool || undefined,
        outcome: filters.outcome || undefined,
        limit: filters.limit,
        offset: nextOffset,
      });
      setRows(res.logs);
      setTotal(res.total);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load(filters.offset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.offset]);

  const onApply = () => {
    setFilters((f) => ({ ...f, offset: 0 }));
    load(0);
  };
  const onClear = () => {
    setFilters({ user: "", server: "", tool: "", outcome: "", limit: 100, offset: 0 });
    setTimeout(() => load(0), 0);
  };

  return (
    <div className="stack">
      <div className="page-head">
        <h2>Audit</h2>
        <span className="small muted">{loading ? "Loading…" : `Total ${total} — showing ${rows.length} (offset ${filters.offset})`}</span>
      </div>

      <div className="toolbar" role="search" aria-label="Audit filters">
        <input placeholder="user email or id" value={filters.user} onChange={(e) => setFilters({ ...filters, user: e.target.value })} aria-label="Filter by user" style={{ minWidth: 180 }} />
        <input placeholder="server slug" value={filters.server} onChange={(e) => setFilters({ ...filters, server: e.target.value })} aria-label="Filter by server" style={{ minWidth: 160 }} />
        <input placeholder="tool (exposed name)" value={filters.tool} onChange={(e) => setFilters({ ...filters, tool: e.target.value })} aria-label="Filter by tool" style={{ minWidth: 200 }} />
        <select value={filters.outcome} onChange={(e) => setFilters({ ...filters, outcome: e.target.value })} aria-label="Filter by outcome">
          <option value="">any outcome</option>
          <option value="success">success</option>
          <option value="timeout">timeout</option>
          <option value="upstream_error">upstream_error</option>
          <option value="circuit_open">circuit_open</option>
          <option value="permission_denied">permission_denied</option>
          <option value="validation_error">validation_error</option>
        </select>
        <button onClick={onApply} className="secondary">Apply{activeFilterCount ? ` · ${activeFilterCount}` : ""}</button>
        <button onClick={onClear} className="ghost small">Clear</button>
        <span className="small muted">Members see only their own rows. Admins see all and can filter by user.</span>
      </div>

      {err && <InlineError message={err} onRetry={() => load(filters.offset)} />}

      {loading ? (
        <div className="card"><LoadingRows rows={6} /></div>
      ) : rows.length === 0 ? (
        <EmptyState title="No audit rows" hint={activeFilterCount ? "Try clearing filters or adjusting the range." : "Tool calls will appear here as they are audited."} />
      ) : (
        <TableWrap>
          <table className="table" aria-label="Audit log">
            <thead>
              <tr>
                <th>Time</th>
                <th>User</th>
                <th>Server</th>
                <th>Tool</th>
                <th>Outcome</th>
                <th>Duration</th>
                <th>Request</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="small" title={r.ts}>{fmtTs(r.ts)}</td>
                  <td className="small">
                    {r.user_email ? <span title={r.user_email}>{r.user_email}</span> : <span className="mono" title={r.user_id || ""}>{r.user_id?.slice(0, 8) || "—"}</span>}
                    {r.user_email && r.user_id && <div className="mono faint" style={{ fontSize: 11 }}>{r.user_id.slice(0, 8)}</div>}
                  </td>
                  <td className="small mono">{r.server_slug}</td>
                  <td className="small mono break" title={r.tool_upstream_name}>{r.tool_exposed_name}</td>
                  <td>
                    <OutcomeBadge outcome={r.outcome} />
                    {r.error_code && r.error_code !== r.outcome && <span className="small muted" style={{ marginLeft: 6 }}>{r.error_code}</span>}
                  </td>
                  <td className="small mono">{fmtDuration(r.duration_ms)}</td>
                  <td className="mono small" title={r.request_id}>{r.request_id.slice(0, 8)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}

      <div className="row gap">
        <button disabled={filters.offset === 0} className="secondary small" onClick={() => setFilters({ ...filters, offset: Math.max(0, filters.offset - filters.limit) })}>Prev</button>
        <button disabled={rows.length < filters.limit} className="secondary small" onClick={() => setFilters({ ...filters, offset: filters.offset + filters.limit })}>Next</button>
      </div>
    </div>
  );
}
