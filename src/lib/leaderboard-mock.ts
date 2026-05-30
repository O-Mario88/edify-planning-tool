// Verified Impact Leaderboard + Program Lead Performance Ranking.
//
// HARD CONTRACT: only verified work counts.
//   leaderboardCountable =
//     activity.status === "Verified" &&
//     activity.impactAssessmentVerified === true &&
//     activity.salesforceRecordId !== null;
//
// Tone is motivational, not punitive. Fairness context (leave, route load,
// blocked planning days, partner / fund delays) is shown alongside ranks
// before any escalation.

import type { CurrentUser } from "./schools-mock";
import { countryRollups } from "./workflow-mock";

// ────────── Categories ──────────

export const LEADERBOARD_CATEGORIES = [
  "Overall",
  "Training",
  "SSA",
  "School Visits",
  "Valid Visits",
  "Core Visits",
  "Core Trainings",
  "Salesforce Compliance",
  "MSC Stories",
  "Exam Results",
  "Enrollment Updates",
] as const;

export type LeaderboardCategory = typeof LEADERBOARD_CATEGORIES[number];

// ────────── Recognition badges ──────────

export type RecognitionBadge =
  | "Monthly Target Champion"
  | "Verified Impact Leader"
  | "Most Consistent"
  | "Quality Star"
  | "Salesforce Compliance Leader"
  | "Fastest Catch-Up"
  | "Core Program Champion"
  | "SSA Champion"
  | "Top Trainer"
  | "School Visit Leader"
  | "High Quality Verifier";

// ────────── Staff leaderboard record ──────────

export type LeaderboardRecord = {
  leaderboardId: string;
  periodType: "Weekly" | "Monthly" | "Quarterly" | "FYTD";
  periodStartDate: string;
  periodEndDate: string;
  staffId: string;
  staffName: string;
  initials: string;
  role: "CCEO" | "Program Lead" | "Partner" | "Other";
  region: string;
  country: "Uganda";
  district?: string;
  programLeadId?: string;
  programLeadName?: string;
  targetCategory: LeaderboardCategory;
  targetValue: number;
  verifiedCompleted: number;
  achievementPercent: number;
  rank: number;
  salesforceCompliancePercent: number;
  verificationPassRate: number;
  evidenceVerifiedCount: number;
  returnedRecordsCount: number;
  consistencyScore: number;
  feedbackScore?: number;
  contextAdjustmentNote?: string;
  recognitionBadge?: RecognitionBadge;
};

// Demo CCEO/staff. Each has verified counts across the categories so the
// engine can derive any category leaderboard from one source of truth.
type StaffSeed = {
  staffId: string;
  staffName: string;
  initials: string;
  region: string;
  district: string;
  programLeadId: string;
  programLeadName: string;
  // Targets per category
  trainingsTarget: number;
  ssaTarget: number;
  schoolVisitsTarget: number;
  validVisitsTarget: number;
  coreVisitsTarget: number;
  coreTrainingsTarget: number;
  salesforceTarget: number;
  mscStoriesTarget: number;
  examResultsTarget: number;
  enrollmentUpdatesTarget: number;
  // Verified completed
  trainingsCompleted: number;
  ssaCompleted: number;
  schoolVisitsCompleted: number;
  validVisitsCompleted: number;
  coreVisitsCompleted: number;
  coreTrainingsCompleted: number;
  salesforceCompliancePercent: number;
  mscStoriesCompleted: number;
  examResultsCompleted: number;
  enrollmentUpdatesCompleted: number;
  // Quality + context
  verificationPassRate: number;
  evidenceVerifiedCount: number;
  returnedRecordsCount: number;
  consistencyScore: number;
  feedbackScore: number;
  // Workload / context — drives the Fairness & Context load model.
  portfolioSchools: number;     // schools the CCEO plans for directly
  partnerSchools: number;       // portfolio schools delivered via partners
  partnersManaged: number;      // delivery partners coordinated
  clustersCovered: number;
  districtsCovered: number;
  travelKmPerCycle: number;     // distance travelled to hit monthly targets
  teamSupportActions: number;   // mentoring / support given to teammates
  extraProjects: number;        // org assignments outside the core role
  contextAdjustmentNote?: string;
};

