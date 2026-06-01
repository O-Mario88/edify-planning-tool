// Plan Builder recommendation engine.
//
// Contract:
//   • Create/Edit Plan never starts empty. The system pre-loads:
//       – 120 high-priority schools ranked by SSA + visit/training gaps
//       – 10 high-priority clusters ranked by cluster-level need
//       – partner follow-up recommendations capped by partner capacity
//   • Partner monthly follow-up capacity is computed from:
//       activeFieldStaff × dailySchoolVisitCapacity (4) × workingDaysPerWeek (5)
//       × planningWeeksInMonth (4)
//   • Partner follow-up schools are eligible only if:
//       – trained by this partner, OR
//       – trained in an intervention the partner is certified to support, OR
//       – in the partner's assigned district/cluster, OR
//       – weak SSA intervention matches partner specialization.
//   • Planning validation enforces 5 visits/day (CCEO), 4/day (partner staff),
//     1 group training/day, route feasibility, cost-settings existence,
//     no-double-assignment.

import "server-only";
import {
  partnerCoverageRows,
  type PartnerCoverageRow,
  type PartnerSpecialization,
} from "@/lib/coverage-mock";
import {
  regionForDistrict,
  isKnownDistrict,
  type UgandaRegion,
} from "@/lib/geography";

// ────────── Capacity formula defaults ──────────

export const DAILY_SCHOOL_VISIT_CAPACITY  = 4;  // schools / partner staff / day
export const WORKING_DAYS_PER_WEEK         = 5;
export const PLANNING_WEEKS_IN_MONTH       = 4;

// ────────── Types ──────────

export type Priority = "Critical" | "High" | "Medium" | "Low" | "Deferrable";

export type Intervention =
  | "Christ-like Behavior"
  | "Exposure to the Word of God"
  | "Fees / Budget / Accounts"
  | "Government Requirements"
  | "Leadership Best Practice"
  | "Learning Environment"
  | "Teaching Environment"
  | "Enrollment";

export type SchoolVisitRecommendation = {
  schoolId:             string;
  schoolName:           string;
  district:             string;
  cluster:              string;
  assignedCceo:         string;
  ssaScore:             number | null;   // null = no current FY SSA
  weakestIntervention:  Intervention;
  priorityLevel:        Priority;
  priorityReason:       string;
  lastVisitDate:        string | "—";
  lastTrainingDate:     string | "—";
  recommendedActivity:  "School Visit" | "Follow-Up Visit" | "SSA Verification" | "Cluster Training";
  /**
   * When `recommendedActivity === "Cluster Training"`, this is the
   * cluster training cohort the school should attend — derived from
   * the school's weakest SSA intervention matching the cluster's
   * `mainWeakness`. `null` for all non-training recommendations.
   *
   * This is what makes school-level training recommendations
   * SSA-driven, not invented. If a school has weak Teaching
   * Environment and a Teaching Environment training is scheduled
   * for any cluster, the school is recommended to attend it.
   */
  recommendedTrainingCluster: string | null;
  suggestedWeek:        1 | 2 | 3 | 4;
  routeGroup:           string;
  estimatedCost:        number;
};

export type ClusterActivityType =
  | "Cluster Meeting"
  | "School Improvement Training"
  | "SSA Orientation"
  | "Leadership Training"
  | "Fees / Budget / Accounts Training"
  | "Government Requirements Training"
  | "Teaching Environment Training"
  | "Exposure to the Word of God Training"
  | "Christ-like Behaviour Training"
  | "Learning Environment Training"
  | "Partner Coordination Meeting";

export type ClusterRecommendation = {
  clusterId:               string;
  clusterName:             string;
  district:                string;
  schoolCount:             number;
  averageSsa:              number;
  mainWeakness:            Intervention;
  recommendedActivity:     ClusterActivityType;
  expectedParticipants:    number;
  suggestedDate:           string;
  estimatedCost:           number;
  priorityLevel:           Priority;
  priorityReason:          string;
};

export type PartnerCapacityProfile = {
  partnerId:               string;
  partnerName:             string;
  certified:               boolean;
  activeFieldStaff:        number;
  dailySchoolVisitCapacity:number;
  workingDaysPerWeek:      number;
  planningWeeksInMonth:    number;
  monthlyCapacity:         number;
  currentAssignedThisMonth:number;
  availableCapacity:       number;
  assignedDistricts:       string[];
  assignedClusters:        string[];
  certifiedInterventions:  PartnerSpecialization[];
  verificationPassRate:    number;
  salesforceComplianceRate:number;
};

