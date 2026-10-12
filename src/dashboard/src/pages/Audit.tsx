import { useEffect, useState } from "react";
import { api, type AuditRow } from "../lib/api";

function outcomeClass(o: string) {
  if (o === "success") return "badge-connected";
  if (o === "timeout") return "badge-timeout";
  if (o === "upstream_error" || o === "error") return "badge-unreachable";
  if (o === "permission_denied") return "badge-unreachable";
  return "badge-unknown";
}

export default function Audit() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState("");
  const [filters, setFilters] = useState({ server: "", tool: "", outcome: "", limit: 100, offset: 0 });

  async function load() {
    setErr("");
    try {
      const res = await api.listAudit({
        server: filters.server || undefined,
        tool: filters.tool || undefined,
        outcome: filters.outcome || undefined,
        limit: filters.limit,
        offset: filters.offset,
      });
      setRows(res.logs);
      setTotal(res.total);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.offset]);

  return (
    <div>
      <h2>Audit</h2>
      <div className="card row gap wrap">
        <input placeholder="server slug" value={filters.server} onChange={(e) => setFilters({ ...filters, server: e.target.value })} />
        <input placeholder="tool (exposed name)" value={filters.tool} onChange={(e) => setFilters({ ...filters, tool: e.target.value })} />
        <select value={filters.outcome} onChange={(e) => setFilters({ ...filters, outcome: e.target.value })}>
          <option value="">any outcome</option>
          <option value="success">success</option>
          <option value="timeout">timeout</option>
          <option value="upstream_error">upstream_error</option>
          <option value="permission_denied">permission_denied</option>
        </select>
        <button onClick={() => setFilters({ ...filters, offset: 0 })} className="secondary">
          Filter
        </button>
        <button
          onClick={() => {
            setFilters({ server: "", tool: "", outcome: "", limit: 100, offset: 0 });
            setTimeout(load, 0);
          }}
          className="secondary"
        >
          Clear
        </button>
      </div>
      {err && <div className="alert alert-error">{err}</div>}
      <div className="muted small">Total: {total} — showing {rows.length} (offset {filters.offset})</div>
      <table className="table">
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
              <td className="small">{new Date(r.ts).toLocaleString()}</td>
              <td className="mono small">{r.user_id?.slice(0, 8) || "—"}</td>
              <td>{r.server_slug}</td>
              <td className="mono small">{r.tool_exposed_name}</td>
              <td>
                <span className={`badge ${outcomeClass(r.outcome)}`}>{r.outcome}</span>
                {r.error_code && <span className="small muted"> {r.error_code}</span>}
              </td>
              <td className="small">{r.duration_ms} ms</td>
              <td className="mono small">{r.request_id.slice(0, 8)}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={7} className="muted">
                No audit rows.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="row gap">
        <button disabled={filters.offset === 0} onClick={() => setFilters({ ...filters, offset: Math.max(0, filters.offset - filters.limit) })}>
          Prev
        </button>
        <button disabled={rows.length < filters.limit} onClick={() => setFilters({ ...filters, offset: filters.offset + filters.limit })}>
          Next
        </button>
      </div>
    </div>
  );
}