const staffSeeds: StaffSeed[] = [
  {
    staffId: "STF-DM-014", staffName: "Daniel Mwangi", initials: "DM",
    region: "North", district: "Central",
    programLeadId: "PL-001", programLeadName: "Sarah Khan",
    trainingsTarget: 12, ssaTarget: 18, schoolVisitsTarget: 24, validVisitsTarget: 20,
    coreVisitsTarget: 8, coreTrainingsTarget: 8,
    salesforceTarget: 100, mscStoriesTarget: 4, examResultsTarget: 6, enrollmentUpdatesTarget: 6,
    trainingsCompleted: 14, ssaCompleted: 19, schoolVisitsCompleted: 26, validVisitsCompleted: 22,
    coreVisitsCompleted: 7, coreTrainingsCompleted: 7,
    salesforceCompliancePercent: 96, mscStoriesCompleted: 5, examResultsCompleted: 6, enrollmentUpdatesCompleted: 6,
    verificationPassRate: 94, evidenceVerifiedCount: 78, returnedRecordsCount: 2,
    consistencyScore: 92, feedbackScore: 88,
    portfolioSchools: 64, partnerSchools: 14, partnersManaged: 3, clustersCovered: 4,
    districtsCovered: 3, travelKmPerCycle: 180, teamSupportActions: 16, extraProjects: 2,
  },
  {
    staffId: "STF-GN-007", staffName: "Grace Nansubuga", initials: "GN",
    region: "Central", district: "Central",
    programLeadId: "PL-001", programLeadName: "Sarah Khan",
    trainingsTarget: 12, ssaTarget: 16, schoolVisitsTarget: 22, validVisitsTarget: 18,
    coreVisitsTarget: 8, coreTrainingsTarget: 8,
    salesforceTarget: 100, mscStoriesTarget: 4, examResultsTarget: 6, enrollmentUpdatesTarget: 6,
    trainingsCompleted: 18, ssaCompleted: 17, schoolVisitsCompleted: 24, validVisitsCompleted: 20,
    coreVisitsCompleted: 8, coreTrainingsCompleted: 8,
    salesforceCompliancePercent: 92, mscStoriesCompleted: 6, examResultsCompleted: 6, enrollmentUpdatesCompleted: 6,
    verificationPassRate: 90, evidenceVerifiedCount: 72, returnedRecordsCount: 3,
    consistencyScore: 88, feedbackScore: 90,
    portfolioSchools: 50, partnerSchools: 8, partnersManaged: 2, clustersCovered: 3,
    districtsCovered: 2, travelKmPerCycle: 90, teamSupportActions: 12, extraProjects: 1,
  },
  {
    staffId: "STF-PO-008", staffName: "Peter Ochieng", initials: "PO",
    region: "Central", district: "Cluster",
    programLeadId: "PL-002", programLeadName: "Imran Bashir",
    trainingsTarget: 10, ssaTarget: 14, schoolVisitsTarget: 18, validVisitsTarget: 16,
    coreVisitsTarget: 6, coreTrainingsTarget: 6,
    salesforceTarget: 100, mscStoriesTarget: 3, examResultsTarget: 4, enrollmentUpdatesTarget: 4,
    trainingsCompleted: 9, ssaCompleted: 13, schoolVisitsCompleted: 17, validVisitsCompleted: 14,
    coreVisitsCompleted: 5, coreTrainingsCompleted: 5,
    salesforceCompliancePercent: 78, mscStoriesCompleted: 2, examResultsCompleted: 3, enrollmentUpdatesCompleted: 3,
    verificationPassRate: 76, evidenceVerifiedCount: 48, returnedRecordsCount: 6,
    consistencyScore: 70, feedbackScore: 72,
    portfolioSchools: 70, partnerSchools: 18, partnersManaged: 4, clustersCovered: 5,
    districtsCovered: 4, travelKmPerCycle: 240, teamSupportActions: 9, extraProjects: 3,
    contextAdjustmentNote: "5 days approved leave; 2 cluster routes blocked",
  },
  {
    staffId: "STF-SN-009", staffName: "Sarah Namutebi", initials: "SN",
    region: "East", district: "West",
    programLeadId: "PL-002", programLeadName: "Imran Bashir",
    trainingsTarget: 10, ssaTarget: 14, schoolVisitsTarget: 20, validVisitsTarget: 16,
    coreVisitsTarget: 6, coreTrainingsTarget: 6,
    salesforceTarget: 100, mscStoriesTarget: 3, examResultsTarget: 4, enrollmentUpdatesTarget: 4,
    trainingsCompleted: 11, ssaCompleted: 14, schoolVisitsCompleted: 22, validVisitsCompleted: 18,
    coreVisitsCompleted: 6, coreTrainingsCompleted: 6,
    salesforceCompliancePercent: 90, mscStoriesCompleted: 4, examResultsCompleted: 4, enrollmentUpdatesCompleted: 4,
    verificationPassRate: 88, evidenceVerifiedCount: 62, returnedRecordsCount: 3,
    consistencyScore: 84, feedbackScore: 85,
    portfolioSchools: 46, partnerSchools: 10, partnersManaged: 2, clustersCovered: 3,
    districtsCovered: 2, travelKmPerCycle: 110, teamSupportActions: 14, extraProjects: 1,
  },
  {
    staffId: "STF-BO-005", staffName: "Brian Okello", initials: "BO",
    region: "North", district: "East",
    programLeadId: "PL-003", programLeadName: "Fatima Noor",
    trainingsTarget: 12, ssaTarget: 16, schoolVisitsTarget: 22, validVisitsTarget: 18,
    coreVisitsTarget: 8, coreTrainingsTarget: 8,
    salesforceTarget: 100, mscStoriesTarget: 4, examResultsTarget: 5, enrollmentUpdatesTarget: 5,
    trainingsCompleted: 7, ssaCompleted: 11, schoolVisitsCompleted: 14, validVisitsCompleted: 12,
    coreVisitsCompleted: 4, coreTrainingsCompleted: 4,
    salesforceCompliancePercent: 64, mscStoriesCompleted: 1, examResultsCompleted: 2, enrollmentUpdatesCompleted: 2,
    verificationPassRate: 64, evidenceVerifiedCount: 32, returnedRecordsCount: 9,
    consistencyScore: 58, feedbackScore: 60,
    portfolioSchools: 60, partnerSchools: 22, partnersManaged: 3, clustersCovered: 4,
    districtsCovered: 4, travelKmPerCycle: 220, teamSupportActions: 7, extraProjects: 2,
    contextAdjustmentNote: "Funding disbursement delayed 3 weeks; 4 leave days",
  },
  {
    staffId: "STF-EN-012", staffName: "Esther Nakato", initials: "EN",
    region: "West", district: "West",
    programLeadId: "PL-003", programLeadName: "Fatima Noor",
    trainingsTarget: 10, ssaTarget: 14, schoolVisitsTarget: 18, validVisitsTarget: 14,
    coreVisitsTarget: 6, coreTrainingsTarget: 6,
    salesforceTarget: 100, mscStoriesTarget: 3, examResultsTarget: 4, enrollmentUpdatesTarget: 4,
    trainingsCompleted: 12, ssaCompleted: 15, schoolVisitsCompleted: 19, validVisitsCompleted: 16,
    coreVisitsCompleted: 6, coreTrainingsCompleted: 6,
    salesforceCompliancePercent: 88, mscStoriesCompleted: 4, examResultsCompleted: 4, enrollmentUpdatesCompleted: 4,
    verificationPassRate: 89, evidenceVerifiedCount: 64, returnedRecordsCount: 3,
    consistencyScore: 86, feedbackScore: 84,
    portfolioSchools: 44, partnerSchools: 12, partnersManaged: 2, clustersCovered: 3,
    districtsCovered: 3, travelKmPerCycle: 130, teamSupportActions: 13, extraProjects: 2,
  },
];