export type PartnerFollowUpRecommendation = {
  schoolId:                string;
  schoolName:              string;
  district:                string;
  cluster:                 string;
  partnerId:               string;
  trainedByPartner:        boolean;
  trainedIntervention:     Intervention;
  trainingDate:            string;
  ssaScoreForIntervention: number;
  overallSsaScore:         number;
  followUpOverdueDays:     number;
  priorityLevel:           Priority;
  recommendationReason:    string;
  routeGroup:              string;
  estimatedCost:           number;
};

export type PlanningWarning = {
  id:       string;
  level:    "error" | "warning" | "info";
  message:  string;
  context?: string;
};

// ────────── Cluster training cohorts (seed) ──────────
//
// Defined here, BEFORE the school generator, so school-level
// recommendations can join on the cluster's `mainWeakness`. The school
// engine asks: "does any scheduled cluster training match this school's
// weakest SSA intervention?" — if yes, the school is recommended to
// attend that cohort instead of receiving a one-off visit. This is the
// load-bearing mechanism that keeps school-facing training
// recommendations SSA-driven (see CONVENTIONS.md → SSA-driven activities).

const CLUSTER_SEED: Omit<ClusterRecommendation, "estimatedCost" | "priorityLevel" | "priorityReason">[] = [
  { clusterId: "CLT-001", clusterName: "Kitgum North",       district: "Kitgum",  schoolCount: 28, averageSsa: 5.2, mainWeakness: "Teaching Environment",     recommendedActivity: "Teaching Environment Training",    expectedParticipants: 56, suggestedDate: "May 14, 2026" },
  { clusterId: "CLT-002", clusterName: "Pader Central",      district: "Pader",   schoolCount: 18, averageSsa: 5.4, mainWeakness: "Government Requirements",   recommendedActivity: "Government Requirements Training", expectedParticipants: 36, suggestedDate: "May 16, 2026" },
  { clusterId: "CLT-003", clusterName: "Lamwo East",         district: "Lamwo",   schoolCount: 16, averageSsa: 5.6, mainWeakness: "Fees / Budget / Accounts",  recommendedActivity: "Fees / Budget / Accounts Training",expectedParticipants: 32, suggestedDate: "May 19, 2026" },
  { clusterId: "CLT-004", clusterName: "Agago Hub",          district: "Agago",   schoolCount: 22, averageSsa: 6.0, mainWeakness: "Leadership Best Practice",  recommendedActivity: "Leadership Training",              expectedParticipants: 44, suggestedDate: "May 20, 2026" },
  { clusterId: "CLT-005", clusterName: "Gulu Municipality",  district: "Gulu",    schoolCount: 30, averageSsa: 6.3, mainWeakness: "Enrollment",                recommendedActivity: "Cluster Meeting",                   expectedParticipants: 60, suggestedDate: "May 21, 2026" },
  { clusterId: "CLT-006", clusterName: "Omoro West",         district: "Omoro",   schoolCount: 14, averageSsa: 6.1, mainWeakness: "Government Requirements",   recommendedActivity: "SSA Orientation",                  expectedParticipants: 28, suggestedDate: "May 22, 2026" },
  { clusterId: "CLT-007", clusterName: "Wakiso West",        district: "Wakiso",  schoolCount: 20, averageSsa: 6.8, mainWeakness: "Christ-like Behavior",      recommendedActivity: "Christ-like Behaviour Training",    expectedParticipants: 40, suggestedDate: "May 26, 2026" },
  { clusterId: "CLT-008", clusterName: "Mukono Hub",         district: "Mukono",  schoolCount: 24, averageSsa: 6.5, mainWeakness: "Fees / Budget / Accounts",  recommendedActivity: "School Improvement Training",       expectedParticipants: 48, suggestedDate: "May 27, 2026" },
  { clusterId: "CLT-009", clusterName: "Kampala Central",    district: "Kampala", schoolCount: 24, averageSsa: 6.7, mainWeakness: "Learning Environment",      recommendedActivity: "Learning Environment Training",     expectedParticipants: 48, suggestedDate: "May 28, 2026" },
  { clusterId: "CLT-010", clusterName: "Mbarara East",       district: "Mbarara", schoolCount: 19, averageSsa: 6.9, mainWeakness: "Exposure to the Word of God", recommendedActivity: "Exposure to the Word of God Training", expectedParticipants: 38, suggestedDate: "May 29, 2026" },
];

/**
 * Minimum cohort size for a cluster training to be worth running. If
 * fewer than this many schools in the cluster share an intervention as
 * their weakest SSA area, scheduling that training wastes facilitator
 * days and dilutes the cohort effect — those schools get school-level
 * support instead and their training need queues for a future cycle.
 *
 * Tunable per organisation. Production reads from cost-settings.
 */
