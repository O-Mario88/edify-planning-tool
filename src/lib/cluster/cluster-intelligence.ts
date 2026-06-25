// Cluster Planning Intelligence — pure FE engine.
//
// Replaces the legacy "1st/2nd/3rd cluster meeting" planning model with an
// open-ended workflow. A cluster may have 0, 1, 3, 5, or 10+ meetings per
// FY; this module computes:
//
//   • per-intervention SSA averages (8 areas) with prior-cycle delta
//   • improved + declined interventions
//   • coverage gaps (schools not visited / not trained / neither)
//   • meeting cadence (count this FY, last meeting, met-this-quarter)
//   • a priority-ordered RECOMMENDATION (which intervention to focus on
//     and which activity to schedule next)
//
// Pure — no I/O, no server-only imports. Consumers (the cluster detail
// page, the planning gap engine, the System Health checks) feed in plain
// inputs and read back a structured intelligence object. Salesforce /
// backend swaps are pluggable: the inputs are shape-agnostic.

import { SSA_INTERVENTIONS } from "@/lib/planning/ssa-performance-mock";
import type { SsaInterventionArea } from "@/lib/planning/planning-gaps-mock";

// ────────── Inputs ──────────

/** One school record the intelligence engine consumes. Coverage flags are
 *  computed by the caller (FY/period scope is the caller's responsibility). */
export type ClusterIntelSchool = {
  schoolId: string;
  schoolName: string;
  schoolType: "Client" | "Core" | "Potential Core";
  /** True when the school has a current-FY SSA on record. */
  hasCurrentFySsa: boolean;
  /** Per-intervention current SSA scores (0-10). Omit when no SSA. */
  currentSsa?: Partial<Record<SsaInterventionArea, number>>;
  /** Per-intervention previous SSA scores (prior cycle, for delta calc). */
  previousSsa?: Partial<Record<SsaInterventionArea, number>>;
  /** True when the school received at least one staff or partner visit in
   *  the selected period. */
  visitedThisPeriod: boolean;
  /** True when the school participated in at least one training (cluster
   *  training counts) in the selected period. */
  trainedThisPeriod: boolean;
  /** Optional partner support assignment + project assignment for the
   *  school-row card on the cluster detail page. */
  partnerSupportName?: string;
  projectAssignmentName?: string;
};

/** One cluster activity (meeting / training / SIT / follow-up / project
 *  session) the intelligence engine consumes. Lifecycle status is mapped
 *  to a coarse three-state ("Completed" / "Scheduled" / "Other") so this
 *  module doesn't have to know the entire activity status enum. */
export type ClusterIntelActivity = {
  id: string;
  activityType:
    | "cluster_meeting"
    | "cluster_training"
    | "school_improvement_training"
    | "follow_up"
    | "project_cluster_session";
  /** ISO date (calendar-exact for meetings/trainings; this engine treats
   *  every meeting/training as needing an exact date). */
  date: string;
  status: "Completed" | "Scheduled" | "Other";
  focusInterventionArea?: SsaInterventionArea;
  teachersTrained?: number;
  schoolLeadersTrained?: number;
};

export type ClusterIntelInput = {
  /** Schools in the cluster (filtered to the period the caller cares about). */
  schools: ClusterIntelSchool[];
  /** Cluster activities, ANY count (no 3-meeting limit). */
  activities: ClusterIntelActivity[];
  /** Reference clock — defaults to `new Date()`. Tests inject a stable date. */
  now?: Date;
};

// ────────── Output types ──────────

export type SsaStatus = "Critical" | "Needs Support" | "Good" | "Strong";

export type InterventionPerformance = {
  intervention: SsaInterventionArea;
  averageScore: number;        // 0-10, rounded to 1dp
  schoolsAssessed: number;
  schoolsMissingSsa: number;
  previousAverage?: number;    // 0-10, rounded to 1dp, prior cycle
  delta?: number;              // current - previous, rounded to 1dp
  status: SsaStatus;
};

export type InterventionImprovement = {
  intervention: SsaInterventionArea;
  previousAverage: number;
  latestAverage: number;
  improvement: number;
  schoolsImproved: number;
};

