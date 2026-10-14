export function StatusBadge({ status }: { status: string }) {
  const normalized = (status || "Unknown").toLowerCase();
  let cls = "badge-unknown";
  let label = status || "Unknown";
  if (normalized === "connected" || normalized === "ok" || normalized === "healthy") { cls = "badge-connected"; label = "Connected"; }
  else if (normalized === "unreachable" || normalized === "error" || normalized === "down") { cls = "badge-unreachable"; label = "Unreachable"; }
  else if (normalized === "disabled") { cls = "badge-disabled"; label = "Disabled"; }
  return <span className={`badge ${cls}`} aria-label={label}>{label}</span>;
}