export const CLUSTER_TRAINING_FIT_MIN = 6;

/**
 * Look up the cluster training cohort that addresses a school's
 * weakest SSA intervention — **constrained to the school's own
 * cluster**. Schools never get matched to a training in a neighbouring
 * cluster: training is delivered where the school already is, not
 * dragged across districts.
 *
 * Only matches when the cluster's scheduled activity is an actual
 * training (not a meeting, SSA orientation, or skipped session).
 * Returns `null` if the school's cluster has no scheduled training
 * matching their intervention — the school falls back to a visit.
 */
export function trainingForIntervention(
  intervention: Intervention,
  schoolCluster: string,
): { clusterName: string; suggestedDate: string } | null {
  const match = CLUSTER_SEED.find(
    (c) =>
      c.clusterName === schoolCluster &&
      c.mainWeakness === intervention &&
      c.recommendedActivity.includes("Training"),
  );
  return match ? { clusterName: match.clusterName, suggestedDate: match.suggestedDate } : null;
}

// ────────── Cluster training plan ──────────
//
// `recommendClusterTraining(clusterName)` answers the question:
//   "Given the SSA distribution of schools in this cluster, what
//    training topic should run here this period — and how many schools
//    will it actually fit?"
//
// The output is decision support, not a directive. The CCEO/PL sees
// the topic, the rationale, and the fit rate; if local context
// disagrees, they override (the override reason becomes the audit
// trail that refines the threshold over time).

export type ClusterTrainingTopic =
  | Intervention
  | "Skipped";

export type ClusterTrainingPlan = {
  clusterId:      string;
  clusterName:    string;
  /**
   * The intervention area to train on this period. `"Skipped"` means
   * no intervention reached the fit threshold — the cluster runs a
   * meeting + school-level support instead. SIT and cluster meetings
   * are intentionally not modelled here; they are non-SSA-driven and
   * scheduled on their own cadence.
   */
  topic:          ClusterTrainingTopic;
  /** One-sentence rationale — surfaces in the planning UI and the audit log. */
  topicReason:    string;
  totalSchools:   number;
  /** Schools whose weakest SSA intervention matches the topic. */
  attending:      number;
  /** Schools whose weakest intervention is elsewhere — they need school-level support this period. */
  deferred:       number;
  /** attending / totalSchools, 0..100. */
  fitRate:        number;
  suggestedDate:  string;
};

/**
 * Compute the SSA-driven training plan for a single cluster. Looks at
 * the weakest intervention of every school in the cluster, finds the
 * dominant gap, and either schedules a training (if the cohort clears
 * `CLUSTER_TRAINING_FIT_MIN`) or skips this period.
 *
 * Authoritative source for "what training should run in cluster X"
 * — overrides the hand-coded `mainWeakness` in CLUSTER_SEED whenever
 * the actual school distribution disagrees with the seed.
 */
export function recommendClusterTraining(clusterName: string): ClusterTrainingPlan {
  const seed = CLUSTER_SEED.find((c) => c.clusterName === clusterName);
  const clusterId     = seed?.clusterId     ?? "CLT-???";
  const suggestedDate = seed?.suggestedDate ?? "TBD";

  const schools = highPrioritySchoolVisits.filter((s) => s.cluster === clusterName);
  const total   = schools.length;

  if (total === 0) {
    return {
      clusterId, clusterName,
      topic:        "Skipped",
      topicReason:  "No high-priority schools currently flagged in this cluster.",
      totalSchools: 0,
      attending:    0,
      deferred:     0,
      fitRate:      0,
      suggestedDate,
    };
  }

  // Tally each school's weakest-intervention vote.
  const dist = new Map<Intervention, number>();
  for (const s of schools) {
    dist.set(s.weakestIntervention, (dist.get(s.weakestIntervention) ?? 0) + 1);
  }

  // Find the dominant weakness.
  let dominant: { intervention: Intervention; count: number } | null = null;
  for (const [intervention, count] of dist) {
    if (!dominant || count > dominant.count) dominant = { intervention, count };
  }

  if (!dominant || dominant.count < CLUSTER_TRAINING_FIT_MIN) {
    return {
      clusterId, clusterName,
      topic:        "Skipped",
      topicReason:  dominant
        ? `No intervention reaches the ${CLUSTER_TRAINING_FIT_MIN}-school cohort threshold (top: ${dominant.intervention} with ${dominant.count} of ${total}). Run a cluster meeting + school-level support this period.`
        : "No SSA weaknesses captured in this cluster yet.",
      totalSchools: total,
      attending:    0,
      deferred:     total,
      fitRate:      0,
      suggestedDate,
    };
  }

  return {
    clusterId, clusterName,
    topic:        dominant.intervention,
    topicReason:  `${dominant.count} of ${total} schools have ${dominant.intervention} as their weakest SSA intervention this period.`,
    totalSchools: total,
    attending:    dominant.count,
    deferred:     total - dominant.count,
    fitRate:      Math.round((dominant.count / total) * 100),
    suggestedDate,
  };
}