export type InterventionDecline = {
  intervention: SsaInterventionArea;
  previousAverage: number;
  latestAverage: number;
  drop: number;
  schoolsDeclined: number;
  recommendedResponse: string;
};

export type ClusterCoverage = {
  total: number;
  client: number;
  core: number;
  potentialCore: number;
  withCurrentFySsa: number;
  missingSsa: number;
  visited: number;
  notVisited: ClusterIntelSchool[];
  trained: number;
  notTrained: ClusterIntelSchool[];
  neitherVisitNorTraining: ClusterIntelSchool[];
};

export type ClusterCadence = {
  meetingsThisFy: number;          // count of completed cluster_meeting
  meetingsScheduledThisFy: number; // count of scheduled cluster_meeting (not yet completed)
  trainingsThisFy: number;         // count of completed cluster_training + SIT
  totalActivitiesThisFy: number;
  lastMeetingDate?: string;        // ISO
  daysSinceLastMeeting?: number;
  nextScheduledDate?: string;      // ISO (any upcoming activity)
  metThisQuarter: boolean;
  teachersTrained: number;
  schoolLeadersTrained: number;
};

/** Priority codes for the recommendation engine — exposed so callers
 *  (System Health, the planning gap engine) can reason about which signal
 *  fired without re-parsing the headline copy. */
export type RecommendationPriority =
  | "ssa_drop"               // priority 1
  | "weak_intervention"      // priority 2
  | "schools_not_visited"    // priority 3
  | "schools_not_trained"    // priority 4
  | "no_meeting_this_quarter"// priority 5
  | "schools_neither"        // priority 6
  | "no_meetings_this_fy"    // priority 5b
  | "on_track";              // nothing outstanding

export type ClusterRecommendation = {
  priority: RecommendationPriority;
  /** The intervention to focus the next activity on (when one applies). */
  focusIntervention?: SsaInterventionArea;
  /** Suggested activity to schedule. */
  suggestedActivity: "meeting" | "training" | "follow_up" | "support_visit" | "review";
  /** One-line action label (e.g. "Schedule Cluster Training"). */
  suggestedActivityLabel: string;
  /** "Recommended Focus" headline (e.g. "Teaching & Learning"). */
  headline: string;
  /** "Reason" body (e.g. "Average dropped from 6.2 to 4.8 …"). */
  reason: string;
  /** How many schools the recommendation references. */
  schoolsAffected: number;
};

/** New open-ended cluster planning categories — replace the legacy 3-slot
 *  vocabulary (`no_first_meeting`, `no_second_meeting`, `no_third_meeting`,
 *  `no_sit`). One ENUM value per planning bucket the user listed. */
export type ClusterGapCategory =
  | "no_meetings_this_fy"
  | "not_met_this_quarter"
  | "schools_need_support"
  | "weak_ssa_intervention"
  | "ssa_performance_drop"
  | "schools_not_visited"
  | "schools_not_trained"
  | "schools_neither_visit_nor_training"
  | "training_needed"
  | "follow_up_needed"
  | "meeting_due"
  | "on_track";

export const CLUSTER_GAP_CATEGORY_LABEL: Record<ClusterGapCategory, string> = {
  no_meetings_this_fy:               "Cluster Has No Meetings This FY",
  not_met_this_quarter:              "Cluster Has Not Met This Quarter",
  schools_need_support:              "Cluster Has Schools Needing Support",
  weak_ssa_intervention:             "Cluster Has Weak SSA Intervention",
  ssa_performance_drop:              "Cluster Has SSA Performance Drop",
  schools_not_visited:               "Cluster Has Schools Not Visited",
  schools_not_trained:               "Cluster Has Schools Not Trained",
  schools_neither_visit_nor_training:"Cluster Has Schools With Neither Visit Nor Training",
  training_needed:                   "Cluster Training Needed",
  follow_up_needed:                  "Cluster Follow-Up Needed",
  meeting_due:                       "Cluster Meeting Due",
  on_track:                          "Cluster Is On Track",
};

