// Planning categories — the CCEO "what should I plan next?" rollup (spec §9).
//
// Takes the data PlanningToolPage ALREADY computes (school gaps, cluster gaps,
// core cards, project gaps — passed in, never recomputed) and folds it into 8
// recommendation-led categories the CCEO expands one by one. Every row is
// UNSCHEDULED recommended work by construction: the gap sources only emit open
// gaps / Not-Planned slots, and this module preserves that — it groups, it
// never invents.
//
// Pure: no server-only imports, no I/O. Cost rates are optional and passed in
// (PlanningToolPage loads them via cost-engine-server); rows without reachable
// cost data carry no cost and the category sums only what it can prove.

import type { SchoolGap, ClusterGap, SsaInterventionArea } from "./planning-gaps-mock";
import { recommendFor, recommendForCluster } from "./planning-gaps-mock";
import { classifySeverity, deliveryFor, type DeliveryType } from "./intervention-recommendation";
import { INTAKE_TO_CANONICAL } from "./intervention-taxonomy";
import { SSA_INTERVENTIONS } from "./ssa-performance-mock";
import type { CorePlanCardVM } from "@/lib/core/core-board";
import type { ProjectGapCategory } from "@/lib/projects/project-planning-gaps";
import {
  computeVisitCost,
  computeTrainingCost,
  computeClusterMeetingCost,
  type VisitCostRates,
  type GroupActivityRates,
} from "@/lib/cost-engine/cost-engine";

// ────────── Types ──────────

export type PlanningCategoryKey =
  | "ssa_sit"
  | "school_visits"
  | "trainings"
  | "cluster_meetings"
  | "core_visits"
  | "core_trainings"
  | "partner_assignments"
  | "special_projects";

export type PlanningCategoryPriority = "high" | "medium" | "clear";

export type PlanningCategoryRow = {
  key: string;
  name: string;
  district: string;
  /** Two weakest SSA interventions, where the gap carries scored data. */
  weakest?: { area: SsaInterventionArea; score: number };
  secondWeak?: { area: SsaInterventionArea; score: number };
  /** The recommendation sentence (reused from the gap engines, not forked). */
  recommendation: string;
  /** Recommended delivery owner — guides, doesn't force. */
  delivery: DeliveryType;
  /** True when this row is the red-alert driver (Critical severity / blocked). */
  redAlert: boolean;
  /** Estimated UGX where CD rates make it computable; undefined otherwise. */
  costUgx?: number;
  /** Where the Schedule button lands — same destination the gap boards use. */
  scheduleHref: string;
};

export type PlanningCategory = {
  key: PlanningCategoryKey;
  label: string;
  count: number;
  redAlertCount: number;
  /** Sum of the row costs that are computable (0 when none are). */
  estimatedCost: number;
  priority: PlanningCategoryPriority;
  rows: PlanningCategoryRow[];
};

/** CD-configured rates, loaded server-side and passed in (optional). */
export type PlanningCostRates = {
  visit: VisitCostRates;
  group: GroupActivityRates;
};

// ────────── Helpers ──────────

/** Mock onboarded gaps prefix the business schoolId with "onb-"; backend gaps
 *  carry the real schoolId directly. Either way, the profile route wants the
 *  bare business id. */
function schoolIdOf(g: SchoolGap): string {
  return g.id.startsWith("onb-") ? g.id.slice(4) : g.id;
}

function schoolHref(g: SchoolGap): string {
  return `/schools/${encodeURIComponent(schoolIdOf(g))}?view=plan`;
}

/** Core-plan interventions are keyed on the INTAKE label set; the delivery
 *  policy + this module's rows speak the canonical 8. One mapping, reused
 *  from the taxonomy seam — never forked. */
function canonicalArea(label: string): SsaInterventionArea | undefined {
  if ((SSA_INTERVENTIONS as readonly string[]).includes(label)) return label as SsaInterventionArea;
  return INTAKE_TO_CANONICAL[label];
}

function schoolRedAlert(g: SchoolGap): boolean {
  return (
    g.riskLevel === "Critical" ||
    (!!g.weakestArea && classifySeverity(g.weakestArea.score) === "Critical")
  );
}

/** One-school, one-day staff/partner visit estimate (primary-district floor —
 *  the planner refines days/district at scheduling time). */
function visitCostUgx(rates: PlanningCostRates | undefined, delivery: DeliveryType): number | undefined {
  if (!rates) return undefined;
  const breakdown = computeVisitCost({
    mode: delivery,
    schools: [{ schoolId: "estimate", schoolName: "estimate", districtType: "primary" }],
    rates: rates.visit,
  });
  return breakdown.totalUgx > 0 ? breakdown.totalUgx : undefined;
}

/** Training floor estimate: session + venue fees only — per-head lines need a
 *  participant count that doesn't exist until the activity is scheduled. */
