import "server-only";

// Live plan-builder data source — the production replacement for the mock
// arrays in `lib/plan-builder-engine.ts`. Maps the role-scoped
// `/planning/plan-builder` feed (real clustered + current-FY-SSA, not-yet-
// planned schools, with SSA-derived weakest interventions) and the live partner
// roster into the exact shapes `PlanBuilderDesktopView` consumes.
//
// Returns `null` when the backend is disabled OR the feed is unreachable, so the
// page can show an explicit empty/error state instead of inventing demo data.

import { fetchPlanBuilder, fetchPartners, type BePlanBuilderSchool, type BePlanBuilderCluster, type BePartner } from "@/lib/api/surfaces";
import { isBackendEnabled, type BackendUser } from "@/lib/api/backend";
import {
  DAILY_SCHOOL_VISIT_CAPACITY,
  WORKING_DAYS_PER_WEEK,
  PLANNING_WEEKS_IN_MONTH,
  type SchoolVisitRecommendation,
  type ClusterRecommendation,
  type PartnerCapacityProfile,
  type PartnerFollowUpRecommendation,
  type PlanRecommendationBundle,
  type Priority,
  type Intervention,
} from "@/lib/plan-builder-engine";

// Backend SSA intervention enum value → the plan-builder `Intervention` union.
// Keyed on the canonical enum value (stable) rather than the display label so
// copy drift never breaks the mapping. Education Technology has no plan-builder
// analogue and folds into Learning Environment (its nearest infra category).
const INTERVENTION_FROM_ENUM: Record<string, Intervention> = {
  teaching_and_learning: "Teaching Environment",
  financial_health: "Fees / Budget / Accounts",
  christlike_behaviour: "Christ-like Behavior",
  exposure_to_word_of_god: "Exposure to the Word of God",
  government_requirements: "Government Requirements",
  leadership: "Leadership Best Practice",
  education_technology: "Learning Environment",
  learning_environment: "Learning Environment",
};

function interventionFor(school: BePlanBuilderSchool): Intervention {
  const key = school.weakest[0]?.intervention;
  return (key && INTERVENTION_FROM_ENUM[key]) || "Teaching Environment";
}

// SSA average (0–10) → planning priority band. Lower SSA = higher priority.
function priorityFromSsa(ssa: number | null): Priority {
  if (ssa == null) return "Critical"; // no current SSA — top priority
  if (ssa < 4) return "Critical";
  if (ssa < 5.5) return "High";
  if (ssa < 7) return "Medium";
  if (ssa < 8.5) return "Low";
  return "Deferrable";
}

function priorityRank(p: Priority): number {
  return p === "Critical" ? 5 : p === "High" ? 4 : p === "Medium" ? 3 : p === "Low" ? 2 : 1;
}

function schoolReason(s: BePlanBuilderSchool): string {
  if (s.ssaScore == null) return "No current-FY SSA average on record — verify before planning.";
  const w = s.weakest[0];
  if (s.ssaScore < 5) return `SSA average ${s.ssaScore.toFixed(1)} — below the 5.0 risk threshold.`;
  if (w) return `Weakest area ${w.label} (${w.score}/10) — targeted support recommended.`;
  return `SSA average ${s.ssaScore.toFixed(1)} — maintain support.`;
}

function mapSchool(s: BePlanBuilderSchool, i: number): SchoolVisitRecommendation {
  const weakestIntervention = interventionFor(s);
  const priorityLevel = priorityFromSsa(s.ssaScore);
  const recommendedActivity: SchoolVisitRecommendation["recommendedActivity"] =
    s.ssaScore == null ? "SSA Verification" : priorityLevel === "Critical" ? "Follow-Up Visit" : "School Visit";
  const suggestedWeek = ((i % 4) + 1) as 1 | 2 | 3 | 4;
  return {
    schoolId: s.schoolId,
    schoolName: s.name,
    district: s.district,
    cluster: s.cluster,
    assignedCceo: s.owner ?? "—",
    ssaScore: s.ssaScore,
    weakestIntervention,
    priorityLevel,
    priorityReason: schoolReason(s),
    lastVisitDate: "—",
    lastTrainingDate: "—",
    recommendedActivity,
    recommendedTrainingCluster: null,
    suggestedWeek,
    routeGroup: `${s.cluster || s.district} · Week ${suggestedWeek}`,
    estimatedCost:
      recommendedActivity === "Follow-Up Visit" ? 105_000 : recommendedActivity === "SSA Verification" ? 65_000 : 95_000,
  };
}

function clusterPriority(avg: number | null): Priority {
  if (avg == null) return "Medium";
  if (avg < 5.5) return "Critical";
  if (avg < 6.5) return "High";
  if (avg < 7.5) return "Medium";
  return "Low";
}