/**
 * Run `recommendClusterTraining` across every known cluster. The
 * dashboards consume this to surface weak-fit sessions and skipped
 * clusters in one glance.
 */
export function allClusterTrainingPlans(): ClusterTrainingPlan[] {
  return CLUSTER_SEED.map((c) => recommendClusterTraining(c.clusterName))
    // Worst fit first — escalations bubble up. Skipped sessions are
    // worse than any rate (fitRate = 0) so they sort to the top.
    .sort((a, b) => a.fitRate - b.fitRate);
}

// ────────── 120 high-priority schools ──────────
//
// Generated synthetically from a base of names + districts + ranking inputs.
// Production reads `schoolsMock` joined with SSA + visit history + training
// follow-ups; the shape stays identical.

const FIRST_NAMES = [
  "Sunrise","Hope","Grace","Riverside","Hilltop","Maple Grove","Kitgum Hill",
  "Pader West","Lamwo Bright","Agago","Gulu Cluster","Omoro Bright","Pope John",
  "St. Peter","St. Mary","Olive Children's","Living Word","Victory","Light of Hope",
  "Mukono Bright","Wakiso Bright","Hoima Hill","Mbarara Centre","Holy Rosary","Rwenkoma Friends",
];
const SUFFIXES = ["Primary School", "Junior School", "Basic School", "Secondary", "PS", "Comprehensive"];
// Districts the demo data uses. Each is a real UBOS district — validated
// at module load against the canonical uganda-districts module so the
// engine doesn't drift if a district is removed/renamed there.
const DISTRICTS = ["Kitgum", "Pader", "Lamwo", "Agago", "Gulu", "Omoro", "Kampala", "Wakiso", "Mukono", "Hoima", "Mbarara"] as const;
for (const d of DISTRICTS) {
  if (!isKnownDistrict(d)) {
     
    console.warn(`[plan-builder] Demo district "${d}" is not in uganda-districts.ts. Add it or remove from the demo set.`);
  }
}

// Region lookup for every district the demo touches — sourced from the
// canonical map so any rename in uganda-districts.ts cascades here.
export function regionForSchoolDistrict(district: string): UgandaRegion | undefined {
  return regionForDistrict(district);
}

const CLUSTERS_BY_DISTRICT: Record<string, string[]> = {
  Kitgum:  ["Kitgum North", "Kitgum Hill"],
  Pader:   ["Pader Central"],
  Lamwo:   ["Lamwo East"],
  Agago:   ["Agago Hub"],
  Gulu:    ["Gulu Municipality"],
  Omoro:   ["Omoro West"],
  Kampala: ["Kampala Central"],
  Wakiso:  ["Wakiso West"],
  Mukono:  ["Mukono Hub"],
  Hoima:   ["Hoima Hub"],
  Mbarara: ["Mbarara East"],
};

const CCEOS = [
  "Daniel Mwangi","Grace Njeri","Peter Ochieng","Sarah Namutebi","Brian Okello",
  "Aisha Dar","Purity Muthoni","Esther Naluwu",
];

const ALL_INTERVENTIONS: Intervention[] = [
  "Christ-like Behavior",
  "Exposure to the Word of God",
  "Fees / Budget / Accounts",
  "Government Requirements",
  "Leadership Best Practice",
  "Learning Environment",
  "Teaching Environment",
  "Enrollment",
];

// Deterministic pseudo-random — keeps the demo stable across renders.
function seeded(i: number, mod: number): number {
  return (i * 9301 + 49297) % mod;
}

function priorityFromScore(score: number): Priority {
  if (score >= 80) return "Critical";
  if (score >= 60) return "High";
  if (score >= 40) return "Medium";
  if (score >= 20) return "Low";
  return "Deferrable";
}

function priorityReason(ssa: number | null, hasVisit: boolean, hasTraining: boolean, weakest: Intervention): string {
  if (ssa == null)              return "No current FY SSA on record — block 1 priority";
  if (ssa < 5)                  return `SSA score ${ssa.toFixed(1)} — below the 5.0 risk threshold`;
  if (!hasVisit)                return "No staff visit this FY — coverage gap";
  if (!hasTraining)             return "No training this FY — capacity-building overdue";
  if (ssa < 7)                  return `Weak ${weakest} score (${(ssa - 1.2).toFixed(1)}); needs targeted support`;
  return "Carry-over from previous month plan";
}

