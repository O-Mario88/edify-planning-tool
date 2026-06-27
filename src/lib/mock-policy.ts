// Mock-data policy — LOCKED OFF. The database is the only runtime source of truth.
//
// Mock/demo data has been purged from the app. Every page fetches from the
// backend/database APIs and renders a real empty state when there are no records
// (e.g. "No schools uploaded yet."). These functions are retained for backwards
// compatibility with call sites but are now hard-locked to false so no mock
// array can ever render in any environment — development included. Local
// testing data is uploaded into the local DATABASE, never fabricated in code.

/** True when dev database seed may load demo fixtures — now always false. */
export function isDevSeedAllowed(): boolean {
  // Demo data is uploaded into the local database via the backend import
  // commands (import_schools_local / import_ssa_local), never fabricated here.
  return false;
}

/** True only when mock fallback may render — now always false. The runtime
 *  dependency on mock arrays is removed completely. */
export function isMockAllowed(): boolean {
  return false;
}

/** Whether the app is wired to the real backend (server-side flag). */
export function isBackendOn(): boolean {
  return (process.env.EDIFY_USE_BACKEND ?? "").toLowerCase() === "true";
}

/** Production safety: backend on (mocks are structurally impossible now). */
export function isProductionSafe(): boolean {
  return isBackendOn();
}