function trainingCostUgx(rates: PlanningCostRates | undefined): number | undefined {
  if (!rates) return undefined;
  const breakdown = computeTrainingCost({ participants: 0, rates: rates.group });
  return breakdown.totalUgx > 0 ? breakdown.totalUgx : undefined;
}

/** Cluster meeting floor: one representative per member school. */
function clusterMeetingCostUgx(rates: PlanningCostRates | undefined, c: ClusterGap): number | undefined {
  if (!rates) return undefined;
  const breakdown = computeClusterMeetingCost({ participants: c.schoolsCount, rates: rates.group });
  return breakdown.totalUgx > 0 ? breakdown.totalUgx : undefined;
}

function makeCategory(
  key: PlanningCategoryKey,
  label: string,
  rows: PlanningCategoryRow[],
): PlanningCategory {
  const redAlertCount = rows.filter((r) => r.redAlert).length;
  return {
    key,
    label,
    count: rows.length,
    redAlertCount,
    estimatedCost: rows.reduce((sum, r) => sum + (r.costUgx ?? 0), 0),
    priority: redAlertCount > 0 ? "high" : rows.length > 0 ? "medium" : "clear",
    rows,
  };
}

/** Compact UGX label, shared by the summary cards. */
export function formatUgx(amount: number): string {
  if (amount >= 1_000_000) return `UGX ${(amount / 1_000_000).toFixed(1)}M`;
  if (amount >= 1_000) return `UGX ${Math.round(amount / 1_000)}K`;
  return `UGX ${amount}`;
}

// ────────── Engine ──────────

