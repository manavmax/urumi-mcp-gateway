export function Badge({ tone = "unknown", children }: { tone?: "success" | "danger" | "warn" | "neutral" | "unknown"; children: React.ReactNode }) {
  const cls = tone === "success" ? "badge-connected" : tone === "danger" ? "badge-unreachable" : tone === "warn" ? "badge-timeout" : tone === "neutral" ? "badge-disabled" : "badge-unknown";
  return <span className={`badge ${cls}`}>{children}</span>;
}
export function OutcomeBadge({ outcome }: { outcome: string }) {
  const o = (outcome || "").toLowerCase();
  if (o === "success") return <Badge tone="success">success</Badge>;
  if (o === "timeout") return <Badge tone="warn">timeout</Badge>;
  if (o === "upstream_error" || o === "circuit_open") return <Badge tone="danger">{o}</Badge>;
  if (o === "permission_denied" || o === "validation_error") return <Badge tone="danger">{o}</Badge>;
  return <Badge tone="unknown">{outcome || "unknown"}</Badge>;
}
