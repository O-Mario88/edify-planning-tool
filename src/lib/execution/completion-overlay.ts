// Confirmed-completion overlay — server-side record of visit/training
// completions confirmed via the Salesforce Completion Gate on /visits and
// /trainings. Previously these lived only in a client localStorage store, so
// the completion was invisible to the server (no audit, no IA notification).
// This overlay gives each confirmation a real record keyed by the EXACT
// entered Salesforce ID. Shaped for a future Prisma `ActivityCompletion` table.

import "server-only";

export type ConfirmedCompletion = {
  activityId: string;
  activityType: string;
  schoolName: string;
  salesforceId: string;
  salesforceIdKind?: string;
  teachers?: number;
  leaders?: number;
  confirmedById: string;
  confirmedByName: string;
  confirmedAt: string;
};

type Store = { records: ConfirmedCompletion[] };
const STORE_KEY = "__edify_completion_overlay__";
type GlobalWithStore = typeof globalThis & { [STORE_KEY]?: Store };

function getStore(): Store {
  const g = globalThis as GlobalWithStore;
  if (!g[STORE_KEY]) g[STORE_KEY] = { records: [] };
  return g[STORE_KEY]!;
}

export function confirmedCompletions(): ConfirmedCompletion[] {
  return getStore().records;
}

export function completionFor(activityId: string): ConfirmedCompletion | undefined {
  return getStore().records.find((r) => r.activityId === activityId);
}

export function recordCompletion(rec: Omit<ConfirmedCompletion, "confirmedAt">): ConfirmedCompletion {
  const full: ConfirmedCompletion = { ...rec, confirmedAt: new Date().toISOString() };
  // De-dupe by activityId — re-confirming overwrites.
  const store = getStore();
  const idx = store.records.findIndex((r) => r.activityId === rec.activityId);
  if (idx === -1) store.records.unshift(full);
  else store.records[idx] = full;
  return full;
}

export function __resetCompletionOverlay() {
  const g = globalThis as GlobalWithStore;
  g[STORE_KEY] = { records: [] };
}