// ────────── Engine: build a category leaderboard ──────────

function valueFor(s: StaffSeed, c: LeaderboardCategory) {
  switch (c) {
    case "Training":             return { v: s.trainingsCompleted,         t: s.trainingsTarget };
    case "SSA":                  return { v: s.ssaCompleted,               t: s.ssaTarget };
    case "School Visits":        return { v: s.schoolVisitsCompleted,      t: s.schoolVisitsTarget };
    case "Valid Visits":         return { v: s.validVisitsCompleted,       t: s.validVisitsTarget };
    case "Core Visits":          return { v: s.coreVisitsCompleted,        t: s.coreVisitsTarget };
    case "Core Trainings":       return { v: s.coreTrainingsCompleted,     t: s.coreTrainingsTarget };
    case "Salesforce Compliance":return { v: s.salesforceCompliancePercent, t: 100 };
    case "MSC Stories":          return { v: s.mscStoriesCompleted,        t: s.mscStoriesTarget };
    case "Exam Results":         return { v: s.examResultsCompleted,       t: s.examResultsTarget };
    case "Enrollment Updates":   return { v: s.enrollmentUpdatesCompleted, t: s.enrollmentUpdatesTarget };
    case "Overall":              return { v: 0, t: 0 }; // computed separately
  }
}

function pct(v: number, t: number) {
  if (t <= 0) return 0;
  return Math.round((v / t) * 100);
}

// Overall score (per spec): 40% target + 20% verification + 15% Salesforce
// + 15% consistency + 10% quality.
function overallScore(s: StaffSeed): number {
  const targetCategoriesAchieved = (
    [pct(s.trainingsCompleted, s.trainingsTarget) >= 100,
     pct(s.ssaCompleted, s.ssaTarget) >= 100,
     pct(s.schoolVisitsCompleted, s.schoolVisitsTarget) >= 100,
     pct(s.validVisitsCompleted, s.validVisitsTarget) >= 100,
     pct(s.coreVisitsCompleted, s.coreVisitsTarget) >= 100,
     pct(s.coreTrainingsCompleted, s.coreTrainingsTarget) >= 100,
    ].filter(Boolean).length / 6
  ) * 100;
  return Math.round(
    targetCategoriesAchieved * 0.40 +
    s.verificationPassRate * 0.20 +
    s.salesforceCompliancePercent * 0.15 +
    s.consistencyScore * 0.15 +
    s.feedbackScore * 0.10,
  );
}

const PERIOD = {
  type: "Monthly" as const,
  start: "2025-11-01",
  end: "2025-11-30",
};

function badgeFor(c: LeaderboardCategory, rank: number, s: StaffSeed): RecognitionBadge | undefined {
  if (rank !== 1) return undefined;
  switch (c) {
    case "Training":             return "Top Trainer";
    case "SSA":                  return "SSA Champion";
    case "School Visits":        return "School Visit Leader";
    case "Core Visits":
    case "Core Trainings":       return "Core Program Champion";
    case "Salesforce Compliance":return "Salesforce Compliance Leader";
    case "Overall":              return "Monthly Target Champion";
    default:                     return s.consistencyScore >= 85 ? "Most Consistent" : "Verified Impact Leader";
  }
}

