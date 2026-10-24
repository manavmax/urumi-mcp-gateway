/* Metrics (Phase 1 observability): per-server 24h aggregates computed from the
   audit table (GET /api/metrics, admin-only) - calls, errors, error rate,
   p50/p95 latency and the top classified failure reasons. Same table language
   as the fleet pages (Audit/Servers) and real data only. The Prometheus
   /metrics endpoint is separate (in-cluster only) and noted in the page sub. */
import { useEffect, useState } from "react";
import { api, type AuditMetricsRow } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Topbar } from "../components/Topbar";

function fmtMs(ms: number): string {
  if (ms < 1000) return `${ms.toLocaleString("en-US")} ms`;
  return `${(ms / 1000).toFixed(ms >= 10000 ? 1 : 2)} s`;
}
function fmtRate(rate: number | null): string {
  return rate === null ? "n/a" : `${rate.toFixed(1)}%`;
}
/* The failure reason is a safe category token (connection_refused, timeout,
   http_error:502, ...); humanize it without hiding the raw token. */
function fmtReason(reason: string): string {
  if (reason.startsWith("http_error:")) return `http error ${reason.split(":", 2)[1]}`;
  return reason.replace(/_/g, " ");
}

export default function Metrics() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [rows, setRows] = useState<AuditMetricsRow[]>([]);
  const [windowHours, setWindowHours] = useState(24);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api
      .auditMetrics()
      .then((data) => {
        if (!alive) return;
        setRows(data.servers);
        setWindowHours(data.window_hours);
      })
      .catch((e) => {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  if (!isAdmin) {
    return (
      <>
        <Topbar />
        <main className="content">
          <div className="page-head">
            <div>
              <h1>Metrics</h1>
            </div>
          </div>
          <div className="note-banner" role="status">
            Metrics are available to administrators only. See Overview for your own activity.
          </div>
        </main>
      </>
    );
  }

  return (
    <>
      <Topbar />
      <main className="content">
        <div className="page-head">
          <div>
            <h1>Metrics</h1>
          </div>
        </div>
        {err && (
          <div className="note-banner" role="alert">
            {err}
          </div>
        )}
        <section className="card" aria-label="Per-server metrics, last 24 hours">
          <div className="card-head">
            <h3 className="card-title">Upstream tool calls, last {windowHours}h</h3>
          </div>
          {loading ? (
            <div className="empty">Loading metrics...</div>
          ) : rows.length === 0 ? (
            <div className="empty">No tool calls in the last 24 hours.</div>
          ) : (
            <div className="table-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Server</th>
                    <th>Calls</th>
                    <th>Errors</th>
                    <th>Error rate</th>
                    <th>p50</th>
                    <th>p95</th>
                    <th>Top failure reasons</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((s) => (
                    <tr key={s.server}>
                      <td className="mono" data-label="Server">{s.server}</td>
                      <td className="num" data-label="Calls">{s.calls.toLocaleString("en-US")}</td>
                      <td className="num" data-label="Errors">{s.errors.toLocaleString("en-US")}</td>
                      <td className="num" data-label="Error rate">{fmtRate(s.error_rate)}</td>
                      <td className="num" data-label="P50">{fmtMs(s.p50_ms)}</td>
                      <td className="num" data-label="P95">{fmtMs(s.p95_ms)}</td>
                      <td data-label="Top failure reasons">
                        <div className="reasons">
                          {s.top_failures.length === 0 ? (
                            <span className="muted">none</span>
                          ) : (
                            s.top_failures.map((f) => (
                              <span
                                key={f.reason}
                                className="reason-chip"
                                title={`${f.count} call(s) failed with ${fmtReason(f.reason)}`}
                              >
                                {fmtReason(f.reason)} <b>{f.count}</b>
                              </span>
                            ))
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </>
  );
}
