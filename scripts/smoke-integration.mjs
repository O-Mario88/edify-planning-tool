#!/usr/bin/env node
/**
 * Frontend ↔ backend integration smoke test.
 * Requires edify-api on :4000 and edify-web on :3000.
 *
 *   node scripts/smoke-integration.mjs
 */
const API = process.env.EDIFY_API_URL ?? "http://localhost:4000/api";
const WEB = process.env.WEB_URL ?? "http://localhost:3000";
const PASSWORD = process.env.DEMO_LOGIN_PASSWORD ?? "edify";

const roles = [
  { email: "cd@edify.org", role: "CountryDirector", label: "CD" },
  { email: "pl1@edify.org", role: "CountryProgramLead", label: "PL" },
  { email: "cceo@edify.org", role: "CCEO", label: "CCEO" },
  { email: "partner@edify.org", role: "PartnerAdmin", label: "Partner" },
  { email: "ia@edify.org", role: "ImpactAssessment", label: "IA" },
  { email: "accountant@edify.org", role: "ProgramAccountant", label: "Accountant" },
];

const backendEndpoints = [
  { path: "/health", auth: false },
  { path: "/schools?pageSize=5", auth: true, role: "pl1@edify.org" },
  { path: "/my-plan?period=month", auth: true, role: "pl1@edify.org" },
  { path: "/budget/weekly", auth: true, role: "cd@edify.org" },
  { path: "/budget/from-schedule", auth: true, role: "cd@edify.org" },
  { path: "/budget/cost-settings", auth: true, role: "cd@edify.org" },
  { path: "/pl/review-queue", auth: true, role: "pl1@edify.org" },
  { path: "/fund-requests", auth: true, role: "cd@edify.org" },
  { path: "/analytics/dashboard", auth: true, role: "cd@edify.org" },
  { path: "/clusters/planning", auth: true, role: "pl1@edify.org" },
  { path: "/filters/options", auth: true, role: "pl1@edify.org" },
  { path: "/search?q=school", auth: true, role: "pl1@edify.org" },
  { path: "/partners/me/activities", auth: true, role: "partner@edify.org" },
  { path: "/messages/recent", auth: true, role: "pl1@edify.org" },
  { path: "/notifications", auth: true, role: "pl1@edify.org" },
];

const webApiByRole = {
  "pl1@edify.org": [
    "/api/health",
    "/api/health/db",
    "/api/my-plan",
    "/api/core-schools",
    "/api/budget/weekly",
    "/api/pl/review-queue",
    "/api/fund-requests",
    "/api/clusters/planning",
    "/api/search?q=school",
    "/api/messages",
    "/api/notifications",
    "/api/activities",
  ],
  "cceo@edify.org": ["/api/cceo/dashboard", "/api/cceo/planning-gaps", "/api/cceo/evidence-queue"],
  "cd@edify.org": ["/api/budget/weekly", "/api/budget/from-schedule", "/api/fund-requests"],
};

const webPagesByRole = {
  "pl1@edify.org": ["/planning", "/my-plan", "/core-schools", "/pl/review", "/weekly-funds", "/approvals"],
  "cceo@edify.org": ["/dashboard", "/planning"],
  "cd@edify.org": ["/dashboard", "/weekly-funds", "/approvals", "/monthly-fund-request"],
};

// Production-like SSR smoke: every major role cockpit + the data-heavy planning
// surfaces must render WITHOUT a server error (HTTP < 500). A 200 or an auth/role
// redirect (3xx) both mean "rendered without throwing"; a 500 is the exact crash
// class this contract work eliminates (undefined array reaching .map() in SSR).
const dashboardSsrByRole = {
  "cd@edify.org": ["/dashboards/director", "/planning", "/clusters", "/plans", "/special-projects", "/budget/intelligence"],
  "cceo@edify.org": ["/dashboards/cceo", "/planning", "/clusters"],
  "pl1@edify.org": ["/dashboards/cpl", "/planning", "/plans"],
  "ia@edify.org": ["/dashboards/impact"],
  "accountant@edify.org": ["/dashboards/accountant", "/budget/intelligence"],
  "partner@edify.org": ["/dashboards/partner"],
};

const results = { pass: 0, fail: 0, warn: 0, timings: [] };

function record(ok, label, detail, ms) {
  const icon = ok ? "✓" : "✗";
  const timing = ms != null ? ` (${ms}ms)` : "";
  console.log(`  ${icon}  ${label}${timing}  →  ${detail}`);
  if (ok) results.pass++;
  else results.fail++;
  if (ms != null) results.timings.push({ label, ms });
}