export type ClusterIntelligence = {
  /** Performance per intervention (always all 8, with assessment counts). */
  ssaPerformance: InterventionPerformance[];
  /** Cluster-wide average across the 8 interventions (0-10, 1dp). */
  averageSsaScore: number;
  weakestIntervention?: InterventionPerformance;
  strongestIntervention?: InterventionPerformance;
  improved: InterventionImprovement[];
  declined: InterventionDecline[];
  coverage: ClusterCoverage;
  cadence: ClusterCadence;
  recommendation: ClusterRecommendation;
  /** Open planning bucket the cluster currently belongs to (for the
   *  planning gap board). Derived from the recommendation + cadence. */
  gapCategory: ClusterGapCategory;
};

// ────────── Helpers ──────────

const round1 = (n: number): number => Math.round(n * 10) / 10;

/** Status thresholds match the user's spec (0-4 Critical, 5-6 Needs
 *  Support, 7-8 Good, 9-10 Strong). */
export function statusForScore(score: number): SsaStatus {
  if (score >= 9) return "Strong";
  if (score >= 7) return "Good";
  if (score >= 5) return "Needs Support";
  return "Critical";
}

/** Quarter index 0..3 within calendar year of the date. */
function quarterIndex(d: Date): number {
  return Math.floor(d.getMonth() / 3);
}

/** Start of the cluster's "this quarter" window relative to `now`. */
function quarterStart(now: Date): Date {
  const q = quarterIndex(now);
  return new Date(now.getFullYear(), q * 3, 1);
}

function isoToDate(iso: string | undefined): Date | undefined {
  if (!iso) return undefined;
  const d = new Date(iso);
  return Number.isFinite(d.getTime()) ? d : undefined;
}

// ────────── Core compute ──────────

function computePerInterventionPerformance(
  schools: ClusterIntelSchool[],
): InterventionPerformance[] {
  const withSsa = schools.filter((s) => s.hasCurrentFySsa && s.currentSsa);
  const missingSsa = schools.length - withSsa.length;
  return SSA_INTERVENTIONS.map((intervention): InterventionPerformance => {
    const current = withSsa
      .map((s) => s.currentSsa?.[intervention])
      .filter((n): n is number => typeof n === "number" && Number.isFinite(n));
    const previous = schools
      .map((s) => s.previousSsa?.[intervention])
      .filter((n): n is number => typeof n === "number" && Number.isFinite(n));
    const averageScore = current.length
      ? round1(current.reduce((a, b) => a + b, 0) / current.length)
      : 0;
    const previousAverage = previous.length
      ? round1(previous.reduce((a, b) => a + b, 0) / previous.length)
      : undefined;
    const delta =
      previousAverage !== undefined ? round1(averageScore - previousAverage) : undefined;
    return {
      intervention,
      averageScore,
      schoolsAssessed: current.length,
      schoolsMissingSsa: missingSsa,
      previousAverage,
      delta,
      status: statusForScore(averageScore),
    };
  });
}

function computeImproved(
  schools: ClusterIntelSchool[],
  performance: InterventionPerformance[],
): InterventionImprovement[] {
  const out: InterventionImprovement[] = [];
  for (const p of performance) {
    if (p.previousAverage === undefined || p.delta === undefined) continue;
    if (p.delta < 0.5) continue;
    const schoolsImproved = schools.filter((s) => {
      const c = s.currentSsa?.[p.intervention];
      const pr = s.previousSsa?.[p.intervention];
      return typeof c === "number" && typeof pr === "number" && c - pr >= 0.5;
    }).length;
    out.push({
      intervention: p.intervention,
      previousAverage: p.previousAverage,
      latestAverage: p.averageScore,
      improvement: p.delta,
      schoolsImproved,
    });
  }
  return out.sort((a, b) => b.improvement - a.improvement);
}

function computeDeclined(
  schools: ClusterIntelSchool[],
  performance: InterventionPerformance[],
): InterventionDecline[] {
  const out: InterventionDecline[] = [];
  for (const p of performance) {
    if (p.previousAverage === undefined || p.delta === undefined) continue;
    if (p.delta > -0.5) continue;
    const schoolsDeclined = schools.filter((s) => {
      const c = s.currentSsa?.[p.intervention];
      const pr = s.previousSsa?.[p.intervention];
      return typeof c === "number" && typeof pr === "number" && pr - c >= 0.5;
    }).length;
    const drop = round1(Math.abs(p.delta));
    out.push({
      intervention: p.intervention,
      previousAverage: p.previousAverage,
      latestAverage: p.averageScore,
      drop,
      schoolsDeclined,
      recommendedResponse:
        drop >= 1.5
          ? `Schedule cluster training on ${p.intervention} — significant drop (${drop} points).`
          : `Schedule cluster meeting to discuss ${p.intervention} (down ${drop} points).`,
    });
  }
  return out.sort((a, b) => b.drop - a.drop);
}