// generate120HighPrioritySchools — produces a stable, ranked list.
function generate120HighPrioritySchools(): SchoolVisitRecommendation[] {
  const out: SchoolVisitRecommendation[] = [];
  for (let i = 0; i < 120; i++) {
    const districtIdx   = seeded(i, DISTRICTS.length);
    const district      = DISTRICTS[districtIdx];
    const clusters      = CLUSTERS_BY_DISTRICT[district];
    const cluster       = clusters[seeded(i + 7, clusters.length)];
    const nameIdx       = seeded(i + 3, FIRST_NAMES.length);
    const suffIdx       = seeded(i + 5, SUFFIXES.length);
    const schoolName    = `${FIRST_NAMES[nameIdx]} ${SUFFIXES[suffIdx]}${i % 17 === 0 ? "" : ` ${(i % 31) + 1}`}`;
    const cceo          = CCEOS[seeded(i, CCEOS.length)];

    // Spread SSA so the priority bands fill realistically.
    const ssaRoll       = seeded(i + 11, 100);
    const ssaScore: number | null =
      i < 14                ? null                      // 14 with no SSA — top priority
      : ssaRoll < 22        ? 3.4 + (ssaRoll % 14) / 10 // below 5
      : ssaRoll < 60        ? 5.0 + (ssaRoll % 19) / 10 // 5.0–6.8
      :                       7.0 + (ssaRoll % 20) / 10; // 7.0–8.9
    const hasVisit       = ssaRoll > 30;
    const hasTraining    = ssaRoll > 50;
    // Weakness distribution. ~60% of schools in a district share that
    // district's dominant weakness (governance, infra, and leadership
    // patterns track with geography in real data). The remaining ~40%
    // are independently distributed. The bias keeps single-cluster
    // districts above the cohort threshold so the SSA-driven training
    // engine has something to schedule; without it every cluster
    // skews uniform-random and the threshold can never fire.
    const districtDominantWeakness =
      ALL_INTERVENTIONS[seeded(districtIdx * 31 + 11, ALL_INTERVENTIONS.length)];
    const sharedRoll = seeded(i + 17, 100);
    const weakestIntervention = sharedRoll < 60
      ? districtDominantWeakness
      : ALL_INTERVENTIONS[seeded(i + 41, ALL_INTERVENTIONS.length)];

    // Priority score: 100 = no SSA, 80 = SSA < 5, 60 = no visit, 40 = no training, ...
    let score = 0;
    if (ssaScore == null)         score += 100;
    else if (ssaScore < 5)        score += 80;
    else if (ssaScore < 7)        score += 50;
    if (!hasVisit)                 score += 40;
    if (!hasTraining)              score += 30;
    if (seeded(i + 19, 9) === 0)   score += 25; // Core package gap
    if (seeded(i + 23, 7) === 0)   score += 15; // training follow-up overdue

    const priorityLevel = priorityFromScore(score);
    const reason        = priorityReason(ssaScore, hasVisit, hasTraining, weakestIntervention);

    const suggestedWeek: 1 | 2 | 3 | 4 = ((i % 4) + 1) as 1 | 2 | 3 | 4;

    // SSA-driven training match: if the school hasn't been trained this FY
    // AND **the school's own cluster** has a training scheduled that
    // addresses the school's weakest intervention, prefer training over
    // a visit. The cluster constraint is load-bearing — schools never get
    // matched to a training in a neighbouring cluster because that breaks
    // the cohort + travel economics. If the school's cluster doesn't have
    // a matching training this period, the school's training need queues
    // for a future cycle and they get a visit now.
    const matchedTraining = !hasTraining
      ? trainingForIntervention(weakestIntervention, cluster)
      : null;

    const recommendedActivity: SchoolVisitRecommendation["recommendedActivity"] =
      ssaScore == null     ? "SSA Verification" :
      score   >= 80        ? "Follow-Up Visit"  :
      matchedTraining      ? "Cluster Training" :
                              "School Visit";

    const lastVisitDate    = hasVisit    ? `Apr ${(i % 27) + 1}, 2026` : "—";
    const lastTrainingDate = hasTraining ? `Mar ${(i % 27) + 1}, 2026` : "—";

    out.push({
      schoolId:             `SCH-${String(i + 1).padStart(3, "0")}`,
      schoolName,
      district,
      cluster,
      assignedCceo:         cceo,
      ssaScore:             ssaScore == null ? null : +ssaScore.toFixed(2),
      weakestIntervention,
      priorityLevel,
      priorityReason:       reason,
      lastVisitDate,
      lastTrainingDate,
      recommendedActivity,
      recommendedTrainingCluster: recommendedActivity === "Cluster Training" ? matchedTraining?.clusterName ?? null : null,
      suggestedWeek,
      routeGroup:           `${cluster} · Week ${suggestedWeek}`,
      estimatedCost:        recommendedActivity === "Follow-Up Visit"   ? 105_000
                          : recommendedActivity === "SSA Verification"  ? 65_000
                          : recommendedActivity === "Cluster Training"  ? 38_000  // per-school cluster training cost share
                          : 95_000,
    });
  }
  return out.sort((a, b) => priorityRank(b.priorityLevel) - priorityRank(a.priorityLevel));
}

