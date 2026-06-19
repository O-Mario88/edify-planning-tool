import "server-only";
import type { AuthUser } from "../common/auth/auth-user";
import type { Container } from "../container";
import { UnauthorizedError } from "../common/errors";

// In-process router. Replaces the HTTP hop to edify-api for ported domains:
// surfaces.ts's live() calls tryInProcess(path, init) first; if a route for an
// enabled domain matches, we run the container service in-process and return the
// data; otherwise the caller falls through to backendFetch (proxy).
//
// Which domains run in-process is controlled by EDIFY_INPROC_DOMAINS — a
// comma-separated list (e.g. "geography,schools") or "*" for all ported. When
// empty (the default during the migration), tryInProcess is a no-op fast path,
// so proxy mode is completely unaffected and the container/Prisma are never even
// imported.

function inprocDomains(): Set<string> {
  return new Set(
    (process.env.EDIFY_INPROC_DOMAINS ?? "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  );
}

export type InProcResult<T> = { handled: true; data: T } | { handled: false };

type Ctx = { url: URL; user: AuthUser; body: unknown; container: Container };
type Route = {
  domain: string;
  method: string;
  // Tested against the URL pathname (no query string).
  match: RegExp;
  handle: (m: RegExpMatchArray, ctx: Ctx) => Promise<unknown> | unknown;
};

const q = (c: Ctx, key: string) => c.url.searchParams.get(key) ?? undefined;

// ── Route table (grows one wave at a time) ──────────────────────────────────
const ROUTES: Route[] = [
  // Wave 1 · geography — auth-only reference reads (mirror GeographyController).
  { domain: "geography", method: "GET", match: /^\/geography\/regions$/, handle: (_m, c) => c.container.geography.listRegions() },
  { domain: "geography", method: "GET", match: /^\/geography\/districts$/, handle: (_m, c) => c.container.geography.listDistricts(q(c, "regionId")) },
  { domain: "geography", method: "GET", match: /^\/geography\/sub-counties$/, handle: (_m, c) => c.container.geography.listSubCounties(q(c, "districtId") ?? "") },
  { domain: "geography", method: "GET", match: /^\/geography\/parishes$/, handle: (_m, c) => c.container.geography.listParishes(q(c, "subCountyId") ?? "") },
  { domain: "geography", method: "GET", match: /^\/geography\/villages$/, handle: (_m, c) => c.container.geography.listVillages(q(c, "parishId") ?? "") },
];

export async function tryInProcess<T>(path: string, init?: RequestInit): Promise<InProcResult<T>> {
  const enabled = inprocDomains();
  if (enabled.size === 0) return { handled: false }; // fast path — proxy mode

  const method = (init?.method ?? "GET").toUpperCase();
  const url = new URL(path, "http://inproc.local");

  for (const r of ROUTES) {
    if (r.method !== method) continue;
    if (!(enabled.has("*") || enabled.has(r.domain))) continue;
    const m = url.pathname.match(r.match);
    if (!m) continue;

    // Lazy imports so the container (and Prisma) load only when a route is
    // actually served in-process — never in pure proxy mode.
    const [{ container }, { resolveAuthUser }] = await Promise.all([
      import("../container"),
      import("../common/auth/resolve-user"),
    ]);

    // Every ported route requires an authenticated principal (mirrors JwtAuthGuard).
    const user = await resolveAuthUser();
    if (!user) throw new UnauthorizedError("Not authenticated");

    const body = init?.body ? JSON.parse(init.body as string) : undefined;
    const data = await r.handle(m, { url, user, body, container });
    return { handled: true, data: data as T };
  }

  return { handled: false };
}