export function calculateCategoryLeaderboard(
  category: LeaderboardCategory,
  seeds: StaffSeed[] = staffSeeds,
): LeaderboardRecord[] {
  const rows = seeds.map((s) => {
    const isOverall = category === "Overall";
    const v = isOverall ? overallScore(s) : valueFor(s, category).v;
    const t = isOverall ? 100 : valueFor(s, category).t;
    return {
      seed: s,
      v,
      t,
      ach: isOverall ? v : pct(v, t),
    };
  });
  // Sort by achievement, then a deterministic tie-break — verification
  // quality, consistency, then name — so equal scores never fall to
  // arbitrary seed order.
  rows.sort(
    (a, b) =>
      b.ach - a.ach ||
      b.seed.verificationPassRate - a.seed.verificationPassRate ||
      b.seed.consistencyScore - a.seed.consistencyScore ||
      a.seed.staffName.localeCompare(b.seed.staffName),
  );
  return rows.map((r) => {
    // Standard-competition rank: an equal score shares a place, so a real
    // tie reads "2, 2, 4" — not an arbitrary 2, 3.
    const rank = 1 + rows.filter((x) => x.ach > r.ach).length;
    return {
      leaderboardId: `LB-${category.replace(/\s+/g, "")}-${r.seed.staffId}`,
      periodType: PERIOD.type,
      periodStartDate: PERIOD.start,
      periodEndDate: PERIOD.end,
      staffId: r.seed.staffId,
      staffName: r.seed.staffName,
      initials: r.seed.initials,
      role: "CCEO",
      region: r.seed.region,
      country: "Uganda",
      district: r.seed.district,
      programLeadId: r.seed.programLeadId,
      programLeadName: r.seed.programLeadName,
      targetCategory: category,
      targetValue: r.t,
      verifiedCompleted: r.v,
      achievementPercent: r.ach,
      rank,
      salesforceCompliancePercent: r.seed.salesforceCompliancePercent,
      verificationPassRate: r.seed.verificationPassRate,
      evidenceVerifiedCount: r.seed.evidenceVerifiedCount,
      returnedRecordsCount: r.seed.returnedRecordsCount,
      consistencyScore: r.seed.consistencyScore,
      feedbackScore: r.seed.feedbackScore,
      contextAdjustmentNote: r.seed.contextAdjustmentNote,
      recognitionBadge: badgeFor(category, rank, r.seed),
    };
  });
}

export const overallMonthlyLeaders: LeaderboardRecord[] = calculateCategoryLeaderboard("Overall");

// ────────── Program Lead leaderboard ──────────

export type ProgramLeadLeaderboardRecord = {
  programLeadId: string;
  programLeadName: string;
  initials: string;
  country: "Uganda";
  region: string;
  staffSupervised: number;
  teamTargetAchievement: number;
  staffOnTrackPercent: number;
  verifiedActivities: number;
  salesforceCompliancePercent: number;
  verificationPassRate: number;
  coreSchoolProgressPercent: number;
  ssaCompletionPercent: number;
  backlogReductionScore: number;
  staffSupportResponsiveness: number;
  feedbackScore: number;
  overallProgramLeadScore: number;
  rank: number;
  recognitionBadge:
    | "Best Performing Program Lead"
    | "Team Growth Champion"
    | "Highest Verification Quality"
    | "Best Salesforce Compliance"
    | "Core School Progress Leader"
    | "Most Improved Team"
    | "Strongest Support Culture";
};

type ProgramLeadSeed = {
  programLeadId: string;
  programLeadName: string;
  initials: string;
  region: string;
  staffSupervised: number;
  teamTargetAchievement: number;
  staffOnTrackPercent: number;
  verifiedActivities: number;
  salesforceCompliance: number;
  verificationPassRate: number;
  coreSchoolProgress: number;
  ssaCompletion: number;
  backlogReductionScore: number;
  staffSupportResponsiveness: number;
  feedbackScore: number;
  // Workload / context — drives the Program Lead context load model.
  portfolioSchools: number;     // schools across the PL's whole team
  regionalPerformance: number;  // region-wide verified achievement %
};

const programLeadSeeds: ProgramLeadSeed[] = [
  { programLeadId: "PL-001", programLeadName: "Sarah Khan",   initials: "SK", region: "North",   staffSupervised: 14, teamTargetAchievement: 92, staffOnTrackPercent: 86, verifiedActivities: 312, salesforceCompliance: 94, verificationPassRate: 92, coreSchoolProgress: 78, ssaCompletion: 90, backlogReductionScore: 88, staffSupportResponsiveness: 90, feedbackScore: 90, portfolioSchools: 214, regionalPerformance: 85 },
  { programLeadId: "PL-002", programLeadName: "Imran Bashir", initials: "IB", region: "Central", staffSupervised: 12, teamTargetAchievement: 84, staffOnTrackPercent: 75, verifiedActivities: 240, salesforceCompliance: 84, verificationPassRate: 82, coreSchoolProgress: 70, ssaCompletion: 82, backlogReductionScore: 76, staffSupportResponsiveness: 78, feedbackScore: 78, portfolioSchools: 168, regionalPerformance: 77 },
  { programLeadId: "PL-003", programLeadName: "Fatima Noor",  initials: "FN", region: "East", staffSupervised: 11, teamTargetAchievement: 70, staffOnTrackPercent: 60, verifiedActivities: 178, salesforceCompliance: 72, verificationPassRate: 70, coreSchoolProgress: 56, ssaCompletion: 70, backlogReductionScore: 60, staffSupportResponsiveness: 70, feedbackScore: 72, portfolioSchools: 139, regionalPerformance: 69 },
];

function programLeadScore(p: ProgramLeadSeed): number {
  return Math.round(
    p.teamTargetAchievement * 0.30 +
    p.staffOnTrackPercent * 0.15 +
    p.verificationPassRate * 0.15 +
    p.salesforceCompliance * 0.10 +
    p.coreSchoolProgress * 0.10 +
    p.backlogReductionScore * 0.10 +
    p.staffSupportResponsiveness * 0.05 +
    p.feedbackScore * 0.05,
  );
}