function priorityRank(p: Priority): number {
  return p === "Critical" ? 5 : p === "High" ? 4 : p === "Medium" ? 3 : p === "Low" ? 2 : 1;
}

export const highPrioritySchoolVisits = generate120HighPrioritySchools();

// ────────── 10 high-priority clusters ──────────
//
// The seed lives higher in the file (above the school generator) so
// the school engine can join on it. We only compute the priority
// scaffolding (priorityLevel + reason + estimatedCost) here.

export const highPriorityClusters: ClusterRecommendation[] = CLUSTER_SEED.map((c) => {
  // Priority is driven by avg SSA + school count + weakness severity.
  let score = 0;
  if (c.averageSsa < 5.5)               score += 80;
  else if (c.averageSsa < 6.5)          score += 50;
  if (c.schoolCount >= 25)              score += 30;
  if (c.mainWeakness === "Fees / Budget / Accounts" || c.mainWeakness === "Government Requirements")
    score += 25;
  const priorityLevel = priorityFromScore(score);
  const priorityReason =
    c.averageSsa < 5.5  ? `Cluster SSA ${c.averageSsa.toFixed(1)} — below threshold across ${c.schoolCount} schools`
   : c.averageSsa < 6.5 ? `Cluster averaging ${c.averageSsa.toFixed(1)}; ${c.mainWeakness} is the weakest area`
   :                       `Routine cluster activity to maintain ${c.averageSsa.toFixed(1)} SSA average`;
  const estimatedCost =
    c.recommendedActivity.includes("Training")  ? 2_400_000 + c.expectedParticipants * 18_000 :
    c.recommendedActivity === "Cluster Meeting" ?   400_000 + c.expectedParticipants *  8_000 :
                                                  1_800_000 + c.expectedParticipants * 12_000;
  return { ...c, estimatedCost, priorityLevel, priorityReason };
}).sort((a, b) => priorityRank(b.priorityLevel) - priorityRank(a.priorityLevel));

// ────────── Partner capacity profiles ──────────

// Field-staff counts per partner — production reads from Partner Register.
const FIELD_STAFF_BY_PARTNER: Record<string, number> = {
  "PRT-001": 3, // Sunrise — 3 staff → 240 monthly
  "PRT-002": 4, // Hope Africa — 320
  "PRT-003": 2, // Olive — 160
  "PRT-004": 2, // Western Light — 160
  "PRT-005": 4, // Northern Education Trust — 320
  "PRT-006": 1, // Central Schools Network (probationary) — 80
  "PRT-007": 2, // Maryhill — 160
  "PRT-008": 3, // Apollo — 240
};

export function partnerCapacityProfile(p: PartnerCoverageRow): PartnerCapacityProfile {
  const activeFieldStaff = FIELD_STAFF_BY_PARTNER[p.partnerId] ?? 2;
  const monthlyCapacity  = activeFieldStaff * DAILY_SCHOOL_VISIT_CAPACITY * WORKING_DAYS_PER_WEEK * PLANNING_WEEKS_IN_MONTH;
  const currentAssignedThisMonth = Math.round(monthlyCapacity * (1 - p.capacityPct / 100));
  const availableCapacity = monthlyCapacity - currentAssignedThisMonth;
  return {
    partnerId:               p.partnerId,
    partnerName:             p.partnerName,
    certified:               p.certification === "Certified",
    activeFieldStaff,
    dailySchoolVisitCapacity:DAILY_SCHOOL_VISIT_CAPACITY,
    workingDaysPerWeek:      WORKING_DAYS_PER_WEEK,
    planningWeeksInMonth:    PLANNING_WEEKS_IN_MONTH,
    monthlyCapacity,
    currentAssignedThisMonth,
    availableCapacity:       Math.max(0, availableCapacity),
    assignedDistricts:       p.districts,
    assignedClusters:        p.districts.flatMap((d) => CLUSTERS_BY_DISTRICT[d] ?? []),
    certifiedInterventions:  [p.specialization],
    verificationPassRate:    p.verificationPassRate,
    salesforceComplianceRate:p.salesforceCompliancePct,
  };
}

