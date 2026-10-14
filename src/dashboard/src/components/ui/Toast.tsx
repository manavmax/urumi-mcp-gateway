import * as React from "react";
export function ToastStack({ toasts }: { toasts: Array<{ id: string; message: string; tone?: "success" | "error" | "info" }> }) {
  if (!toasts.length) return null;
  return (
    <div className="toast-stack" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.tone === "error" ? "alert-error" : t.tone === "success" ? "alert-success" : ""}`}>{t.message}</div>
      ))}
    </div>
  );
}