export function buildPlanningCategories(args: {
  /** The viewer-scoped, filter-scoped open school gaps (onboarded/backend). */
  schoolGaps: SchoolGap[];
  /** The viewer-scoped open cluster gaps. */
  clusterGaps: ClusterGap[];
  /** The viewer-scoped CorePlan cards (slots carry their own status). */
  coreCards: CorePlanCardVM[];
  /** The viewer-scoped project gap categories. */
  projectGaps: ProjectGapCategory[];
  /** CD cost rates — omit and every row simply carries no cost. */
  rates?: PlanningCostRates;
}): PlanningCategory[] {
  const { schoolGaps, clusterGaps, coreCards, projectGaps, rates } = args;

  // 1 · Schools Needing SSA/SIT — clustered, no current-FY SSA. The SSA is
  // delivered via SIT / partner / self; the recommendation engine words it.
  const ssaRows: PlanningCategoryRow[] = schoolGaps
    .filter((g) => g.gapCategory === "no_ssa")
    .map((g) => ({
      key: g.id,
      name: g.schoolName,
      district: g.district,
      recommendation: recommendFor(g).headline,
      delivery: "staff" as const,
      redAlert: schoolRedAlert(g),
      costUgx: visitCostUgx(rates, "staff"),
      scheduleHref: schoolHref(g),
    }));

  // 2 · School Visits — SSA done, support visit outstanding.
  const visitRows: PlanningCategoryRow[] = schoolGaps
    .filter((g) => g.gapCategory === "no_visit")
    .map((g) => {
      const delivery = g.weakestArea ? deliveryFor(g.weakestArea.area) : "staff";
      return {
        key: g.id,
        name: g.schoolName,
        district: g.district,
        weakest: g.weakestArea,
        secondWeak: g.secondWeakArea,
        recommendation: recommendFor(g).headline,
        delivery,
        redAlert: schoolRedAlert(g),
        costUgx: visitCostUgx(rates, delivery),
        scheduleHref: schoolHref(g),
      };
    });

  // 3 · Trainings — SSA done, School Improvement Training outstanding.
  const trainingRows: PlanningCategoryRow[] = schoolGaps
    .filter((g) => g.gapCategory === "no_training")
    .map((g) => ({
      key: g.id,
      name: g.schoolName,
      district: g.district,
      weakest: g.weakestArea,
      secondWeak: g.secondWeakArea,
      recommendation: recommendFor(g).headline,
      delivery: g.weakestArea ? deliveryFor(g.weakestArea.area) : "staff",
      redAlert: schoolRedAlert(g),
      costUgx: trainingCostUgx(rates),
      scheduleHref: schoolHref(g),
    }));

  // 4 · Cluster Meetings / Parish Fellowships — only clusters with a genuinely
  // MISSING slot (the engine emits every active cluster; on-track ones aren't
  // unscheduled work, so they don't belong in a planning category).
  const openClusters = clusterGaps.filter(
    (c) =>
      c.firstMeeting === "Missing" ||
      c.secondMeeting === "Missing" ||
      c.thirdMeeting === "Missing" ||
      c.schoolImprovementTraining === "Missing",
  );
  const clusterRows: PlanningCategoryRow[] = openClusters.map((c) => {
    const rec = recommendForCluster(c);
    return {
      key: c.id,
      name: c.clusterName,
      district: c.district,
      recommendation: rec.headline,
      delivery: (c.partnerFacilitator ? "partner" : "staff") as DeliveryType,
      // SIT blocked outright (no school has an SSA) is the cluster red alert.
      redAlert: c.schoolsWithSsa === 0,
      costUgx: clusterMeetingCostUgx(rates, c),
      scheduleHref: `/clusters/${encodeURIComponent(c.id)}`,
    };
  });

  // 5 + 6 · Core School Visits / Trainings — unplanned slots on active core
  // plans (status "Not Planned" = unscheduled recommended work).
  const coreRow = (card: CorePlanCardVM, slot: CorePlanCardVM["slots"][number]): PlanningCategoryRow => {
    const baseline = card.interventions.find((i) => i.intervention === slot.intervention);
    const ranked = [...card.interventions].sort((a, b) => a.baselineScore - b.baselineScore);
    const slotArea = canonicalArea(slot.intervention);
    const rankedArea = (i?: (typeof ranked)[number]) => {
      const area = i ? canonicalArea(i.intervention) : undefined;
      return area && i ? { area, score: i.baselineScore } : undefined;
    };
    const delivery = slotArea ? deliveryFor(slotArea) : "staff";
    const noun = slot.activityType === "visit" ? "Visit" : "Training";
    return {
      key: slot.id,
      name: `${card.schoolName} · ${noun} ${slot.sequenceNumber}`,
      district: card.district,
      weakest: rankedArea(ranked[0]),
      secondWeak: rankedArea(ranked[1]),
      recommendation: `Schedule core ${noun.toLowerCase()} ${slot.sequenceNumber} of 4 — ${slot.intervention}${
        baseline ? ` (baseline ${baseline.baselineScore}/10)` : ""
      }.`,
      delivery,
      redAlert: baseline ? classifySeverity(baseline.baselineScore) === "Critical" : false,
      costUgx:
        slot.activityType === "visit" ? visitCostUgx(rates, delivery) : trainingCostUgx(rates),
      scheduleHref: `/core-schools/${encodeURIComponent(card.plan.schoolId)}`,
    };
  };
  const openSlots = coreCards.flatMap((card) =>
    card.slots.filter((s) => s.status === "Not Planned").map((s) => ({ card, slot: s })),
  );
  const coreVisitRows = openSlots
    .filter((x) => x.slot.activityType === "visit")
    .map((x) => coreRow(x.card, x.slot));
  const coreTrainingRows = openSlots
    .filter((x) => x.slot.activityType === "training")
    .map((x) => coreRow(x.card, x.slot));

  // 7 · Partner Assignments — scored schools whose weakest intervention ROUTES
  // to partner expertise and that have no partner attached yet. (A different
  // lens on the same open gaps: "send these to a partner", not new work.)
  const partnerRows: PlanningCategoryRow[] = schoolGaps
    .filter(
      (g) =>
        g.ssaCompleted &&
        !!g.weakestArea &&
        deliveryFor(g.weakestArea.area) === "partner" &&
        !g.assignedPartner,
    )
    .map((g) => ({
      key: `partner-${g.id}`,
      name: g.schoolName,
      district: g.district,
      weakest: g.weakestArea,
      secondWeak: g.secondWeakArea,
      recommendation: `Assign ${g.weakestArea!.area} support to a partner — scored ${g.weakestArea!.score}/10 and this intervention routes to partner expertise.`,
      delivery: "partner" as const,
      redAlert: schoolRedAlert(g),
      costUgx: visitCostUgx(rates, "partner"),
      scheduleHref: schoolHref(g),
    }));

  // 8 · Special Project Activities — the project follow-up queues, flattened.
  const projectRows: PlanningCategoryRow[] = projectGaps.flatMap((cat) =>
    cat.items.map((it) => ({
      key: `${cat.key}-${it.key}`,
      name: it.schoolName,
      district: it.district,
      recommendation: `${cat.label}: ${it.detail}`,
      delivery: (cat.key === "partnerAssignedNotScheduled" ? "partner" : "staff") as DeliveryType,
      redAlert: cat.key === "noImprovement",
      costUgx: undefined, // no cost data reachable for project activities yet
      scheduleHref: it.href,
    })),
  );

  return [
    makeCategory("ssa_sit", "Schools Needing SSA/SIT", ssaRows),
    makeCategory("school_visits", "School Visits", visitRows),
    makeCategory("trainings", "Trainings", trainingRows),
    makeCategory("cluster_meetings", "Cluster Meetings / Parish Fellowships", clusterRows),
    makeCategory("core_visits", "Core School Visits", coreVisitRows),
    makeCategory("core_trainings", "Core School Trainings", coreTrainingRows),
    makeCategory("partner_assignments", "Partner Assignments", partnerRows),
    makeCategory("special_projects", "Special Project Activities", projectRows),
  ];
}