function computeCoverage(schools: ClusterIntelSchool[]): ClusterCoverage {
  const notVisited = schools.filter((s) => !s.visitedThisPeriod);
  const notTrained = schools.filter((s) => !s.trainedThisPeriod);
  const neither = schools.filter((s) => !s.visitedThisPeriod && !s.trainedThisPeriod);
  return {
    total: schools.length,
    client: schools.filter((s) => s.schoolType === "Client").length,
    core: schools.filter((s) => s.schoolType === "Core").length,
    potentialCore: schools.filter((s) => s.schoolType === "Potential Core").length,
    withCurrentFySsa: schools.filter((s) => s.hasCurrentFySsa).length,
    missingSsa: schools.filter((s) => !s.hasCurrentFySsa).length,
    visited: schools.length - notVisited.length,
    notVisited,
    trained: schools.length - notTrained.length,
    notTrained,
    neitherVisitNorTraining: neither,
  };
}

function computeCadence(activities: ClusterIntelActivity[], now: Date): ClusterCadence {
  const completedMeetings = activities.filter(
    (a) => a.activityType === "cluster_meeting" && a.status === "Completed",
  );
  const scheduledMeetings = activities.filter(
    (a) => a.activityType === "cluster_meeting" && a.status === "Scheduled",
  );
  const trainings = activities.filter(
    (a) =>
      (a.activityType === "cluster_training" || a.activityType === "school_improvement_training") &&
      a.status === "Completed",
  );

  const meetingDates = [...completedMeetings, ...scheduledMeetings]
    .map((a) => isoToDate(a.date))
    .filter((d): d is Date => !!d)
    .sort((a, b) => a.getTime() - b.getTime());

  const completedDates = completedMeetings
    .map((a) => isoToDate(a.date))
    .filter((d): d is Date => !!d)
    .sort((a, b) => a.getTime() - b.getTime());
  const lastCompleted = completedDates.at(-1);

  const upcomingDates = activities
    .filter((a) => a.status === "Scheduled")
    .map((a) => isoToDate(a.date))
    .filter((d): d is Date => !!d && d.getTime() >= now.getTime())
    .sort((a, b) => a.getTime() - b.getTime());

  const qStart = quarterStart(now);
  const metThisQuarter = completedMeetings.some((m) => {
    const d = isoToDate(m.date);
    return d !== undefined && d.getTime() >= qStart.getTime();
  });

  return {
    meetingsThisFy: completedMeetings.length,
    meetingsScheduledThisFy: scheduledMeetings.length,
    trainingsThisFy: trainings.length,
    totalActivitiesThisFy: completedMeetings.length + scheduledMeetings.length + trainings.length,
    lastMeetingDate: lastCompleted?.toISOString().slice(0, 10),
    daysSinceLastMeeting: lastCompleted
      ? Math.floor((now.getTime() - lastCompleted.getTime()) / (1000 * 60 * 60 * 24))
      : undefined,
    nextScheduledDate: upcomingDates[0]?.toISOString().slice(0, 10),
    metThisQuarter,
    teachersTrained: activities.reduce((sum, a) => sum + (a.teachersTrained ?? 0), 0),
    schoolLeadersTrained: activities.reduce(
      (sum, a) => sum + (a.schoolLeadersTrained ?? 0),
      0,
    ),
    // Suppress unused-meetingDates warning — reserved for future trend chart.
    ...(meetingDates.length === 0 ? {} : {}),
  };
}