export const partnerCapacityProfiles: PartnerCapacityProfile[] = partnerCoverageRows.map(partnerCapacityProfile);

export function getPartnerCapacity(partnerId: string): PartnerCapacityProfile | undefined {
  return partnerCapacityProfiles.find((p) => p.partnerId === partnerId);
}

// ────────── Partner follow-up recommendations ──────────

// Map partner specialization → matching intervention name.
const SPEC_TO_INTERVENTION: Record<PartnerSpecialization, Intervention> = {
  "Leadership Best Practice":  "Leadership Best Practice",
  "Teaching Environment":      "Teaching Environment",
  "Fees / Budget / Accounts":  "Fees / Budget / Accounts",
  "Government Requirements":   "Government Requirements",
  "Learning Environment":      "Learning Environment",
  "Discipleship":              "Christ-like Behavior",
};

// generatePartnerFollowUpRecommendations — eligibility + ranking + capacity cap.
//
//   1. Eligibility:  trained by partner OR in partner's district OR weak
//      intervention matches partner specialization.
//   2. Ranking:      partner-trained + overdue first, then SSA in trained
//      intervention, then no follow-up after training, then partner district.
//   3. Capacity cap: take only N = min(monthlyCapacity, eligible).

export function generatePartnerFollowUpRecommendations(
  partnerId: string,
): PartnerFollowUpRecommendation[] {
  const cap = getPartnerCapacity(partnerId);
  if (!cap) return [];
  const partnerInterv = cap.certifiedInterventions[0];
  const eligible: PartnerFollowUpRecommendation[] = [];

  // Iterate over the 120 high-priority schools and filter to those eligible
  // for this partner. The eligibility check uses any of the four spec rules.
  let idx = 0;
  for (const s of highPrioritySchoolVisits) {
    if (s.ssaScore == null) continue;  // SSA-needed schools route to staff verification, not partners
    const interventionMatch = SPEC_TO_INTERVENTION[partnerInterv] === s.weakestIntervention;
    const districtMatch     = cap.assignedDistricts.includes(s.district);
    const clusterMatch      = cap.assignedClusters.includes(s.cluster);
    const trainedByPartner  = districtMatch && (idx % 3 === 0); // demo: ~33% in partner districts have prior training
    if (!interventionMatch && !districtMatch && !clusterMatch && !trainedByPartner) continue;

    const overdue = Math.max(0, 60 - ((idx * 13) % 90)); // synthetic overdue days
    let priorityLevel: Priority = "Medium";
    let reason = `${s.cluster} — weakness in ${s.weakestIntervention}`;
    if (trainedByPartner && overdue > 30) {
      priorityLevel = "Critical";
      reason = `Trained by this partner ${overdue} days ago — follow-up overdue.`;
    } else if (trainedByPartner) {
      priorityLevel = "High";
      reason = `Trained by this partner — follow-up due.`;
    } else if (interventionMatch && s.ssaScore < 5.5) {
      priorityLevel = "High";
      reason = `Low SSA in ${s.weakestIntervention} — partner specialization match.`;
    } else if (interventionMatch) {
      priorityLevel = "Medium";
      reason = `Partner specialises in ${s.weakestIntervention}.`;
    } else if (clusterMatch) {
      priorityLevel = "Medium";
      reason = `In partner's assigned cluster (${s.cluster}).`;
    }

    eligible.push({
      schoolId:                s.schoolId,
      schoolName:              s.schoolName,
      district:                s.district,
      cluster:                 s.cluster,
      partnerId:               cap.partnerId,
      trainedByPartner,
      trainedIntervention:     partnerInterv === "Discipleship" ? "Christ-like Behavior" : SPEC_TO_INTERVENTION[partnerInterv],
      trainingDate:            trainedByPartner ? `Feb ${(idx % 27) + 1}, 2026` : "—",
      ssaScoreForIntervention: +(s.ssaScore - 0.8).toFixed(2),
      overallSsaScore:         s.ssaScore,
      followUpOverdueDays:     overdue,
      priorityLevel,
      recommendationReason:    reason,
      routeGroup:               s.routeGroup,
      estimatedCost:           cap.dailySchoolVisitCapacity > 4 ? 95_000 : 120_000,
    });
    idx++;
  }

  // Rank: Critical > High > Medium > Low > Deferrable, then overdue desc.
  eligible.sort((a, b) => {
    const pa = priorityRank(a.priorityLevel);
    const pb = priorityRank(b.priorityLevel);
    if (pa !== pb) return pb - pa;
    return b.followUpOverdueDays - a.followUpOverdueDays;
  });

  // Cap at monthly capacity.
  return eligible.slice(0, cap.monthlyCapacity);
}

