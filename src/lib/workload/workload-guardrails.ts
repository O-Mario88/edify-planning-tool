// Healthy Workload Guardrails.
//
// The product principle:
//   • Surveil less. Protect more.
//   • Flag staff carrying too much BEFORE the system penalises them
//     for what the load made impossible.
//   • Recommend an intervention, not a punishment.
//
// This engine is pure functions. Inputs come from data the app
// already has (FWI portfolio complexity, planning load, leave
// records, partner-managed counts, special-project assignments).
// Outputs are FlagItem[] + RecommendationItem[] — both consumed by
// HR and CPL action inboxes through the role-action-engine.

import type { PortfolioComplexityInputs } from "@/lib/performance/fwi-types";

// ────────── Flag kinds ──────────
//
// Each flag is a single, named overload condition. Multiple flags
// can fire for one staff member — the recommendation engine reads
// the full set to pick the most impactful intervention.

export type WorkloadFlagKind =
  | "TooManySchools"
  | "TooManyDistricts"
  | "TooManySecondaryDistricts"
  | "HighDailyTravelKm"
  | "TooManyPartnersManaged"
  | "TooManyPendingTasks"
  | "TooManySpecialProjects"
  | "RepeatedHotelTrips"
  | "HighTargetUnderHighLoad";

export type WorkloadFlag = {
  staffId: string;
  staffName: string;
  kind: WorkloadFlagKind;
  /// 0..100 severity. 100 = "drop everything else". 0 = "barely tripped".
  severity: number;
  /// One-sentence, supportive — phrased as observation, not accusation.
  message: string;
};

// ────────── Thresholds ──────────
//
// Defaults baked here; production reads from a per-country
// HealthyWorkloadThresholds row so a CD can tune. Numbers come
// from operating norms — past these, sustainability drops sharply.

export type WorkloadThresholds = {
  maxSchools: number;
  maxDistricts: number;
  maxSecondaryDistricts: number;
  maxDailyTravelKm: number;
  maxPartnersManaged: number;
  maxPendingTasks: number;
  maxSpecialProjects: number;
  /// Hotel trips per month above which it stops being healthy.
  maxHotelTripsPerMonth: number;
};

export const DEFAULT_WORKLOAD_THRESHOLDS: WorkloadThresholds = {
  maxSchools:              40,
  maxDistricts:             5,
  maxSecondaryDistricts:    3,
  maxDailyTravelKm:        80,
  maxPartnersManaged:       4,
  maxPendingTasks:         25,
  maxSpecialProjects:       2,
  maxHotelTripsPerMonth:    6,
};

// ────────── Detection inputs ──────────

export type WorkloadDetectionInput = {
  staffId: string;
  staffName: string;
  /// Portfolio shape — same one the FWI engine consumes.
  portfolio: PortfolioComplexityInputs;
  /// Open Inbox items for this staff member (drives TooManyPendingTasks).
  pendingTaskCount: number;
  /// Number of distinct special projects assigned right now.
  specialProjectsActive: number;
  /// Total daily travel km averaged over the last 4 weeks (drives
  /// HighDailyTravelKm).
  avgDailyTravelKm: number;
  /// Optional: this staff's current target vs the team median, as a
  /// ratio (1.2 = 20% over team median). Drives HighTargetUnderHighLoad
  /// when combined with a heavy portfolio.
  targetRatioVsMedian?: number;
};

// ────────── Detector ──────────