// ────────── Recommendation engine ──────────
//
// Priority order as specified by the user:
//   1. SSA performance drop on any intervention (>= 1.0)
//   2. Weakest intervention is Critical or Needs Support
//   3. Many schools not visited
//   4. Many schools not trained
//   5. Cluster hasn't met this quarter
//   6. Schools with neither visit nor training (URGENT)
//
// Implementation note: #6 ("urgent cluster support") is checked BEFORE
// #3/#4/#5 when the count is non-trivial — it represents the most
// dangerous coverage gap. The "many schools" thresholds are conservative
// (>= 25% of cluster, min 2) so small clusters don't flap.

function manyThreshold(total: number): number {
  if (total <= 0) return Infinity;
  return Math.max(2, Math.ceil(total * 0.25));
}

function buildRecommendation(args: {
  performance: InterventionPerformance[];
  improved: InterventionImprovement[];
  declined: InterventionDecline[];
  coverage: ClusterCoverage;
  cadence: ClusterCadence;
}): ClusterRecommendation {
  const { performance, declined, coverage, cadence } = args;
  const threshold = manyThreshold(coverage.total);

  // Priority 6 (escalated): schools with NEITHER visit nor training are
  // the most dangerous coverage gap — treat as priority 1 when the count
  // crosses the threshold. The user's spec lists this last but flags it
  // as "urgent", which we model by lifting it to top priority when
  // material.
  if (coverage.neitherVisitNorTraining.length >= threshold) {
    return {
      priority: "schools_neither",
      suggestedActivity: "support_visit",
      suggestedActivityLabel: "Schedule Urgent Cluster Support",
      headline: `Urgent: ${coverage.neitherVisitNorTraining.length} schools without visit or training`,
      reason: `${coverage.neitherVisitNorTraining.length} of ${coverage.total} schools in this cluster have received neither a visit nor a training this period. Prioritise targeted cluster support.`,
      schoolsAffected: coverage.neitherVisitNorTraining.length,
    };
  }

  // Priority 1: SSA performance drop.
  const topDrop = declined[0];
  if (topDrop && topDrop.drop >= 1.0) {
    return {
      priority: "ssa_drop",
      focusIntervention: topDrop.intervention,
      suggestedActivity: "training",
      suggestedActivityLabel: "Schedule Cluster Training",
      headline: topDrop.intervention,
      reason: `Average score dropped from ${topDrop.previousAverage} to ${topDrop.latestAverage} (${topDrop.drop} point drop) across ${topDrop.schoolsDeclined} school${topDrop.schoolsDeclined === 1 ? "" : "s"}.`,
      schoolsAffected: topDrop.schoolsDeclined,
    };
  }

  // Priority 2: weakest intervention is Critical or Needs Support.
  const ranked = [...performance]
    .filter((p) => p.schoolsAssessed > 0)
    .sort((a, b) => a.averageScore - b.averageScore);
  const weakest = ranked[0];
  if (weakest && (weakest.status === "Critical" || weakest.status === "Needs Support")) {
    return {
      priority: "weak_intervention",
      focusIntervention: weakest.intervention,
      suggestedActivity: "training",
      suggestedActivityLabel: "Schedule Cluster Training",
      headline: weakest.intervention,
      reason: `Cluster average is ${weakest.averageScore}/10 (${weakest.status}) across ${weakest.schoolsAssessed} school${weakest.schoolsAssessed === 1 ? "" : "s"} with SSA.${weakest.schoolsMissingSsa > 0 ? ` ${weakest.schoolsMissingSsa} school${weakest.schoolsMissingSsa === 1 ? "" : "s"} still need SSA.` : ""}`,
      schoolsAffected: weakest.schoolsAssessed,
    };
  }

  // Priority 3: many schools not visited.
  if (coverage.notVisited.length >= threshold) {
    return {
      priority: "schools_not_visited",
      suggestedActivity: "support_visit",
      suggestedActivityLabel: "Schedule Follow-Up Visits",
      headline: `${coverage.notVisited.length} schools have not been visited`,
      reason: `Plan a cluster-wide follow-up round to reach ${coverage.notVisited.length} schools that haven't received a visit this period.`,
      schoolsAffected: coverage.notVisited.length,
    };
  }

  // Priority 4: many schools not trained.
  if (coverage.notTrained.length >= threshold) {
    return {
      priority: "schools_not_trained",
      suggestedActivity: "training",
      suggestedActivityLabel: "Schedule Cluster Training",
      headline: `${coverage.notTrained.length} schools have not been trained`,
      reason: `Schedule cluster training to reach ${coverage.notTrained.length} schools that haven't participated in any training this period.${weakest ? ` Recommended focus: ${weakest.intervention}.` : ""}`,
      schoolsAffected: coverage.notTrained.length,
      focusIntervention: weakest?.intervention,
    };
  }

  // Priority 5: cluster hasn't met this FY (worse than just not this quarter).
  if (cadence.meetingsThisFy === 0 && cadence.meetingsScheduledThisFy === 0) {
    return {
      priority: "no_meetings_this_fy",
      suggestedActivity: "meeting",
      suggestedActivityLabel: "Schedule Cluster Meeting",
      headline: "Cluster has not met this fiscal year",
      reason: "Schedule a cluster meeting to establish the planning rhythm for this FY.",
      schoolsAffected: coverage.total,
    };
  }

  // Priority 5: cluster hasn't met this quarter.
  if (!cadence.metThisQuarter) {
    return {
      priority: "no_meeting_this_quarter",
      suggestedActivity: "meeting",
      suggestedActivityLabel: "Schedule Cluster Meeting",
      headline: "Cluster has not met this quarter",
      reason: `Last cluster meeting was ${cadence.daysSinceLastMeeting ?? "—"} days ago. Schedule a cluster meeting to maintain cadence.`,
      schoolsAffected: coverage.total,
      focusIntervention: weakest?.intervention,
    };
  }

  return {
    priority: "on_track",
    suggestedActivity: "review",
    suggestedActivityLabel: "Review Cluster",
    headline: "Cluster is on track",
    reason: "Cadence, SSA performance, and coverage are within thresholds. Continue current plan.",
    schoolsAffected: 0,
    focusIntervention: weakest?.intervention,
  };
}