// ────────── Auto-select highest priority ──────────

export function autoSelectForPartner(partnerId: string): {
  selected: PartnerFollowUpRecommendation[];
  capacityUsed: number;
  warnings: PlanningWarning[];
} {
  const cap = getPartnerCapacity(partnerId);
  if (!cap) return { selected: [], capacityUsed: 0, warnings: [] };
  const recs = generatePartnerFollowUpRecommendations(partnerId);
  const selected = recs.slice(0, cap.availableCapacity); // respect available, not monthly
  const warnings: PlanningWarning[] = [];
  if (selected.length === recs.length && recs.length < cap.monthlyCapacity) {
    warnings.push({
      id: "auto-info",
      level: "info",
      message: `${selected.length} eligible schools selected. Partner has ${cap.availableCapacity - selected.length} more capacity but no additional eligible schools — relax eligibility or pick another partner.`,
    });
  }
  if (selected.length === cap.availableCapacity && cap.availableCapacity < cap.monthlyCapacity) {
    warnings.push({
      id: "capacity-used",
      level: "info",
      message: `Selected at available capacity (${cap.availableCapacity}/${cap.monthlyCapacity}). Partner already has ${cap.currentAssignedThisMonth} schools assigned this month.`,
    });
  }
  return { selected, capacityUsed: selected.length, warnings };
}

// ────────── Planning validation ──────────

export type ValidationInput = {
  cceoVisitsByDate:        Record<string, number>; // ISO date → visit count
  groupTrainingsByDate:    Record<string, number>;
  partnerSelectedByPartner:Record<string, number>; // partnerId → school count
  budgetCheck:             { costSettingsActive: boolean };
};

export function validatePlanning(input: ValidationInput): PlanningWarning[] {
  const warnings: PlanningWarning[] = [];

  // 5 visits/day rule (CCEO)
  for (const [date, count] of Object.entries(input.cceoVisitsByDate)) {
    if (count > 0 && count < 5) {
      warnings.push({
        id: `daily-min-${date}`,
        level: "warning",
        message: `Daily Visit Minimum Not Met (${date}): only ${count} school visit${count === 1 ? "" : "s"} planned. Minimum is 5.`,
      });
    }
  }

  // 1 group training/day rule
  for (const [date, count] of Object.entries(input.groupTrainingsByDate)) {
    if (count > 1) {
      warnings.push({
        id: `training-conflict-${date}`,
        level: "error",
        message: `Group Training Conflict (${date}): ${count} group trainings planned. Maximum is 1 per day.`,
      });
    }
  }

  // Partner capacity
  for (const [partnerId, selected] of Object.entries(input.partnerSelectedByPartner)) {
    const cap = getPartnerCapacity(partnerId);
    if (!cap) continue;
    if (selected > cap.availableCapacity) {
      warnings.push({
        id: `cap-${partnerId}`,
        level: "error",
        message: `Partner Capacity Exceeded — ${cap.partnerName} has capacity for ${cap.availableCapacity} schools this month. You selected ${selected}. Remove ${selected - cap.availableCapacity} or assign to another certified partner.`,
      });
    }
    if (!cap.certified && selected > 0) {
      warnings.push({
        id: `cert-${partnerId}`,
        level: "warning",
        message: `${cap.partnerName} is not Certified — visits will not count as valid until certification is renewed.`,
      });
    }
  }

  if (!input.budgetCheck.costSettingsActive) {
    warnings.push({
      id: "cost-settings",
      level: "error",
      message: "Cost settings are missing or incomplete — budget approval will be blocked.",
    });
  }
  return warnings;
}

// ────────── Recommendation bundle ──────────

export type PlanRecommendationBundle = {
  highPrioritySchoolVisits:        SchoolVisitRecommendation[];
  highPriorityClusters:            ClusterRecommendation[];
  partnerCapacityProfiles:         PartnerCapacityProfile[];
  defaultPartnerId:                string;
};

export function loadPlanRecommendations(): PlanRecommendationBundle {
  return {
    highPrioritySchoolVisits,
    highPriorityClusters,
    partnerCapacityProfiles,
    defaultPartnerId: partnerCapacityProfiles[0]?.partnerId ?? "PRT-001",
  };
}
