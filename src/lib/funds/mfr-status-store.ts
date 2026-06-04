// Monthly Fund Request status overlay — persists the single shared workflow
// status of the country/month MFR artifact (PL → CD → RVP → Accountant), so
// the approval-chain buttons actually advance state instead of flipping local
// React state. globalThis-backed, shaped like a future Prisma
// `MonthlyFundRequest.status` column + an MfrStatusEvent history table.

import "server-only";
import type { MonthlyFundRequestStatus } from "./monthly-fund-request-types";

export type MfrStatusEvent = {
  status: MonthlyFundRequestStatus;
  at: string;
  byId: string;
  byName: string;
  note?: string;
};

type MfrStatusEntry = { status: MonthlyFundRequestStatus; history: MfrStatusEvent[] };
type MfrStatusStore = { byId: Record<string, MfrStatusEntry> };

const STORE_KEY = "__edify_mfr_status_store__";
type GlobalWithStore = typeof globalThis & { [STORE_KEY]?: MfrStatusStore };

function getStore(): MfrStatusStore {
  const g = globalThis as GlobalWithStore;
  if (!g[STORE_KEY]) g[STORE_KEY] = { byId: {} };
  return g[STORE_KEY]!;
}

/** Persisted status for the artifact, or undefined if it's never been acted on. */
export function mfrStatus(fundRequestId: string): MonthlyFundRequestStatus | undefined {
  return getStore().byId[fundRequestId]?.status;
}

export function mfrHistory(fundRequestId: string): MfrStatusEvent[] {
  return getStore().byId[fundRequestId]?.history ?? [];
}

export function setMfrStatus(
  fundRequestId: string,
  status: MonthlyFundRequestStatus,
  by: { id: string; name: string },
  note?: string,
): MfrStatusEntry {
  const store = getStore();
  const event: MfrStatusEvent = { status, at: new Date().toISOString(), byId: by.id, byName: by.name, note };
  const existing = store.byId[fundRequestId];
  if (existing) {
    existing.status = status;
    existing.history.unshift(event);
  } else {
    store.byId[fundRequestId] = { status, history: [event] };
  }
  return store.byId[fundRequestId];
}

export function __resetMfrStatusStore() {
  const g = globalThis as GlobalWithStore;
  g[STORE_KEY] = { byId: {} };
}
