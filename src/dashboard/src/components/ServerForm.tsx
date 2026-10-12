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
    <form onSubmit={submit} className="form">
      {err && <div className="alert alert-error">{err}</div>}
      <label>
        Slug
        <input value={v.slug} onChange={(e) => setV({ ...v, slug: e.target.value })} placeholder="my-server" />
      </label>
      <label>
        URL (http/https, no private nets)
        <input value={v.url} onChange={(e) => setV({ ...v, url: e.target.value })} placeholder="http://my-mcp:8000/mcp" />
      </label>
      <label>
        Auth type
        <select value={v.auth_type} onChange={(e) => setV({ ...v, auth_type: e.target.value })}>
          <option value="none">none</option>
          <option value="bearer">bearer</option>
          <option value="header">header</option>
        </select>
      </label>
      {v.auth_type === "header" && (
        <label>
          Header name
          <input value={v.header_name} onChange={(e) => setV({ ...v, header_name: e.target.value })} placeholder="X-Token" />
        </label>
      )}
      {(v.auth_type === "bearer" || v.auth_type === "header") && (
        <label>
          Credential (stored encrypted, never shown again)
          <input value={v.credential} onChange={(e) => setV({ ...v, credential: e.target.value })} placeholder="token" type="password" />
        </label>
      )}
      <label>
        Timeout (ms)
        <input type="number" value={v.timeout_ms} onChange={(e) => setV({ ...v, timeout_ms: Number(e.target.value) })} min={1000} max={60000} step={1000} />
      </label>
      <label className="row">
        <input type="checkbox" checked={v.enabled} onChange={(e) => setV({ ...v, enabled: e.target.checked })} /> Enabled
      </label>
      <div className="row gap">
        <button type="submit" disabled={busy}>
          {busy ? "Saving..." : submitLabel}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