function mapCluster(c: BePlanBuilderCluster): ClusterRecommendation {
  const mainWeakness = (c.weakest && INTERVENTION_FROM_ENUM[c.weakest.intervention]) || "Teaching Environment";
  const priorityLevel = clusterPriority(c.averageSsa);
  const expectedParticipants = Math.max(2, c.schoolCount * 2);
  return {
    clusterId: c.clusterId,
    clusterName: c.clusterName,
    district: c.district,
    schoolCount: c.schoolCount,
    averageSsa: c.averageSsa ?? 0,
    mainWeakness,
    recommendedActivity: c.weakest ? "School Improvement Training" : "Cluster Meeting",
    expectedParticipants,
    suggestedDate: "TBD",
    estimatedCost: c.weakest
      ? 2_400_000 + expectedParticipants * 18_000
      : 400_000 + expectedParticipants * 8_000,
    priorityLevel,
    priorityReason:
      c.averageSsa == null
        ? `${c.schoolCount} schools clustered; SSA averages pending.`
        : c.averageSsa < 6.5
          ? `Cluster averaging ${c.averageSsa.toFixed(1)} across ${c.schoolCount} schools${c.weakest ? ` — weakest area ${c.weakest.label}` : ""}.`
          : `Routine cluster activity to maintain ${c.averageSsa.toFixed(1)} SSA average.`,
  };
}

// Live partner → capacity profile. Identity + certification are REAL (from the
// Partner Register); the field-staff count and monthly capacity are DOCUMENTED
// ESTIMATES — the backend does not yet expose per-partner field-staff rosters
// (tracked as a follow-up). The capacity formula + estimate are surfaced in the
// UI so planners never mistake the estimate for a measured number.
const ESTIMATED_FIELD_STAFF = 2;

function mapPartner(p: BePartner): PartnerCapacityProfile {
  const activeFieldStaff = ESTIMATED_FIELD_STAFF;
  const monthlyCapacity = activeFieldStaff * DAILY_SCHOOL_VISIT_CAPACITY * WORKING_DAYS_PER_WEEK * PLANNING_WEEKS_IN_MONTH;
  return {
    partnerId: p.id,
    partnerName: p.name,
    certified: p.isCertified,
    activeFieldStaff,
    dailySchoolVisitCapacity: DAILY_SCHOOL_VISIT_CAPACITY,
    workingDaysPerWeek: WORKING_DAYS_PER_WEEK,
    planningWeeksInMonth: PLANNING_WEEKS_IN_MONTH,
    monthlyCapacity,
    currentAssignedThisMonth: 0,
    availableCapacity: monthlyCapacity,
    assignedDistricts: [],
    assignedClusters: [],
    certifiedInterventions: [],
    verificationPassRate: 0,
    salesforceComplianceRate: 0,
  };
}

// Follow-up recommendations for a partner, derived from the LIVE ready-to-plan
// schools. Without a per-partner district roster we rank by SSA risk (weakest
// first) and cap at the partner's monthly capacity — the same risk-ranked
// assignment the coverage engine specifies. Refined once partner districts are
// exposed by the backend.
function recommendationsFor(p: PartnerCapacityProfile, schools: SchoolVisitRecommendation[]): PartnerFollowUpRecommendation[] {
  return schools
    .filter((s) => s.ssaScore != null)
    .slice(0, p.monthlyCapacity)
    .map((s) => ({
      schoolId: s.schoolId,
      schoolName: s.schoolName,
      district: s.district,
      cluster: s.cluster,
      partnerId: p.partnerId,
      trainedByPartner: false,
      trainedIntervention: s.weakestIntervention,
      trainingDate: "—",
      ssaScoreForIntervention: s.ssaScore ?? 0,
      overallSsaScore: s.ssaScore ?? 0,
      followUpOverdueDays: 0,
      priorityLevel: s.priorityLevel,
      recommendationReason: `${s.cluster || s.district} — weakness in ${s.weakestIntervention}.`,
      routeGroup: s.routeGroup,
      estimatedCost: 120_000,
    }));
}

export type LivePlanBundle = PlanRecommendationBundle & {
  recommendationsByPartner: Record<string, PartnerFollowUpRecommendation[]>;
};

/** Live plan-builder bundle, or `null` when the backend is off/unreachable. */
export async function backendPlanBuilderBundle(user: BackendUser): Promise<LivePlanBundle | null> {
  if (!isBackendEnabled()) return null;
  const feed = await fetchPlanBuilder(user, "");
  if (!feed.live) return null;

  const highPrioritySchoolVisits = feed.data.schools
    .map(mapSchool)
    .sort((a, b) => priorityRank(b.priorityLevel) - priorityRank(a.priorityLevel));
  const highPriorityClusters = feed.data.clusters
    .map(mapCluster)
    .sort((a, b) => priorityRank(b.priorityLevel) - priorityRank(a.priorityLevel));

  // Live partner roster (identities real; capacity estimated — see mapPartner).
  const partnersRes = await fetchPartners(user, true);
  const partnerCapacityProfiles = partnersRes.live ? partnersRes.data.map(mapPartner) : [];

  const recommendationsByPartner: Record<string, PartnerFollowUpRecommendation[]> = {};
  for (const p of partnerCapacityProfiles) {
    recommendationsByPartner[p.partnerId] = recommendationsFor(p, highPrioritySchoolVisits);
  }

  return {
    highPrioritySchoolVisits,
    highPriorityClusters,
    partnerCapacityProfiles,
    defaultPartnerId: partnerCapacityProfiles[0]?.partnerId ?? "",
    recommendationsByPartner,
  };
}
