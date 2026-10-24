import { useState } from "react";

export type ServerFormValues = {
  slug: string;
  url: string;
  auth_type: string;
  header_name: string;
  credential: string;
  timeout_ms: number;
  enabled: boolean;
};

/* Add/Edit server modal fields, ported from design/mockups/servers.html
   (.field, .hint, .grid-2 markup). Same validation and payload as before. */
export function ServerForm({
  initial,
  onSubmit,
  onCancel,
  submitLabel = "Save",
}: {
  initial?: Partial<ServerFormValues>;
  onSubmit: (v: ServerFormValues) => Promise<void>;
  onCancel: () => void;
  submitLabel?: string;
}) {
  const [v, setV] = useState<ServerFormValues>({
    slug: initial?.slug || "",
    url: initial?.url || "",
    auth_type: initial?.auth_type || "none",
    header_name: initial?.header_name || "",
    credential: initial?.credential || "",
    timeout_ms: initial?.timeout_ms || 10000,
    enabled: initial?.enabled ?? true,
  });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    if (!v.slug || !v.url) {
      setErr("slug and url are required");
      return;
    }
    setBusy(true);
    try {
      await onSubmit(v);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <div className="field">
        <label htmlFor="f-slug">Slug</label>
        <input id="f-slug" value={v.slug} onChange={(e) => setV({ ...v, slug: e.target.value })} placeholder="my-mcp" />
        <div className="hint">lowercase letters, numbers and dashes</div>
      </div>
      <div className="field">
        <label htmlFor="f-url">URL</label>
        <input id="f-url" value={v.url} onChange={(e) => setV({ ...v, url: e.target.value })} placeholder="https://mcp.internal.example.com/mcp" />
      </div>
      <div className="grid-2">
        <div className="field">
          <label htmlFor="f-auth">Auth type</label>
          <select id="f-auth" value={v.auth_type} onChange={(e) => setV({ ...v, auth_type: e.target.value })}>
            <option value="none">none</option>
            <option value="bearer">bearer</option>
            <option value="header">header</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-timeout">Timeout (ms)</label>
          <input id="f-timeout" type="number" value={v.timeout_ms} min={1000} max={60000} step={1000}
            onChange={(e) => setV({ ...v, timeout_ms: Number(e.target.value) })} />
        </div>
      </div>
      {v.auth_type === "header" && (
        <div className="field">
          <label htmlFor="f-header">Header name</label>
          <input id="f-header" value={v.header_name} onChange={(e) => setV({ ...v, header_name: e.target.value })} placeholder="X-Token" />
        </div>
      )}
      {(v.auth_type === "bearer" || v.auth_type === "header") && (
        <div className="field">
          <label htmlFor="f-cred">Credential (optional)</label>
          <input id="f-cred" type="password" value={v.credential} onChange={(e) => setV({ ...v, credential: e.target.value })}
            placeholder="encrypted at rest, never returned" />
        </div>
      )}
      <div className="field">
        <label htmlFor="f-enabled">Enabled</label>
        <input id="f-enabled" type="checkbox" checked={v.enabled} onChange={(e) => setV({ ...v, enabled: e.target.checked })}
          style={{ width: 16, height: 16, justifySelf: "start" }} />
      </div>
      {err && <div className="err" role="alert">{err}</div>}
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 4 }}>
        <button className="btn btn-ghost" type="button" onClick={onCancel}>Cancel</button>
        <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "Saving…" : submitLabel}</button>
      </div>
    </form>
  );
}
