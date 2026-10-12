export function StatusBadge({ status }: { status: string }) {
  const normalized = (status || "Unknown").toLowerCase();
  let cls = "badge-unknown";
  if (normalized === "connected" || normalized === "ok" || normalized === "healthy") cls = "badge-connected";
  else if (normalized === "unreachable" || normalized === "error" || normalized === "down") cls = "badge-unreachable";
  else if (normalized === "disabled") cls = "badge-disabled";
  return <span className={`badge ${cls}`}>{status}</span>;
}
