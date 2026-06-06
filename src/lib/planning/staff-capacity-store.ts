// Mutable per-staff direct-support limits — the CD/IA-set capacity (spec §3/§12).
// globalThis-backed so a server action's write is visible to the next render
// (same pattern as the entity store). Production: a StaffSupportCapacity table.

export const STAFF_SUPPORT_LIMIT_DEFAULT = 50;

const KEY = "__edify_staff_limits__";
type Backing = { limits: Record<string, number>; history: LimitChange[] };
type G = typeof globalThis & { [KEY]?: Backing };

export type LimitChange = {
  staffId: string;
  max: number;
  setByName: string;
  setByRole: string;
  at: string;
  notes?: string;
};

function backing(): Backing {
  const g = globalThis as G;
  if (!g[KEY]) {
    // Seed: a low limit for the demo CCEO so the at-limit gate is exercised.
    g[KEY] = { limits: { "STF-PC-001": 3 }, history: [] };
  }
  return g[KEY]!;
}

export function getStaffLimit(staffId: string): number {
  return backing().limits[staffId] ?? STAFF_SUPPORT_LIMIT_DEFAULT;
}

export function isLimitExplicit(staffId: string): boolean {
  return staffId in backing().limits;
}

export function setStaffLimit(staffId: string, max: number, setByName: string, setByRole: string, notes?: string): void {
  const b = backing();
  b.limits[staffId] = Math.max(0, Math.floor(max));
  b.history.unshift({ staffId, max: b.limits[staffId], setByName, setByRole, at: new Date().toISOString(), notes });
}

export function limitHistory(staffId?: string): LimitChange[] {
  const h = backing().history;
  return staffId ? h.filter((x) => x.staffId === staffId) : h;
}