export const programLeadLeaderboard: ProgramLeadLeaderboardRecord[] = (() => {
  const scored = programLeadSeeds
    .map((p) => ({ ...p, overallProgramLeadScore: programLeadScore(p) }))
    .sort(
      (a, b) =>
        b.overallProgramLeadScore - a.overallProgramLeadScore ||
        b.teamTargetAchievement - a.teamTargetAchievement ||
        a.programLeadName.localeCompare(b.programLeadName),
    );
  return scored.map((p) => {
    // Shared rank — equal overall scores share a place.
    const rank =
      1 +
      scored.filter(
        (x) => x.overallProgramLeadScore > p.overallProgramLeadScore,
      ).length;
    let badge: ProgramLeadLeaderboardRecord["recognitionBadge"] = "Strongest Support Culture";
    if (rank === 1) badge = "Best Performing Program Lead";
    else if (p.coreSchoolProgress >= 75) badge = "Core School Progress Leader";
    else if (p.salesforceCompliance >= 90) badge = "Best Salesforce Compliance";
    else if (p.verificationPassRate >= 90) badge = "Highest Verification Quality";
    return {
      programLeadId: p.programLeadId,
      programLeadName: p.programLeadName,
      initials: p.initials,
      country: "Uganda" as const,
      region: p.region,
      staffSupervised: p.staffSupervised,
      teamTargetAchievement: p.teamTargetAchievement,
      staffOnTrackPercent: p.staffOnTrackPercent,
      verifiedActivities: p.verifiedActivities,
      salesforceCompliancePercent: p.salesforceCompliance,
      verificationPassRate: p.verificationPassRate,
      coreSchoolProgressPercent: p.coreSchoolProgress,
      ssaCompletionPercent: p.ssaCompletion,
      backlogReductionScore: p.backlogReductionScore,
      staffSupportResponsiveness: p.staffSupportResponsiveness,
      feedbackScore: p.feedbackScore,
      overallProgramLeadScore: p.overallProgramLeadScore,
      rank,
      recognitionBadge: badge,
    };
  });
})();

// ────────── Role-aware filters ──────────

function filterStaffLeaderboardForUser(
  rows: LeaderboardRecord[],
  user: CurrentUser,
): LeaderboardRecord[] {
  if (user.role === "Admin" || user.role === "CountryDirector") return rows;
  if (user.role === "CountryProgramLead") return rows; // demo: supervises everyone
  return rows.filter((r) => r.staffId === user.staffId);
}

// Cross-dashboard summary (for callout cards on CCEO/CPL/Director dashboards)
export function leaderboardSummaryFor(user: CurrentUser) {
  const overall = filterStaffLeaderboardForUser(overallMonthlyLeaders, user);
  const top = overall[0];
  const myRow = overall.find((r) => r.staffId === user.staffId);
  return {
    topStaffName: top?.staffName,
    topStaffScore: top?.achievementPercent,
    myRank: myRow?.rank,
    myAchievement: myRow?.achievementPercent,
    bestProgramLead: programLeadLeaderboard[0]?.programLeadName,
    bestProgramLeadScore: programLeadLeaderboard[0]?.overallProgramLeadScore,
  };
}

// ────────── Fairness & Context — workload / context load model ──────────
//
// The leaderboard ranks verified achievement. This model measures how
// DEMANDING each person's context is, so a lower raw % from someone
// carrying a heavy portfolio is read fairly. It is display-only — it
// never changes the achievement rank (motivational, not punitive).
//
//   CCEO load  = portfolio schools (incl. partner-handled) + partners
//                managed + clusters + districts + travel distance +
//                team-support given + extra org projects.
//   PL load    = CCEOs managed + schools in portfolio; team and regional
//                performance are shown alongside as outcome context.

export type ContextBand = "Light" | "Moderate" | "Heavy" | "Very Heavy";

export type ContextFactor = {
  key: string;
  label: string;
  display: string;
  sub?: string;
  intensity: number; // 0..1, relative to the heaviest in the cohort
};

function contextBand(index: number): ContextBand {
  if (index >= 78) return "Very Heavy";
  if (index >= 58) return "Heavy";
  if (index >= 38) return "Moderate";
  return "Light";
}

const ratioOf = (v: number, max: number) => (max > 0 ? v / max : 0);

export type CceoContextProfile = {
  staffId: string;
  staffName: string;
  initials: string;
  region: string;
  programLeadName?: string;
  totalPortfolioSchools: number;
  loadIndex: number;
  band: ContextBand;
  factors: ContextFactor[];
  note?: string;
};

// Weights sum to 1. Portfolio size and travel carry the most weight —
// they are the hardest constraints a CCEO cannot control.
const CCEO_LOAD_WEIGHTS = {
  schools: 0.28,
  travel: 0.16,
  partners: 0.12,
  clusters: 0.12,
  districts: 0.12,
  support: 0.1,
  extra: 0.1,
};