function warn(label, detail) {
  console.log(`  ⚠  ${label}  →  ${detail}`);
  results.warn++;
}

async function backendLogin(email) {
  const t0 = performance.now();
  const res = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password: PASSWORD }),
  });
  const ms = Math.round(performance.now() - t0);
  if (!res.ok) return { token: null, ms, status: res.status };
  const data = await res.json();
  return { token: data.accessToken ?? null, ms, status: res.status };
}

async function backendGet(path, token) {
  const t0 = performance.now();
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const res = await fetch(`${API}${path}`, { headers, cache: "no-store" });
  const ms = Math.round(performance.now() - t0);
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  return { status: res.status, ms, body };
}

function parseCookies(setCookie) {
  const jar = new Map();
  const parts = Array.isArray(setCookie) ? setCookie : setCookie ? [setCookie] : [];
  for (const line of parts) {
    const [pair] = line.split(";");
    const eq = pair.indexOf("=");
    if (eq > 0) jar.set(pair.slice(0, eq), pair.slice(eq + 1));
  }
  return jar;
}

// One web session per email per run — repeated logins trip the login rate
// limiter and make the suite un-rerunnable. Cache + reuse instead.
const _sessionCache = new Map();
async function getWebSession(email) {
  if (_sessionCache.has(email)) return _sessionCache.get(email);
  const session = await webLogin(email);
  _sessionCache.set(email, session);
  return session;
}

