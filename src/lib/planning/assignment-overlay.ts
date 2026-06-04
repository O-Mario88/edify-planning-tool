// Gap-board assignment overlay — a durable record of every activity assigned
// from the planning gap boards (assign to myself / staff / partner /
// facilitator). The gap boards + My Plan render from a separate client mock
// (core-school-plan-mock), so full gap re-derivation is a later data-layer
// unification; this overlay gives the assignment a real, auditable server-side
// record + drives the cross-role notification. Shaped for a future Prisma
// `PlanActivityAssignment` table.

import "server-only";

export type GapAssignmentOwner = "myself" | "staff" | "partner" | "partner_facilitator";

export type GapAssignmentRecord = {
  id: string;
  title: string;
  schoolOrCluster: string;
  owner: GapAssignmentOwner;
  ownerName?: string;
  monthLabel?: string;
  week?: number;
  notes?: string;
  assignedById: string;
  assignedByName: string;
  assignedAt: string;
};

type Store = { records: GapAssignmentRecord[] };
const STORE_KEY = "__edify_gap_assignment_store__";
type GlobalWithStore = typeof globalThis & { [STORE_KEY]?: Store };

function getStore(): Store {
  const g = globalThis as GlobalWithStore;
  if (!g[STORE_KEY]) g[STORE_KEY] = { records: [] };
  return g[STORE_KEY]!;
}

export function gapAssignments(): GapAssignmentRecord[] {
  return getStore().records;
}

export function recordGapAssignment(rec: Omit<GapAssignmentRecord, "id" | "assignedAt">): GapAssignmentRecord {
  const full: GapAssignmentRecord = {
    ...rec,
    id: `gasn_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`,
    assignedAt: new Date().toISOString(),
  };
  getStore().records.unshift(full);
  return full;
}

export function __resetGapAssignmentStore() {
  const g = globalThis as GlobalWithStore;
  g[STORE_KEY] = { records: [] };
}
