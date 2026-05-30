// Gap engine — pure functions over PlanningGap arrays. The Planning page
// reads PlanningGap[] from the mock (or, later, the DB) and uses these
// helpers to bucket / filter / summarize without re-traversing the list
// itself.

import type {
  PlanningGap,
  GapKind,
  PlanningRecommendation,
  SsaGateState,
} from "./gap-types";
import { actionStateFor, GAP_GROUP, SCHEDULE_PRECISION } from "./gap-types";

// ────────── Tab bundle ──────────

/**
 * Bundle of gap groups for the Planning page tabs.
 *
 * Each tab is a pre-bucketed, pre-sorted PlanningGap[]. Totals on the
 * page header health strip are derived in the same pass so the caller
 * doesn't re-iterate the gap list to compute counters.
 */
export type PlanningGapTabs = {
  clientSchools:      PlanningGap[];   // tab 1
  clusters:           PlanningGap[];   // tab 2
  coreSchools:        PlanningGap[];   // tab 3
  partnerAssignments: PlanningGap[];   // tab 4
  // Totals for the page header health strip
  totals: {
    ssaLocked:         number;
    readyToPlan:       number;
    assignedToPartner: number;
    movedToMyPlan:     number;
  };
};

// Priority sort order — CRITICAL highest priority (lowest rank value).
const PRIORITY_RANK: Record<string, number> = {
  CRITICAL: 0,
  HIGH:     1,
  NORMAL:   2,
  LOW:      3,
};

const priorityRank = (g: PlanningGap): number => {
  const p = (g as { priority?: string }).priority;
  if (p && p in PRIORITY_RANK) return PRIORITY_RANK[p];
  return PRIORITY_RANK.NORMAL;
};

const kindRank = (g: PlanningGap): string => String(g.kind ?? "");

const sortGaps = (gaps: PlanningGap[]): PlanningGap[] =>
  [...gaps].sort((a, b) => {
    const pr = priorityRank(a) - priorityRank(b);
    if (pr !== 0) return pr;
    return kindRank(a).localeCompare(kindRank(b));
  });

/**
 * Bucket every PlanningGap into its GapGroup tab using GAP_GROUP. Within
 * each tab, sort by priority (CRITICAL → HIGH → NORMAL → LOW), then by
 * kind so similar gaps stack together. Compute totals in the same pass.
 */
export function groupGapsForTabs(all: PlanningGap[]): PlanningGapTabs {
  const clientSchools:      PlanningGap[] = [];
  const clusters:           PlanningGap[] = [];
  const coreSchools:        PlanningGap[] = [];
  const partnerAssignments: PlanningGap[] = [];

  let ssaLocked         = 0;
  let readyToPlan       = 0;
  let assignedToPartner = 0;
  let movedToMyPlan     = 0;

  for (const gap of all) {
    const group = GAP_GROUP[gap.kind];

    // GAP_GROUP returns the canonical GapGroup constants from gap-types
    // ("CLIENT_SCHOOLS" / "CLUSTERS" / "CORE_SCHOOLS" / "PARTNER_ASSIGNMENTS").
    // Earlier this switch checked camelCase strings and silently dropped
    // every gap into the default branch — every tab read "0".
    switch (group) {
      case "CLIENT_SCHOOLS":
        clientSchools.push(gap);
        break;
      case "CLUSTERS":
        clusters.push(gap);
        break;
      case "CORE_SCHOOLS":
        coreSchools.push(gap);
        break;
      case "PARTNER_ASSIGNMENTS":
        partnerAssignments.push(gap);
        break;
      default:
        break;
    }

    // Totals — derived in the same pass to avoid a second traversal.
    // Map the SsaGateState union ("SIT_NOT_DONE" / "SIT_DONE_SSA_MISSING" /
    // "SSA_COMPLETE_NOT_PLANNED" / "PLANNED" / "IN_PROGRESS" / "COMPLETED"
    // / "VERIFIED") onto the four health-strip buckets.
    const gate = gap.ssaGate;
    if (gate === "SIT_NOT_DONE" || gate === "SIT_DONE_SSA_MISSING") {
      ssaLocked += 1;
    }
    if (gate === "SSA_COMPLETE_NOT_PLANNED") {
      readyToPlan += 1;
    }
    if (gap.assignedPartnerId && gate !== "COMPLETED" && gate !== "VERIFIED") {
      assignedToPartner += 1;
    }
    if (gate === "PLANNED" || gate === "IN_PROGRESS") {
      movedToMyPlan += 1;
    }
  }

  return {
    clientSchools:      sortGaps(clientSchools),
    clusters:           sortGaps(clusters),
    coreSchools:        sortGaps(coreSchools),
    partnerAssignments: sortGaps(partnerAssignments),
    totals: {
      ssaLocked,
      readyToPlan,
      assignedToPartner,
      movedToMyPlan,
    },
  };
}

// ────────── Filters ──────────

export function filterGapsByGate(
  gaps: PlanningGap[],
  gate: SsaGateState,
): PlanningGap[] {
  return gaps.filter((g) => g.ssaGate === gate);
}

export function filterGapsByKind(
  gaps: PlanningGap[],
  kinds: GapKind[],
): PlanningGap[] {
  if (kinds.length === 0) return [];
  const set = new Set<GapKind>(kinds);
  return gaps.filter((g) => set.has(g.kind));
}

export function filterGapsBySchool(
  gaps: PlanningGap[],
  schoolId: string,
): PlanningGap[] {
  return gaps.filter((g) => {
    const gg = g as { schoolId?: string; school?: { id?: string } };
    return gg.schoolId === schoolId || gg.school?.id === schoolId;
  });
}

// ────────── Helpers ──────────

/**
 * Quick summary used by the page header + the dev console. byKind is a
 * count of gaps per kind; ssaLocked is the count of gaps still gated by
 * SSA; topPriority is the highest-priority gap after the canonical sort.
 */
export function gapsSummary(gaps: PlanningGap[]): {
  byKind: Record<string, number>;
  ssaLocked: number;
  topPriority: PlanningGap | null;
} {
  const byKind: Record<string, number> = {};
  let ssaLocked = 0;

  for (const g of gaps) {
    const k = String(g.kind);
    byKind[k] = (byKind[k] ?? 0) + 1;
    if (g.ssaGate === "LOCKED" || g.ssaGate === "SSA_LOCKED") {
      ssaLocked += 1;
    }
  }

  const sorted = sortGaps(gaps);
  const topPriority = sorted.length > 0 ? sorted[0] : null;

  return { byKind, ssaLocked, topPriority };
}

/**
 * Check whether a given action kind is available on a gap. Reads the
 * gap's ssaGate via actionStateFor and returns true iff the resulting
 * state === "AVAILABLE".
 */
export function isActionAvailable(
  gap: PlanningGap,
  actionKind: import("./gap-types").PlanningActionKind,
): boolean {
  const state = actionStateFor(gap.ssaGate, actionKind);
  return state === "AVAILABLE";
}

// Re-export the schedule-precision lookup for convenience so callers
// don't need a second import from gap-types just to format a date.
export { SCHEDULE_PRECISION };

// Touch unused import so PlanningRecommendation stays in the public
// surface of this module for downstream consumers that re-export from
// here. Stripped at compile-time — purely a type-level reference.
export type { PlanningRecommendation };
