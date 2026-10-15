/* Shared auth + cookie helpers for the dashboard scripts (parity.mjs,
   screenshots.mjs, and any verify-*.mjs probe). One login contract, one
   cookie-priming path: scripts sign in over the real /api/auth/login chain and
   seed EVERY cookie from the response via context.addCookies, so a renamed or
   extra session cookie cannot silently break one script while the other keeps
   working. The admin password is read from the gateway-admin Secret unless
   GATEWAY_ADMIN_PASSWORD is set; it is never printed. */

export async function httpJson(url, { method = "GET", body, headers = {}, cookie } = {}) {
  const h = { "Content-Type": "application/json", ...headers };
  if (cookie) h["Cookie"] = cookie;
  const res = await fetch(url, { method, headers: h, body: body ? JSON.stringify(body) : undefined });
  const text = await res.text();
  let json = null;
  try { json = JSON.parse(text); } catch { /* not json */ }
  return { res, text, json, ok: res.ok, status: res.status, setCookie: res.headers.get("set-cookie") || "" };
}

export function parseCookie(setCookieHeader) {
  return setCookieHeader.split(",").map((s) => s.split(";")[0].trim()).filter(Boolean).join("; ");
}

async function adminPassword() {
  if (process.env.GATEWAY_ADMIN_PASSWORD) return process.env.GATEWAY_ADMIN_PASSWORD;
  const { execSync } = await import("node:child_process");
  return execSync("kubectl get secret gateway-admin -n urumi -o jsonpath='{.data.password}' | base64 -d", { encoding: "utf8" }).trim();
}

export async function adminLogin(dashboardUrl) {
  const email = process.env.GATEWAY_ADMIN_EMAIL || "admin@urumi.local";
  const pass = await adminPassword();
  const r = await loginAs(dashboardUrl, email, pass);
  if (!r.cookie) throw new Error(`admin login failed (no session cookie) ${r.status}`);
  return { cookie: r.cookie, csrf: r.csrf, email, pass };
}

export async function loginAs(dashboardUrl, email, password) {
  const r = await httpJson(`${dashboardUrl}/api/auth/login`, { method: "POST", body: { email, password } });
  if (!r.ok) throw new Error(`login ${email} failed ${r.status} ${r.text.slice(0, 300)}`);
  return { cookie: parseCookie(r.setCookie), csrf: r.json?.csrf_token || "" };
}

export async function createThrowawayMember(dashboardUrl, adminCookie, adminCsrf, prefix) {
  const { randomUUID } = await import("node:crypto");
  const email = `${prefix}${randomUUID().slice(0, 8)}@example.invalid`;
  const password = `Tmp-${randomUUID().slice(0, 12)}-a1!`;
  const r = await httpJson(`${dashboardUrl}/api/users`, {
    method: "POST", body: { email, password, role: "member" },
    cookie: adminCookie, headers: { "X-CSRF-Token": adminCsrf },
  });
  if (!r.ok) throw new Error(`create member failed ${r.status} ${r.text.slice(0, 300)}`);
  return { email, password, id: r.json?.id };
}

export async function deleteMember(dashboardUrl, adminCookie, adminCsrf, userId) {
  const r = await httpJson(`${dashboardUrl}/api/users/${userId}`, {
    method: "DELETE", cookie: adminCookie, headers: { "X-CSRF-Token": adminCsrf },
  });
  if (!r.ok && r.status !== 204) console.error(`  ! delete member ${userId} -> ${r.status} ${r.text.slice(0, 200)}`);
}

export function cookiePair(cookieHeader, dashboardUrl) {
  return cookieHeader.split(";").map((c) => {
    const [name, ...rest] = c.trim().split("=");
    return { name, value: rest.join("="), domain: new URL(dashboardUrl).hostname, path: "/" };
  }).filter((c) => c.name && c.value);
}