export const cceoContextProfiles: CceoContextProfile[] = (() => {
  const totalSchools = (s: StaffSeed) => s.portfolioSchools + s.partnerSchools;
  const max = {
    schools: Math.max(...staffSeeds.map(totalSchools)),
    travel: Math.max(...staffSeeds.map((s) => s.travelKmPerCycle)),
    partners: Math.max(...staffSeeds.map((s) => s.partnersManaged)),
    clusters: Math.max(...staffSeeds.map((s) => s.clustersCovered)),
    districts: Math.max(...staffSeeds.map((s) => s.districtsCovered)),
    support: Math.max(...staffSeeds.map((s) => s.teamSupportActions)),
    extra: Math.max(...staffSeeds.map((s) => s.extraProjects)),
  };
  return staffSeeds
    .map((s) => {
      const schools = totalSchools(s);
      const i = {
        schools: ratioOf(schools, max.schools),
        travel: ratioOf(s.travelKmPerCycle, max.travel),
        partners: ratioOf(s.partnersManaged, max.partners),
        clusters: ratioOf(s.clustersCovered, max.clusters),
        districts: ratioOf(s.districtsCovered, max.districts),
        support: ratioOf(s.teamSupportActions, max.support),
        extra: ratioOf(s.extraProjects, max.extra),
      };
      const loadIndex = Math.round(
        100 *
          (CCEO_LOAD_WEIGHTS.schools * i.schools +
            CCEO_LOAD_WEIGHTS.travel * i.travel +
            CCEO_LOAD_WEIGHTS.partners * i.partners +
            CCEO_LOAD_WEIGHTS.clusters * i.clusters +
            CCEO_LOAD_WEIGHTS.districts * i.districts +
            CCEO_LOAD_WEIGHTS.support * i.support +
            CCEO_LOAD_WEIGHTS.extra * i.extra),
      );
      return {
        staffId: s.staffId,
        staffName: s.staffName,
        initials: s.initials,
        region: s.region,
        programLeadName: s.programLeadName,
        totalPortfolioSchools: schools,
        loadIndex,
        band: contextBand(loadIndex),
        factors: [
          {
            key: "schools",
            label: "Portfolio schools",
            display: `${schools}`,
            sub: `${s.partnerSchools} via partners`,
            intensity: i.schools,
          },
          {
            key: "travel",
            label: "Travel / cycle",
            display: `${s.travelKmPerCycle} km`,
            intensity: i.travel,
          },
          {
            key: "partners",
            label: "Partners managed",
            display: `${s.partnersManaged}`,
            intensity: i.partners,
          },
          {
            key: "clusters",
            label: "Clusters",
            display: `${s.clustersCovered}`,
            intensity: i.clusters,
          },
          {
            key: "districts",
            label: "Districts",
            display: `${s.districtsCovered}`,
            intensity: i.districts,
          },
          {
            key: "support",
            label: "Team support",
            display: `${s.teamSupportActions}`,
            sub: "sessions given",
            intensity: i.support,
          },
          {
            key: "extra",
            label: "Extra projects",
            display: `${s.extraProjects}`,
            intensity: i.extra,
          },
        ],
        note: s.contextAdjustmentNote,
      };
    })
    .sort((a, b) => b.loadIndex - a.loadIndex);
})();

export type ProgramLeadContextProfile = {
  programLeadId: string;
  programLeadName: string;
  initials: string;
  region: string;
  cceosManaged: number;
  portfolioSchools: number;
  teamPerformancePercent: number;
  regionalPerformancePercent: number;
  loadIndex: number;
  band: ContextBand;
  factors: ContextFactor[];
};

export const programLeadContextProfiles: ProgramLeadContextProfile[] = (() => {
  const maxCceos = Math.max(...programLeadSeeds.map((p) => p.staffSupervised));
  const maxSchools = Math.max(...programLeadSeeds.map((p) => p.portfolioSchools));
  return programLeadSeeds
    .map((p) => {
      const ci = ratioOf(p.staffSupervised, maxCceos);
      const si = ratioOf(p.portfolioSchools, maxSchools);
      // PL load is scope-driven: CCEOs managed + schools in portfolio.
      const loadIndex = Math.round(100 * (0.5 * ci + 0.5 * si));
      return {
        programLeadId: p.programLeadId,
        programLeadName: p.programLeadName,
        initials: p.initials,
        region: p.region,
        cceosManaged: p.staffSupervised,
        portfolioSchools: p.portfolioSchools,
        teamPerformancePercent: p.teamTargetAchievement,
        regionalPerformancePercent: p.regionalPerformance,
        loadIndex,
        band: contextBand(loadIndex),
        factors: [
          {
            key: "cceos",
            label: "CCEOs managed",
            display: `${p.staffSupervised}`,
            intensity: ci,
          },
          {
            key: "schools",
            label: "Schools in portfolio",
            display: `${p.portfolioSchools}`,
            intensity: si,
          },
        ],
      };
    })
    .sort((a, b) => b.loadIndex - a.loadIndex);
})();

// Most improved staff: rank by month-over-month achievement growth.
// Mocked from consistency + verification trend so the engine call exists.
export type MostImprovedRow = {
  staffId: string;
  staffName: string;
  improvementPoints: number;
  category: LeaderboardCategory;
};

export const mostImprovedStaff: MostImprovedRow[] = [
  { staffId: "STF-EN-012", staffName: "Esther Nakato",  improvementPoints: 14, category: "Training" },
  { staffId: "STF-SN-009", staffName: "Sarah Namutebi", improvementPoints: 11, category: "Valid Visits" },
  { staffId: "STF-PO-008", staffName: "Peter Ochieng",  improvementPoints: 8,  category: "SSA" },
];

// ────────── Country Director leaderboard ──────────
//
// Derived from the single `countryRollups` source (workflow-mock) so the
// "best Country Director" recognition can never drift from the Country
// Comparison table on the RVP dashboard. One country = one director.

export type CountryDirectorRecord = {
  directorName: string;
  initials: string;
  country: string;
  schools: number;
  monthlyTargetPct: number;
  validVisitPct: number;
  ssaCompletedPct: number;
  fundsUtilizationPct: number;
  directorScore: number;
  rank: number;
};