export function detectWorkloadFlags(
  input: WorkloadDetectionInput,
  thresholds: WorkloadThresholds = DEFAULT_WORKLOAD_THRESHOLDS,
): WorkloadFlag[] {
  const flags: WorkloadFlag[] = [];

  // 1) Too many schools.
  if (input.portfolio.schoolCount > thresholds.maxSchools) {
    flags.push({
      staffId: input.staffId, staffName: input.staffName,
      kind: "TooManySchools",
      severity: pctOver(input.portfolio.schoolCount, thresholds.maxSchools),
      message: `${input.portfolio.schoolCount} schools assigned, ${thresholds.maxSchools} is the healthy cap.`,
    });
  }

  // 2) Too many districts.
  if (input.portfolio.districtCount > thresholds.maxDistricts) {
    flags.push({
      staffId: input.staffId, staffName: input.staffName,
      kind: "TooManyDistricts",
      severity: pctOver(input.portfolio.districtCount, thresholds.maxDistricts),
      message: `${input.portfolio.districtCount} districts to coordinate across — context-switch cost adds up.`,
    });
  }

  // 3) Too many secondary districts.
  if (input.portfolio.secondaryDistrictCount > thresholds.maxSecondaryDistricts) {
    flags.push({
      staffId: input.staffId, staffName: input.staffName,
      kind: "TooManySecondaryDistricts",
      severity: pctOver(input.portfolio.secondaryDistrictCount, thresholds.maxSecondaryDistricts),
      message: `${input.portfolio.secondaryDistrictCount} secondary districts means many overnight trips.`,
    });
  }

  // 4) High daily travel km.
  if (input.avgDailyTravelKm > thresholds.maxDailyTravelKm) {
    flags.push({
      staffId: input.staffId, staffName: input.staffName,
      kind: "HighDailyTravelKm",
      severity: pctOver(input.avgDailyTravelKm, thresholds.maxDailyTravelKm),
      message: `Averaging ${Math.round(input.avgDailyTravelKm)}km/day — sustainable cap is ${thresholds.maxDailyTravelKm}km.`,
    });
  }

  // 5) Too many partners managed.
  if (input.portfolio.partnersManaged > thresholds.maxPartnersManaged) {
    flags.push({
      staffId: input.staffId, staffName: input.staffName,
      kind: "TooManyPartnersManaged",
      severity: pctOver(input.portfolio.partnersManaged, thresholds.maxPartnersManaged),
      message: `${input.portfolio.partnersManaged} partner relationships — coordination load doubles per partner.`,
    });
  }

  // 6) Too many pending tasks (inbox overload — distinct from
  //    portfolio overload).
  if (input.pendingTaskCount > thresholds.maxPendingTasks) {
    flags.push({
      staffId: input.staffId, staffName: input.staffName,
      kind: "TooManyPendingTasks",
      severity: pctOver(input.pendingTaskCount, thresholds.maxPendingTasks),
      message: `${input.pendingTaskCount} open tasks — the queue is becoming a backlog.`,
    });
  }

  // 7) Too many special projects.
  if (input.specialProjectsActive > thresholds.maxSpecialProjects) {
    flags.push({
      staffId: input.staffId, staffName: input.staffName,
      kind: "TooManySpecialProjects",
      severity: pctOver(input.specialProjectsActive, thresholds.maxSpecialProjects),
      message: `${input.specialProjectsActive} special projects in flight — protect core work.`,
    });
  }

  // 8) Repeated hotel trips.
  if (input.portfolio.hotelTripsCount > thresholds.maxHotelTripsPerMonth) {
    flags.push({
      staffId: input.staffId, staffName: input.staffName,
      kind: "RepeatedHotelTrips",
      severity: pctOver(input.portfolio.hotelTripsCount, thresholds.maxHotelTripsPerMonth),
      message: `${input.portfolio.hotelTripsCount} overnight trips this month — burnout territory.`,
    });
  }

  // 9) High target under high load. Multi-factor: only fires when
  //    BOTH the portfolio is heavy AND the target is above the team
  //    median. Catches "we set them up to fail."
  if (
    input.portfolio.schoolCount > thresholds.maxSchools * 0.85 &&
    (input.targetRatioVsMedian ?? 1) > 1.10
  ) {
    flags.push({
      staffId: input.staffId, staffName: input.staffName,
      kind: "HighTargetUnderHighLoad",
      severity: 80,
      message: `Target is ${Math.round(((input.targetRatioVsMedian ?? 1) - 1) * 100)}% above team median on top of a near-cap portfolio.`,
    });
  }

  return flags;
}