async function webLogin(email) {
  const init = await fetch(`${WEB}/login`, { redirect: "manual" });
  const csrf = init.headers.getSetCookie?.() ?? [];
  const jar = parseCookies(csrf);
  const token = jar.get("edify-csrf");
  if (!token) return { cookies: "", ok: false, error: "no csrf" };

  const res = await fetch(`${WEB}/api/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-csrf-token": token,
      Cookie: `edify-csrf=${token}`,
    },
    body: JSON.stringify({ email, password: PASSWORD }),
  });
  const loginCookies = res.headers.getSetCookie?.() ?? [];
  const all = parseCookies([...csrf, ...loginCookies]);
  const cookieStr = [...all.entries()].map(([k, v]) => `${k}=${v}`).join("; ");
  const data = await res.json().catch(() => ({}));
  return { cookies: cookieStr, ok: res.ok && data.ok, role: data.role, error: data.message };
}

async function webGet(path, cookies) {
  const t0 = performance.now();
  const res = await fetch(`${WEB}${path}`, {
    headers: cookies ? { Cookie: cookies } : {},
    redirect: "manual",
    cache: "no-store",
  });
  const ms = Math.round(performance.now() - t0);
  return { status: res.status, ms };
}

async function testBackendHealth() {
  console.log("\n── Backend direct (edify-api) ──");
  const { status, ms } = await backendGet("/health");
  record(status === 200, "GET /health", status, ms);
}

async function testBackendAuth() {
  console.log("\n── Backend auth (all pilot roles) ──");
  const tokens = new Map();
  for (const r of roles) {
    const { token, ms, status } = await backendLogin(r.email);
    record(!!token, `login ${r.label}`, token ? "token ok" : `failed ${status}`, ms);
    if (token) tokens.set(r.email, token);
  }
  return tokens;
}

async function testBackendEndpoints(tokens) {
  console.log("\n── Backend endpoints ──");
  for (const ep of backendEndpoints) {
    const token = ep.auth ? tokens.get(ep.role ?? "cd@edify.org") : null;
    const { status, ms, body } = await backendGet(ep.path, token);
    const ok = status === 200 && body != null;
    const hint = ok
      ? Array.isArray(body)
        ? `array[${body.length}]`
        : body.data
          ? `paginated ${body.total ?? body.data?.length ?? "?"}`
          : typeof body === "object"
            ? `keys:${Object.keys(body).slice(0, 4).join(",")}`
            : "ok"
      : `HTTP ${status}`;
    record(ok, `GET ${ep.path}`, hint, ms);
  }
}

async function testWebBridge(email, cookies, label) {
  console.log(`\n── Web API bridge (${label}) ──`);
  for (const path of webApiByRole[email] ?? []) {
    const { status, ms } = await webGet(path, cookies);
    record(status === 200, `GET ${path}`, status, ms);
  }
}

async function testWebPages(email, cookies, label) {
  console.log(`\n── Web pages SSR (${label}) ──`);
  for (const path of webPagesByRole[email] ?? []) {
    const { status, ms } = await webGet(path, cookies);
    record(status === 200, `GET ${path}`, status, ms);
  }
}

async function testDashboardSSR() {
  console.log("\n── Dashboard SSR smoke (renders without 500) ──");
  for (const [email, paths] of Object.entries(dashboardSsrByRole)) {
    const session = await getWebSession(email);
    if (!session.ok) {
      record(false, `web login ${email}`, session.error ?? "login failed");
      continue;
    }
    for (const path of paths) {
      const { status, ms } = await webGet(path, session.cookies);
      // < 500 == rendered without throwing (200 or an auth/role redirect).
      record(status < 500, `SSR ${email.split("@")[0]} ${path}`, `HTTP ${status}`, ms);
    }
  }
}

async function testStability(tokens) {
  console.log("\n── Stability (20 concurrent my-plan reads) ──");
  const token = tokens.get("pl1@edify.org");
  const n = 20;
  const t0 = performance.now();
  const batch = await Promise.all(
    Array.from({ length: n }, () => backendGet("/my-plan?period=month", token)),
  );
  const totalMs = Math.round(performance.now() - t0);
  const ok = batch.every((r) => r.status === 200);
  const avg = Math.round(batch.reduce((s, r) => s + r.ms, 0) / n);
  const max = Math.max(...batch.map((r) => r.ms));
  record(ok, `${n}× GET /my-plan`, `avg ${avg}ms max ${max}ms wall ${totalMs}ms`);
}

async function testBackendStillUp() {
  const { status, ms } = await backendGet("/health");
  record(status === 200, "backend still up after load", status, ms);
}

async function testDataShape(tokens) {
  console.log("\n── Data contract checks ──");
  const token = tokens.get("pl1@edify.org");
  const plan = await backendGet("/my-plan?period=month", token);
  const hasGroups = plan.body?.groups != null || plan.body?.scheduled != null || Array.isArray(plan.body);
  record(plan.status === 200 && hasGroups, "my-plan shape", hasGroups ? "has activity groups" : "unexpected shape");

  const costs = await backendGet("/budget/cost-settings", tokens.get("cd@edify.org"));
  const count = costs.body?.count ?? costs.body?.settings?.length ?? (Array.isArray(costs.body) ? costs.body.length : 0);
  record(costs.status === 200 && count >= 1, "cost catalogue", `${count} rates`);

  const weekly = await backendGet("/budget/weekly", tokens.get("cd@edify.org"));
  const hasBudget = weekly.body && (weekly.body.totalCents != null || weekly.body.lines != null || weekly.body.weeks != null);
  record(weekly.status === 200 && hasBudget, "weekly budget rollup", hasBudget ? "has totals" : "empty shape");
}

async function main() {
  console.log("\n  Edify integration smoke test");
  console.log(`  API: ${API}`);
  console.log(`  WEB: ${WEB}`);

  try {
    await fetch(`${API}/health`, { signal: AbortSignal.timeout(3000) });
  } catch {
    console.error("\n  ✗  edify-api not reachable on " + API);
    console.error("     Start: cd edify-api && npm run start:dev\n");
    process.exit(1);
  }
  try {
    await fetch(`${WEB}/api/health`, { signal: AbortSignal.timeout(3000) });
  } catch {
    console.error("\n  ✗  edify-web not reachable on " + WEB);
    console.error("     Start: npm run dev\n");
    process.exit(1);
  }

  await testBackendHealth();
  const tokens = await testBackendAuth();
  await testBackendEndpoints(tokens);
  await testDataShape(tokens);
  await testDashboardSSR();
  await testStability(tokens);
  await testBackendStillUp();

  console.log("\n── Web sessions (role-scoped) ──");
  for (const [email, label] of [
    ["pl1@edify.org", "PL"],
    ["cceo@edify.org", "CCEO"],
    ["cd@edify.org", "CD"],
  ]) {
    const session = await getWebSession(email);
    record(session.ok, `web login ${email}`, session.ok ? session.role : session.error);
    if (session.ok) {
      await testWebBridge(email, session.cookies, label);
      await testWebPages(email, session.cookies, label);
    }
  }

  const timings = results.timings.filter((t) => t.ms > 2000);
  if (timings.length) {
    console.log("\n── Slow endpoints (>2s) ──");
    for (const t of timings.sort((a, b) => b.ms - a.ms).slice(0, 10)) {
      warn(t.label, `${t.ms}ms`);
    }
  }

  console.log("\n  ─────────────────────────────");
  console.log(`  ${results.pass} passed, ${results.fail} failed, ${results.warn} slow warnings\n`);
  process.exit(results.fail > 0 ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