function initialsOf(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

// Director score: 50% monthly target + 25% valid-visit quality + 25% SSA
// coverage. Verified field outcomes, not funds throughput.
export const countryDirectorLeaderboard: CountryDirectorRecord[] = (() => {
  const scored = countryRollups.map((c) => ({
    c,
    score: Math.round(
      c.monthlyTargetPct * 0.5 + c.validVisitPct * 0.25 + c.ssaCompletedPct * 0.25,
    ),
  }));
  scored.sort(
    (a, b) =>
      b.score - a.score ||
      b.c.monthlyTargetPct - a.c.monthlyTargetPct ||
      a.c.director.localeCompare(b.c.director),
  );
  return scored.map(({ c, score }) => ({
    directorName: c.director,
    initials: initialsOf(c.director),
    country: c.country,
    schools: c.schools,
    monthlyTargetPct: c.monthlyTargetPct,
    validVisitPct: c.validVisitPct,
    ssaCompletedPct: c.ssaCompletedPct,
    fundsUtilizationPct: Math.round(
      (c.fundsDisbursedUgxM / c.fundsCommittedUgxM) * 100,
    ),
    directorScore: score,
    // Shared rank — equal director scores share a place.
    rank: 1 + scored.filter((x) => x.score > score).length,
  }));
})();

// ────────── Role-aware "best performers" panels ──────────
//
// One resolver owns every dashboard's recognition card so the gating and
// the data shaping live in a single place. The component is a dumb
// renderer of whatever tiles this returns.

export type BestPerformerTone = "amber" | "violet" | "emerald" | "sky";
export type BestPerformerKind = "cceo" | "pl" | "cd" | "improved";

export type BestPerformerStat = { label: string; value: string };

export type BestPerformerTile = {
  key: string;
  kind: BestPerformerKind;
  roleLabel: string;
  name: string;
  initials: string;
  context: string;
  badge: string;
  scoreLabel: string;
  scoreValue: string;
  stats: BestPerformerStat[];
  tone: BestPerformerTone;
};

export type BestPerformersAudience = "cpl" | "cd" | "rvp" | "hr";

export type BestPerformersPanel = {
  title: string;
  subtitle: string;
  tiles: BestPerformerTile[];
};

// Map a signed-in Program Lead to a leaderboard programLeadId. Demo data
// uses different PL names than the auth store, so we match by name and
// fall back to the first PL seed for any unmatched account.
export function programLeadIdForUser(user?: CurrentUser): string {
  if (user) {
    const byName = programLeadSeeds.find(
      (p) => p.programLeadName.toLowerCase() === user.name.toLowerCase(),
    );
    if (byName) return byName.programLeadId;
  }
  return programLeadSeeds[0].programLeadId;
}

function cceoOverallTile(
  rec: LeaderboardRecord,
  roleLabel: string,
  tone: BestPerformerTone,
): BestPerformerTile {
  return {
    key: `cceo-ov-${rec.staffId}`,
    kind: "cceo",
    roleLabel,
    name: rec.staffName,
    initials: rec.initials,
    context: `${rec.region} · ${rec.programLeadName ?? "—"}`,
    badge: rec.recognitionBadge ?? "Verified Impact Leader",
    scoreLabel: "Verified %",
    scoreValue: `${rec.achievementPercent}%`,
    stats: [
      { label: "Salesforce", value: `${rec.salesforceCompliancePercent}%` },
      { label: "Pass rate", value: `${rec.verificationPassRate}%` },
      { label: "Consistency", value: `${rec.consistencyScore}` },
    ],
    tone,
  };
}

function cceoSsaTile(
  rec: LeaderboardRecord,
  roleLabel: string,
  tone: BestPerformerTone,
): BestPerformerTile {
  return {
    key: `cceo-ssa-${rec.staffId}`,
    kind: "cceo",
    roleLabel,
    name: rec.staffName,
    initials: rec.initials,
    context: `${rec.region} · ${rec.programLeadName ?? "—"}`,
    badge: "SSA Champion",
    scoreLabel: "SSA %",
    scoreValue: `${rec.achievementPercent}%`,
    stats: [
      { label: "SSA done", value: `${rec.verifiedCompleted}/${rec.targetValue}` },
      { label: "Pass rate", value: `${rec.verificationPassRate}%` },
      { label: "Salesforce", value: `${rec.salesforceCompliancePercent}%` },
    ],
    tone,
  };
}

function plTile(
  rec: ProgramLeadLeaderboardRecord,
  roleLabel: string,
  tone: BestPerformerTone,
  highlight: "overall" | "ssa" = "overall",
): BestPerformerTile {
  const isSsa = highlight === "ssa";
  return {
    key: `pl-${rec.programLeadId}-${highlight}`,
    kind: "pl",
    roleLabel,
    name: rec.programLeadName,
    initials: rec.initials,
    context: `${rec.region} · ${rec.staffSupervised} staff`,
    badge: isSsa ? "SSA Coverage Leader" : rec.recognitionBadge,
    scoreLabel: isSsa ? "Team SSA %" : "PL score",
    scoreValue: isSsa
      ? `${rec.ssaCompletionPercent}%`
      : `${rec.overallProgramLeadScore}`,
    stats: isSsa
      ? [
          { label: "SSA done", value: `${rec.ssaCompletionPercent}%` },
          { label: "Team target", value: `${rec.teamTargetAchievement}%` },
          { label: "Core schools", value: `${rec.coreSchoolProgressPercent}%` },
        ]
      : [
          { label: "Team target", value: `${rec.teamTargetAchievement}%` },
          { label: "Staff on track", value: `${rec.staffOnTrackPercent}%` },
          { label: "Verification", value: `${rec.verificationPassRate}%` },
        ],
    tone,
  };
}

function cdTile(
  rec: CountryDirectorRecord,
  roleLabel: string,
  tone: BestPerformerTone,
): BestPerformerTile {
  return {
    key: `cd-${rec.country}`,
    kind: "cd",
    roleLabel,
    name: rec.directorName,
    initials: rec.initials,
    context: `${rec.country} · ${rec.schools} schools`,
    badge: rec.rank === 1 ? "Top Country Director" : "Country Performance Leader",
    scoreLabel: "CD score",
    scoreValue: `${rec.directorScore}`,
    stats: [
      { label: "Monthly target", value: `${rec.monthlyTargetPct}%` },
      { label: "Valid visits", value: `${rec.validVisitPct}%` },
      { label: "SSA done", value: `${rec.ssaCompletedPct}%` },
    ],
    tone,
  };
}

function mostImprovedTile(
  roleLabel: string,
  tone: BestPerformerTone,
): BestPerformerTile | null {
  const top = mostImprovedStaff[0];
  if (!top) return null;
  return {
    key: `improved-${top.staffId}`,
    kind: "improved",
    roleLabel,
    name: top.staffName,
    initials: initialsOf(top.staffName),
    context: `Biggest month-over-month gain · ${top.category}`,
    badge: "Fastest Catch-Up",
    scoreLabel: "MoM gain",
    scoreValue: `+${top.improvementPoints} pts`,
    stats: mostImprovedStaff.slice(0, 3).map((r) => ({
      label: r.staffName.split(/\s+/)[0],
      value: `+${r.improvementPoints}`,
    })),
    tone,
  };
}

// Role-gated recognition panel. The signed-in `user` is only consulted for
// the Program Lead view (to resolve "their team"); other audiences are
// country/region-wide and ignore it.
export function bestPerformersFor(
  audience: BestPerformersAudience,
  user?: CurrentUser,
): BestPerformersPanel {
  switch (audience) {
    case "cpl": {
      const plId = programLeadIdForUser(user);
      const ownTeam = overallMonthlyLeaders.filter(
        (r) => r.programLeadId === plId,
      );
      const otherTeams = overallMonthlyLeaders.filter(
        (r) => r.programLeadId !== plId,
      );
      const tiles: BestPerformerTile[] = [];
      if (ownTeam[0]) {
        tiles.push(cceoOverallTile(ownTeam[0], "Your Team's top CCEO", "amber"));
      }
      if (otherTeams[0]) {
        tiles.push(cceoOverallTile(otherTeams[0], "Top CCEO · other teams", "sky"));
      }
      return {
        title: "Best performing — your team",
        subtitle:
          "Your strongest verified performer, and the CCEO setting the pace on other teams.",
        tiles,
      };
    }
    case "cd": {
      const tiles: BestPerformerTile[] = [];
      const bestPl = programLeadLeaderboard[0];
      const bestCceo = overallMonthlyLeaders[0];
      const ssaCceo = calculateCategoryLeaderboard("SSA")[0];
      const ssaPl = [...programLeadLeaderboard].sort(
        (a, b) => b.ssaCompletionPercent - a.ssaCompletionPercent,
      )[0];
      if (bestPl) tiles.push(plTile(bestPl, "Best Program Lead", "violet", "overall"));
      if (bestCceo) tiles.push(cceoOverallTile(bestCceo, "Best CCEO", "amber"));
      if (ssaCceo) tiles.push(cceoSsaTile(ssaCceo, "SSA leader · CCEO", "emerald"));
      if (ssaPl) tiles.push(plTile(ssaPl, "SSA leader · Program Lead", "sky", "ssa"));
      return {
        title: "Best performing — country",
        subtitle:
          "Top Program Lead and CCEO this month, plus who leads SSA across both layers.",
        tiles,
      };
    }
    case "rvp": {
      const tiles: BestPerformerTile[] = [];
      const bestCd = countryDirectorLeaderboard[0];
      const bestPl = programLeadLeaderboard[0];
      const bestCceo = overallMonthlyLeaders[0];
      if (bestCd) tiles.push(cdTile(bestCd, "Best Country Director", "emerald"));
      if (bestPl) tiles.push(plTile(bestPl, "Best Program Lead", "violet", "overall"));
      if (bestCceo) {
        tiles.push(cceoOverallTile(bestCceo, "Best CCEO · top field staff", "amber"));
      }
      return {
        title: "Best performing — region",
        subtitle:
          "The standout in each layer of the region this month — verified work only.",
        tiles,
      };
    }
    case "hr": {
      const tiles: BestPerformerTile[] = [];
      const bestPl = programLeadLeaderboard[0];
      const improved = mostImprovedTile("Most improved staff", "sky");
      if (bestPl) {
        tiles.push(plTile(bestPl, "Best team · Program Lead", "violet", "overall"));
      }
      if (improved) tiles.push(improved);
      return {
        title: "Best performing & most improved",
        subtitle:
          "Team recognition and the staff making the biggest month-over-month gains.",
        tiles,
      };
    }
  }
}
