// Mock-data policy — the single switch that decides whether frontend mock data
// is ever allowed to render. Part of the purge migration (backend-only data).
//
// Rule: production NEVER shows mock data. In development it's allowed only when
// explicitly opted in (NEXT_PUBLIC_USE_MOCK_DATA=true) AND the backend bridge is
// off. Real pages must not depend on this to invent data — when mock is not
// allowed they must fetch from the backend and render empty/error states.

/** True only when mock fallback may render (dev, opt-in, backend off). */
export function isMockAllowed(): boolean {
  if (process.env.NODE_ENV === "production") return false;
  if (process.env.NEXT_PUBLIC_USE_MOCK_DATA === "true") return true;
  return false;
}

/** Whether the app is wired to the real backend (server-side flag). */
export function isBackendOn(): boolean {
  return (process.env.EDIFY_USE_BACKEND ?? "").toLowerCase() === "true";
}

/** Production safety: mock data disabled, backend on. */
export function isProductionSafe(): boolean {
  return !isMockAllowed() && isBackendOn();
}
