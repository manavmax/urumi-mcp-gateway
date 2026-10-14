export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="empty">
      <div style={{ fontWeight: 800 }}>{title}</div>
      {hint && <div className="small muted" style={{ marginTop: 6 }}>{hint}</div>}
    </div>
  );
}
export function Skeleton({ h = 14, w = "100%" }: { h?: number; w?: string | number }) {
  return <div className="skeleton" style={{ height: h, width: w }} />;
}
export function InlineError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="alert alert-error row gap">
      <span className="flex1">{message}</span>
      {onRetry && <button className="secondary small" onClick={onRetry}>Retry</button>}
    </div>
  );
}
export function LoadingRows({ rows = 3 }: { rows?: number }) {
  return (
    <div className="stack" style={{ gap: 8 }}>
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} h={44} />)}
    </div>
  );
}
