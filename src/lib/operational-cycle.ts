// Client-safe operational cycle helpers.
//
// The canonical FY engine (lib/fy-engine) is server-only because it
// pulls schoolsMock + the per-school FY summary table. Client cards
// (CoreSchoolCard, SchoolGapsBoard) just need to ask "is this date
// in the current cycle, the previous one, or older?" — that's pure
// date math. Lifting it here keeps client components from dragging
// the whole engine through the React tree.
//
// In production this is replaced with a server-passed prop or a
// React context populated at the layout level; the function shapes
// stay the same so call sites don't change.

export type OperationalCycle = {
  id:        string;
  label:     string;
  startIso:  string;  // "YYYY-10-01"
  endIso:    string;  // "YYYY-09-30"
};

/**
 * Canonical operational cycles. Mirrors the Active + Locked rows in
 * fy-engine.financialYears. Keep these in sync with the server-side
 * ledger — they're the load-bearing source for client-side cycle math.
 */
export const ACTIVE_OPERATIONAL_CYCLE: OperationalCycle = {
  id:       "fy-2025-26",
  label:    "FY 2025/26",
  startIso: "2025-10-01",
  endIso:   "2026-09-30",
};

export const PREVIOUS_OPERATIONAL_CYCLE: OperationalCycle = {
  id:       "fy-2024-25",
  label:    "FY 2024/25",
  startIso: "2024-10-01",
  endIso:   "2025-09-30",
};

// ────────── Status type + helpers ──────────

export type CycleStatus =
  | "current_cycle"   // ≥ active.startIso, ≤ active.endIso
  | "previous_cycle"  // in the immediately prior FY
  | "older"           // before previous FY
  | "future"          // after active.endIso
  | "no_entry";       // no date recorded

/**
 * Bucket a date into a cycle status. Pure — feed any cycle for tests.
 */
export function cycleStatusFor(
  iso: string | undefined,
  active:   OperationalCycle = ACTIVE_OPERATIONAL_CYCLE,
  previous: OperationalCycle = PREVIOUS_OPERATIONAL_CYCLE,
): CycleStatus {
  if (!iso) return "no_entry";
  if (iso >= active.startIso && iso <= active.endIso) return "current_cycle";
  if (iso >= previous.startIso && iso <= previous.endIso) return "previous_cycle";
  if (iso < previous.startIso) return "older";
  return "future";
}

/** Short user-facing label. Mirrors the spec's section 10 vocabulary. */
export function cycleLabelFor(status: CycleStatus): string {
  switch (status) {
    case "current_cycle":  return "Completed This Cycle";
    case "previous_cycle": return "Completed Last Cycle";
    case "older":          return "Historical Only";
    case "future":         return "Scheduled Future Cycle";
    case "no_entry":       return "Current Cycle Required";
  }
}

/** True only if the date is in the active cycle window. */
export function isInCurrentCycle(
  iso: string | undefined,
  active: OperationalCycle = ACTIVE_OPERATIONAL_CYCLE,
): boolean {
  if (!iso) return false;
  return iso >= active.startIso && iso <= active.endIso;
}

/**
 * Resolve "what should the planner see about this school's SSA?"
 * One call → the right badge tone + text, instead of every card
 * re-implementing the logic. Used by CoreSchoolCard and
 * SchoolGapsBoard so both surfaces stay consistent.
 */
export type CycleBadge = {
  status:       CycleStatus;
  label:        string;       // "Historical Only", "Completed This Cycle", etc.
  tone:         "good" | "warn" | "danger" | "info";
  /** Optional sub-line — "Last: Jul 20, 2026" when historical. */
  sub?:         string;
  /** When true, the planner should be reminded the school still needs current-cycle action. */
  needsCurrentCycleAction: boolean;
};

export function ssaCycleBadge(lastSsaIso: string | undefined): CycleBadge {
  const status = cycleStatusFor(lastSsaIso);
  switch (status) {
    case "current_cycle":
      return {
        status,
        label: "Completed This Cycle",
        tone:  "good",
        sub:   lastSsaIso ? `Completed ${prettyDate(lastSsaIso)}` : undefined,
        needsCurrentCycleAction: false,
      };
    case "previous_cycle":
      return {
        status,
        label: "Historical Only",
        tone:  "warn",
        sub:   `Last cycle · ${prettyDate(lastSsaIso!)}`,
        needsCurrentCycleAction: true,
      };
    case "older":
      return {
        status,
        label: "Historical Only",
        tone:  "warn",
        sub:   `Last: ${prettyDate(lastSsaIso!)}`,
        needsCurrentCycleAction: true,
      };
    case "future":
      return {
        status,
        label: "Scheduled Future Cycle",
        tone:  "info",
        sub:   lastSsaIso ? `Planned for ${prettyDate(lastSsaIso)}` : undefined,
        needsCurrentCycleAction: true,
      };
    case "no_entry":
      return {
        status,
        label: "Current Cycle SSA Missing",
        tone:  "danger",
        needsCurrentCycleAction: true,
      };
  }
}

// ────────── Date formatting ──────────

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function prettyDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}