// ────────── Recommendation engine ──────────
//
// Reads the flag set + picks the most impactful intervention. The
// recommendations are deliberately concrete (numbers + names), not
// generic.

export type WorkloadRecommendationKind =
  | "ReduceTarget"
  | "RebalanceSchools"
  | "AddPartnerSupport"
  | "ApproveTravelSupport"
  | "AssignCoaching"
  | "RedistributeProjects";

export type WorkloadRecommendation = {
  staffId: string;
  staffName: string;
  kind: WorkloadRecommendationKind;
  /// 0..100 — how strongly the engine recommends it.
  priority: number;
  /// One sentence explaining what + why.
  message: string;
};

export function recommendInterventions(
  input: WorkloadDetectionInput,
  flags: WorkloadFlag[],
  thresholds: WorkloadThresholds = DEFAULT_WORKLOAD_THRESHOLDS,
): WorkloadRecommendation[] {
  if (flags.length === 0) return [];

  const recs: WorkloadRecommendation[] = [];
  const kinds = new Set(flags.map((f) => f.kind));

  // Schools over cap → rebalance is the strongest intervention.
  if (kinds.has("TooManySchools")) {
    const excess = input.portfolio.schoolCount - thresholds.maxSchools;
    recs.push({
      staffId: input.staffId, staffName: input.staffName,
      kind: "RebalanceSchools", priority: 90,
      message: `Move ${excess} school${excess === 1 ? "" : "s"} to a CCEO under the median load.`,
    });
  }

  // High-target-on-high-load → reduce target.
  if (kinds.has("HighTargetUnderHighLoad")) {
    recs.push({
      staffId: input.staffId, staffName: input.staffName,
      kind: "ReduceTarget", priority: 85,
      message: `Drop monthly target by ~15% this period; reassess after portfolio rebalance.`,
    });
  }

  // Many partners → add partner support OR redistribute partners.
  if (kinds.has("TooManyPartnersManaged")) {
    recs.push({
      staffId: input.staffId, staffName: input.staffName,
      kind: "AddPartnerSupport", priority: 70,
      message: `Assign a co-focal for at least one partner — coordination cost compounds.`,
    });
  }

  // Travel + hotels → approve travel/per-diem support.
  if (kinds.has("HighDailyTravelKm") || kinds.has("RepeatedHotelTrips")) {
    recs.push({
      staffId: input.staffId, staffName: input.staffName,
      kind: "ApproveTravelSupport", priority: 65,
      message: `Approve overnight support to cut average daily km; flag for travel-allowance review.`,
    });
  }

  // Too many tasks → coaching to triage / re-prioritise.
  if (kinds.has("TooManyPendingTasks")) {
    recs.push({
      staffId: input.staffId, staffName: input.staffName,
      kind: "AssignCoaching", priority: 50,
      message: `Pair with a CPL or senior CCEO for a one-hour inbox triage session.`,
    });
  }

  // Too many projects → redistribute.
  if (kinds.has("TooManySpecialProjects")) {
    recs.push({
      staffId: input.staffId, staffName: input.staffName,
      kind: "RedistributeProjects", priority: 55,
      message: `Reassign ${input.specialProjectsActive - thresholds.maxSpecialProjects} special project${input.specialProjectsActive - thresholds.maxSpecialProjects === 1 ? "" : "s"} so core school work doesn't suffer.`,
    });
  }

  // Multiple districts / secondary districts often share the same
  // remedy as too-many-schools — collapse so we don't double-recommend.
  // (No additional rec emitted here.)

  return recs.sort((a, b) => b.priority - a.priority);
}

// ────────── Helpers ──────────

function pctOver(actual: number, cap: number): number {
  if (cap <= 0) return 100;
  return Math.min(100, Math.round(((actual - cap) / cap) * 100));
}
