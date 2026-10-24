#!/usr/bin/env node
/**
 * Generate REAL traffic through the local gateway (kind cluster, urumi
 * namespace) so the dashboard pages show live data. No fake rows: every audit
 * row comes from a real JSON-RPC tools/call over POST /mcp with a real API
 * key created through the dashboard API.
 *
 * Usage: node gen-traffic.mjs   (GW_PASS env overrides the secret read)
 *
 * The two schema-invalid calls near the end are real client mistakes (a
 * 100-char timezone against a 64-char field) that the gateway classifies as
 * validation_error - genuine traffic, not inserted rows.
 */
import { execSync } from "node:child_process";

const BASE = "http://dashboard.127.0.0.1.nip.io";
const EMAIL = "admin@urumi.local";

function adminPassword() {
  const b64 = execSync(
    "kubectl get secret gateway-admin -n urumi -o jsonpath='{.data.password}'",
    { encoding: "utf8" },
  ).trim();
  return Buffer.from(b64, "base64").toString("utf8");
}

async function main() {
  const password = process.env.GW_PASS || adminPassword();

  const loginRes = await fetch(`${BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: EMAIL, password }),
  });
  if (!loginRes.ok) throw new Error(`login failed: ${loginRes.status} ${await loginRes.text()}`);
  const me = await loginRes.json();
  const cookie = (loginRes.headers.getSetCookie?.() ?? [])
    .map((c) => c.split(";")[0])
    .join("; ");
  console.log(`logged in as ${me.user?.email ?? "?"}`);

  // create an API key (shown once - captured here, never printed in full)
  const keyRes = await fetch(`${BASE}/api/keys`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": me.csrf_token, cookie },
    body: JSON.stringify({}),
  });
  if (!keyRes.ok) throw new Error(`key create failed: ${await keyRes.text()}`);
  const keyBody = await keyRes.json();
  const key = keyBody.key;
  console.log(`api key created: ${String(key).slice(0, 12)}...`);

  const mcpHeaders = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${key}`,
  };
  let rpcId = 1;

  async function rpc(method, params) {
    const r = await fetch(`${BASE}/mcp`, {
      method: "POST",
      headers: mcpHeaders,
      body: JSON.stringify({ jsonrpc: "2.0", id: rpcId++, method, params: params ?? {} }),
    });
    const body = await r.json();
    return { status: r.status, body };
  }

  const init = await rpc("initialize", {
    protocolVersion: "2024-11-05",
    capabilities: {},
    clientInfo: { name: "urumi-traffic-gen", version: "0.1.0" },
  });
  if (!init.body?.result) {
    throw new Error(`initialize failed: ${JSON.stringify(init.body).slice(0, 300)}`);
  }
  await fetch(`${BASE}/mcp`, {
    method: "POST",
    headers: mcpHeaders,
    body: JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }),
  });

  const list = await rpc("tools/list", {});
  const tools = list.body?.result?.tools ?? [];
  console.log(`tools available: ${tools.length}`);
  for (const t of tools) console.log(`  - ${t.name}`);

  const timeTool = tools.find((t) => t.name.includes("get_current_time"));
  const listOrders = tools.find((t) => t.name.startsWith("woo__") && t.name.endsWith("__list_orders"));
  const listProducts = tools.find((t) => t.name.startsWith("woo__") && t.name.endsWith("__list_products"));
  const listNotes = tools.find((t) => t.name.endsWith("__list_notes"));
  const getOrders = tools.find((t) => t.name.startsWith("woo__") && t.name.endsWith("__get_order"));
  const searchNotes = tools.find((t) => t.name.endsWith("__search_notes"));
  if (!timeTool) throw new Error("no get_current_time tool found");

  const plan = [];
  for (let i = 0; i < 14; i++) plan.push({ name: timeTool.name, args: {} }); // default zone
  for (const tz of ["Europe/Berlin", "Asia/Tokyo", "America/New_York", "Asia/Kolkata", "Pacific/Auckland"]) {
    plan.push({ name: timeTool.name, args: { timezone_name: tz } });
  }
  if (listOrders) for (let i = 0; i < 8; i++) plan.push({ name: listOrders.name, args: {} });
  if (getOrders) for (const id of [1, 2, 3]) plan.push({ name: getOrders.name, args: { id } });
  if (listProducts) for (let i = 0; i < 10; i++) plan.push({ name: listProducts.name, args: {} });
  if (listNotes) for (let i = 0; i < 8; i++) plan.push({ name: listNotes.name, args: {} });
  if (searchNotes) {
    for (const q of ["hello", "note", "urumi"]) {
      plan.push({ name: searchNotes.name, args: { query: q } });
    }
  }
  // two real client mistakes: schema violations (timezone_name max_length=64)
  plan.push({ name: timeTool.name, args: { timezone_name: "x".repeat(100) } });
  plan.push({ name: timeTool.name, args: { timezone_name: "x".repeat(120) } });

  let ok = 0;
  for (const call of plan) {
    const r = await rpc("tools/call", { name: call.name, arguments: call.args });
    const accepted = r.status === 200 && !r.body?.error;
    if (accepted) ok++;
    else console.log(`  ${call.name} -> ${r.status} ${JSON.stringify(r.body?.error ?? {}).slice(0, 120)}`);
    await new Promise((res) => setTimeout(res, 150));
  }
  console.log(`done: ${ok}/${plan.length} calls accepted by the gateway`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
