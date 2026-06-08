import "server-only";

// Server-side bridge from edify-web → edify-api (NestJS).
//
// The two apps have separate auth: edify-web has a demo cookie session, the
// backend has JWT. This client maps the signed-in edify-web user to a backend
// demo account (by role), logs in once (token cached), and proxies scoped
// requests with the Bearer token. Server-only — tokens never reach the browser.
//
// Enable per-surface via EDIFY_USE_BACKEND=true; the API base is EDIFY_API_URL.

const API = process.env.EDIFY_API_URL ?? "http://localhost:4000/api";
const DEV_PASSWORD = "edify";

export function isBackendEnabled(): boolean {
  return (process.env.EDIFY_USE_BACKEND ?? "").toLowerCase() === "true";
}

// edify-web role → backend demo account with the matching scope. The backend
// resolves the real role/scope from its own user record, so role-string
// differences (RVP vs RegionalVicePresident) don't matter here.
const ROLE_TO_BACKEND_EMAIL: Record<string, string> = {
  CCEO: "cceo@edify.org",
  CountryProgramLead: "pl1@edify.org",
  CountryDirector: "cd@edify.org",
  RVP: "rvp@edify.org",
  RegionalVicePresident: "rvp@edify.org",
  ImpactAssessment: "ia@edify.org",
  ProgramAccountant: "accountant@edify.org",
  HumanResource: "hr@edify.org",
  HumanResources: "hr@edify.org",
  ProjectCoordinator: "cd@edify.org",
  Admin: "admin@edify.org",
  // No partner backend user yet — fall back to a scoped CCEO for testing.
  PartnerAdmin: "cceo@edify.org",
  PartnerFieldOfficer: "cceo@edify.org",
};

export type BackendUser = { email?: string; role: string };
function backendEmailFor(user: BackendUser): string {
  return ROLE_TO_BACKEND_EMAIL[user.role] ?? "cd@edify.org";
}

type CacheEntry = { token: string; exp: number };
const tokenCache = new Map<string, CacheEntry>();

async function loginToBackend(email: string): Promise<string | null> {
  const cached = tokenCache.get(email);
  if (cached && cached.exp > Date.now()) return cached.token;
  try {
    const res = await fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password: DEV_PASSWORD }),
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { accessToken?: string };
    if (!data.accessToken) return null;
    tokenCache.set(email, { token: data.accessToken, exp: Date.now() + 10 * 60 * 1000 });
    return data.accessToken;
  } catch {
    return null;
  }
}

export type BackendResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string };

/** The backend API base — used by the SSE proxy route to stream realtime events. */
export function backendApiBase(): string {
  return API;
}

/** Resolve the backend bearer token for a user (for the SSE proxy, which can't
 *  use backendFetch because it streams an open connection). */
export async function backendTokenFor(user: BackendUser): Promise<string | null> {
  return loginToBackend(backendEmailFor(user));
}

/** Fetch a scoped backend endpoint as the current edify-web user. */
export async function backendFetch<T>(path: string, user: BackendUser, init?: RequestInit): Promise<BackendResult<T>> {
  const token = await loginToBackend(backendEmailFor(user));
  if (!token) return { ok: false, error: "Backend auth unavailable" };
  try {
    const res = await fetch(`${API}${path}`, {
      ...init,
      headers: { ...(init?.headers ?? {}), Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      cache: "no-store",
    });
    if (!res.ok) return { ok: false, error: `Backend ${res.status}` };
    return { ok: true, data: (await res.json()) as T };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "Network error" };
  }
}