function gapCategoryFromRecommendation(
  rec: ClusterRecommendation,
  coverage: ClusterCoverage,
  cadence: ClusterCadence,
): ClusterGapCategory {
  switch (rec.priority) {
    case "ssa_drop":               return "ssa_performance_drop";
    case "weak_intervention":      return "weak_ssa_intervention";
    case "schools_not_visited":    return "schools_not_visited";
    case "schools_not_trained":    return "schools_not_trained";
    case "schools_neither":        return "schools_neither_visit_nor_training";
    case "no_meetings_this_fy":    return "no_meetings_this_fy";
    case "no_meeting_this_quarter":return "not_met_this_quarter";
    case "on_track":
      // Even when the recommendation says "on track", surface secondary
      // signals so the planning board can show coverage/training gaps.
      if (coverage.missingSsa > 0) return "schools_need_support";
      if (cadence.trainingsThisFy === 0) return "training_needed";
      return "on_track";
  }
}

// ────────── Public entrypoint ──────────

export function computeClusterIntelligence(input: ClusterIntelInput): ClusterIntelligence {
  const now = input.now ?? new Date();
  const schools = input.schools;
  const activities = input.activities;

  const performance = computePerInterventionPerformance(schools);
  const improved = computeImproved(schools, performance);
  const declined = computeDeclined(schools, performance);
  const coverage = computeCoverage(schools);
  const cadence = computeCadence(activities, now);

  const assessed = performance.filter((p) => p.schoolsAssessed > 0);
  const averageSsaScore = assessed.length
    ? round1(assessed.reduce((sum, p) => sum + p.averageScore, 0) / assessed.length)
    : 0;
  const weakest = [...assessed].sort((a, b) => a.averageScore - b.averageScore)[0];
  const strongest = [...assessed].sort((a, b) => b.averageScore - a.averageScore)[0];

  const recommendation = buildRecommendation({
    performance, improved, declined, coverage, cadence,
  });
  const gapCategory = gapCategoryFromRecommendation(recommendation, coverage, cadence);

  return {
    ssaPerformance: performance,
    averageSsaScore,
    weakestIntervention: weakest,
    strongestIntervention: strongest,
    improved,
    declined,
    coverage,
    cadence,
    recommendation,
    gapCategory,
  };
}
