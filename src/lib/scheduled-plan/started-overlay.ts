// Started-activity overlay — records which scheduled plans the field
// worker has actually started, so "Start activity" transitions the card to
// In Progress durably (survives reload) instead of console.log-only. The
// schedule page applies this overlay onto its demo plans. Shaped for a future
// Prisma `ScheduledPlan.status` write.

import "server-only";

type StartedEntry = { at: string; byId: string; byName: string };
type Store = { started: Record<string, StartedEntry> };

const STORE_KEY = "__edify_started_plan_store__";
type GlobalWithStore = typeof globalThis & { [STORE_KEY]?: Store };

function getStore(): Store {
  const g = globalThis as GlobalWithStore;
  if (!g[STORE_KEY]) g[STORE_KEY] = { started: {} };
  return g[STORE_KEY]!;
}

export function isPlanStarted(id: string): boolean {
  return !!getStore().started[id];
}

export function markPlanStarted(id: string, by: { id: string; name: string }): void {
  getStore().started[id] = { at: new Date().toISOString(), byId: by.id, byName: by.name };
}

export function __resetStartedPlanStore() {
  const g = globalThis as GlobalWithStore;
  g[STORE_KEY] = { started: {} };
}
