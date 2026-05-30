// Core School Dashboard — mock data + engine.
//
// Core Schools require 4 visits + 4 trainings per FY, delivered by staff or
// CERTIFIED partners (non-certified partner visits do not count as valid).
// The engine derives package status, SSA performance, attention list, and
// Champion School recommendations. Champion conversion is recommendation
// only — Program Lead / Country Director must approve.

import type { CurrentUser } from "./schools-mock";
import { ENGINE_TODAY } from "./refresh-and-followup-mock";

export type CoreSsaStatus =
  | "SSA Current"
  | "SSA Needed"
  | "SSA Scheduled"
  | "SSA Completed"
  | "SSA Verified"
  | "SSA Overdue";

export type CorePackageStatus =
  | "Not Started"
  | "Started"
  | "Halfway Supported"
  | "Nearly Complete"
  | "Package Complete"
  | "Behind Schedule"
  | "Critical Gap";

export type ChampionStatus =
  | "Not Eligible"
  | "Potential Champion"
  | "Champion Review Required"
  | "Recommended as Champion"
  | "Approved Champion School";

export type CoreSchoolRow = {
  schoolId: string;
  schoolName: string;
  schoolType: "Core";
  region: string;
  district: string;
  cluster: string;
  assignedCceoId: string;
  assignedCceoName: string;
  assignedPartnerName?: string;
  partnerCertified?: boolean;

  latestSsaDate?: string;
  latestVerifiedSsaAverage?: number;
  ssaStatus: CoreSsaStatus;

  staffVisitsCompleted: number;
  partnerVisitsCompleted: number;
  staffTrainingsCompleted: number;
  partnerTrainingsCompleted: number;

  // Derived
  visitsCompleted: number;
  trainingsCompleted: number;

  lowestIntervention?: string;
  bestIntervention?: string;
  riskReasons: string[];
  recommendedNextAction: string;

  packageStatus: CorePackageStatus;
  championStatus: ChampionStatus;

  yoyImprovement?: number; // points vs previous FY
  salesforceCompliance: "Complete" | "Partial" | "Missing";
  evidenceStatus: "Verified" | "Pending" | "Not Submitted";
};

// Helper: count valid visits/trainings per the certification rule.
function countValid(staff: number, partner: number, partnerCertified: boolean | undefined): number {
  return staff + (partnerCertified ? partner : 0);
}

function calculateCorePackageStatus(args: {
  visits: number;
  trainings: number;
  todayMonthOfFy?: number;
}): CorePackageStatus {
  const { visits, trainings } = args;
  if (visits === 0 && trainings === 0) return "Not Started";

  let baseline: CorePackageStatus = "Started";
  if (visits >= 1 && trainings >= 1) baseline = "Started";
  if (visits >= 2 && trainings >= 2) baseline = "Halfway Supported";
  if (visits >= 3 && trainings >= 3) baseline = "Nearly Complete";
  if (visits >= 4 && trainings >= 4) baseline = "Package Complete";

  if (baseline === "Package Complete") return baseline;

  // Pacing: expected progress based on FY month (Oct = 1)
  const m = args.todayMonthOfFy ?? currentFyMonth();
  const expected = m / 12;
  const actual = (visits / 4 + trainings / 4) / 2;
  const tolerance = 0.15;
  if (actual < expected - tolerance) return "Behind Schedule";
  return baseline;
}

function currentFyMonth(today: Date = ENGINE_TODAY): number {
  const m = today.getMonth(); // 0–11
  // Oct = 1, Nov = 2, …, Sep = 12
  return ((m - 9 + 12) % 12) + 1;
}

function recommendChampionSchool(args: {
  schoolType: "Core";
  latestVerifiedSsaAverage?: number;
  visits: number;
  trainings: number;
  salesforceCompliance: CoreSchoolRow["salesforceCompliance"];
  evidenceStatus: CoreSchoolRow["evidenceStatus"];
  yoyImprovement?: number;
}): ChampionStatus {
  if (
    args.schoolType === "Core" &&
    (args.latestVerifiedSsaAverage ?? 0) >= 8.0 &&
    args.visits >= 4 &&
    args.trainings >= 4 &&
    args.salesforceCompliance === "Complete" &&
    args.evidenceStatus === "Verified" &&
    (args.yoyImprovement ?? 0) > 0
  ) {
    return "Recommended as Champion";
  }
  if ((args.latestVerifiedSsaAverage ?? 0) >= 7.5 && args.visits >= 3 && args.trainings >= 3) {
    return "Potential Champion";
  }
  return "Not Eligible";
}

// Seed: 9 Core Schools spanning all package + champion combinations.
const seed: Omit<CoreSchoolRow, "visitsCompleted" | "trainingsCompleted" | "packageStatus" | "championStatus">[] = [
  {
    schoolId: "CS-001", schoolName: "Mountain View Core", schoolType: "Core",
    region: "North", district: "Central",  cluster: "Kampala North",
    assignedCceoId: "STF-DM-014", assignedCceoName: "Daniel Mwangi",
    assignedPartnerName: "World Vision", partnerCertified: true,
    latestSsaDate: "2025-10-12", latestVerifiedSsaAverage: 8.4, ssaStatus: "SSA Verified",
    staffVisitsCompleted: 3, partnerVisitsCompleted: 1, staffTrainingsCompleted: 2, partnerTrainingsCompleted: 2,
    lowestIntervention: "Fees / Budget / Accounts", bestIntervention: "Christ-like Behavior",
    riskReasons: [], recommendedNextAction: "Review for Champion School",
    yoyImprovement: 0.6, salesforceCompliance: "Complete", evidenceStatus: "Verified",
  },
  {
    schoolId: "CS-002", schoolName: "Hillside Core P/S", schoolType: "Core",
    region: "North", district: "Cluster", cluster: "Mukono Cluster",
    assignedCceoId: "STF-DM-014", assignedCceoName: "Daniel Mwangi",
    assignedPartnerName: "Compassion International", partnerCertified: true,
    latestSsaDate: "2025-09-30", latestVerifiedSsaAverage: 7.6, ssaStatus: "SSA Current",
    staffVisitsCompleted: 2, partnerVisitsCompleted: 1, staffTrainingsCompleted: 2, partnerTrainingsCompleted: 1,
    lowestIntervention: "Government Requirements", bestIntervention: "Enrollment",
    riskReasons: [], recommendedNextAction: "Schedule next visit + verify Salesforce",
    yoyImprovement: 0.3, salesforceCompliance: "Partial", evidenceStatus: "Pending",
  },
  {
    schoolId: "CS-003", schoolName: "Riverside Core Junior", schoolType: "Core",
    region: "North", district: "Cluster", cluster: "Mukono Cluster",
    assignedCceoId: "STF-DM-014", assignedCceoName: "Daniel Mwangi",
    partnerCertified: false,
    latestSsaDate: "2025-04-20", latestVerifiedSsaAverage: 6.4, ssaStatus: "SSA Needed",
    staffVisitsCompleted: 1, partnerVisitsCompleted: 0, staffTrainingsCompleted: 1, partnerTrainingsCompleted: 0,
    lowestIntervention: "Teaching Environment", bestIntervention: "Word of God",
    riskReasons: ["SSA outdated", "Behind on package"], recommendedNextAction: "Complete SSA + schedule visit",
    yoyImprovement: -0.1, salesforceCompliance: "Partial", evidenceStatus: "Pending",
  },
  {
    schoolId: "CS-004", schoolName: "Sunrise Core P/S", schoolType: "Core",
    region: "North", district: "East", cluster: "Jinja Hub",
    assignedCceoId: "STF-DM-014", assignedCceoName: "Daniel Mwangi",
    assignedPartnerName: "Teach Beyond", partnerCertified: true,
    latestSsaDate: "2025-11-02", latestVerifiedSsaAverage: 7.9, ssaStatus: "SSA Verified",
    staffVisitsCompleted: 4, partnerVisitsCompleted: 0, staffTrainingsCompleted: 3, partnerTrainingsCompleted: 1,
    lowestIntervention: "Fees / Budget / Accounts", bestIntervention: "Leadership Best Practice",
    riskReasons: [], recommendedNextAction: "Verify Salesforce + Champion review",
    yoyImprovement: 0.4, salesforceCompliance: "Complete", evidenceStatus: "Verified",
  },
  {
    schoolId: "CS-005", schoolName: "Bright Core P/S", schoolType: "Core",
    region: "Central", district: "Central", cluster: "Kampala Central",
    assignedCceoId: "STF-GN-007", assignedCceoName: "Grace Nansubuga",
    assignedPartnerName: "ACSI", partnerCertified: true,
    latestSsaDate: "2025-10-18", latestVerifiedSsaAverage: 8.1, ssaStatus: "SSA Verified",
    staffVisitsCompleted: 2, partnerVisitsCompleted: 2, staffTrainingsCompleted: 2, partnerTrainingsCompleted: 2,
    lowestIntervention: "Government Requirements", bestIntervention: "Christ-like Behavior",
    riskReasons: [], recommendedNextAction: "Continue cadence",
    yoyImprovement: 0.5, salesforceCompliance: "Complete", evidenceStatus: "Verified",
  },
  {
    schoolId: "CS-006", schoolName: "Lamwo Core East", schoolType: "Core",
    region: "Central", district: "Cluster", cluster: "Lamwo East",
    assignedCceoId: "STF-PO-008", assignedCceoName: "Peter Ochieng",
    partnerCertified: false,
    latestSsaDate: undefined, latestVerifiedSsaAverage: undefined, ssaStatus: "SSA Needed",
    staffVisitsCompleted: 0, partnerVisitsCompleted: 0, staffTrainingsCompleted: 0, partnerTrainingsCompleted: 0,
    lowestIntervention: "—", bestIntervention: "—",
    riskReasons: ["No SSA on record", "0 visits", "0 trainings"], recommendedNextAction: "Complete SSA + start visits",
    yoyImprovement: undefined, salesforceCompliance: "Missing", evidenceStatus: "Not Submitted",
  },
  {
    schoolId: "CS-007", schoolName: "Agago Core Hub", schoolType: "Core",
    region: "Central", district: "Cluster", cluster: "Agago Hub",
    assignedCceoId: "STF-PO-008", assignedCceoName: "Peter Ochieng",
    assignedPartnerName: "UCU", partnerCertified: true,
    latestSsaDate: "2025-09-15", latestVerifiedSsaAverage: 7.2, ssaStatus: "SSA Current",
    staffVisitsCompleted: 1, partnerVisitsCompleted: 1, staffTrainingsCompleted: 1, partnerTrainingsCompleted: 0,
    lowestIntervention: "Learning Environment", bestIntervention: "Enrollment",
    riskReasons: ["Below pacing"], recommendedNextAction: "Schedule training + visit",
    yoyImprovement: 0.2, salesforceCompliance: "Partial", evidenceStatus: "Pending",
  },
  {
    schoolId: "CS-008", schoolName: "Gulu Core Municipality", schoolType: "Core",
    region: "East", district: "Cluster", cluster: "Gulu Municipality",
    assignedCceoId: "STF-SN-009", assignedCceoName: "Sarah Namutebi",
    assignedPartnerName: "World Vision", partnerCertified: true,
    latestSsaDate: "2025-10-25", latestVerifiedSsaAverage: 8.6, ssaStatus: "SSA Verified",
    staffVisitsCompleted: 4, partnerVisitsCompleted: 0, staffTrainingsCompleted: 4, partnerTrainingsCompleted: 0,
    lowestIntervention: "Fees / Budget / Accounts", bestIntervention: "Word of God",
    riskReasons: [], recommendedNextAction: "Recommend as Champion School",
    yoyImprovement: 0.7, salesforceCompliance: "Complete", evidenceStatus: "Verified",
  },
  {
    schoolId: "CS-009", schoolName: "Omoro Core West", schoolType: "Core",
    region: "East", district: "West", cluster: "Omoro West",
    assignedCceoId: "STF-SN-009", assignedCceoName: "Sarah Namutebi",
    partnerCertified: false,
    latestSsaDate: "2025-08-30", latestVerifiedSsaAverage: 5.8, ssaStatus: "SSA Needed",
    staffVisitsCompleted: 1, partnerVisitsCompleted: 0, staffTrainingsCompleted: 0, partnerTrainingsCompleted: 0,
    lowestIntervention: "Teaching Environment", bestIntervention: "Christ-like Behavior",
    riskReasons: ["Lowest SSA in cohort", "0 trainings"], recommendedNextAction: "Urgent training + complete SSA",
    yoyImprovement: -0.3, salesforceCompliance: "Missing", evidenceStatus: "Not Submitted",
  },
];

export const coreSchools: CoreSchoolRow[] = seed.map((s) => {
  const visits = countValid(s.staffVisitsCompleted, s.partnerVisitsCompleted, s.partnerCertified);
  const trainings = countValid(s.staffTrainingsCompleted, s.partnerTrainingsCompleted, s.partnerCertified);
  const packageStatus = calculateCorePackageStatus({ visits, trainings });
  const championStatus = recommendChampionSchool({
    schoolType: "Core",
    latestVerifiedSsaAverage: s.latestVerifiedSsaAverage,
    visits, trainings,
    salesforceCompliance: s.salesforceCompliance,
    evidenceStatus: s.evidenceStatus,
    yoyImprovement: s.yoyImprovement,
  });
  return { ...s, visitsCompleted: visits, trainingsCompleted: trainings, packageStatus, championStatus };
});

// ────────── Role-aware visibility ──────────

export function filterCoreSchoolsByUserRole(user: CurrentUser): CoreSchoolRow[] {
  if (user.role === "Admin") return coreSchools;
  if (user.role === "CountryDirector") return coreSchools;
  if (user.role === "CountryProgramLead") return coreSchools; // demo: supervises all CCEOs
  if (user.role === "ImpactAssessment" || user.role === "ProgramAccountant") return coreSchools;
  // CCEO: only own assigned
  return coreSchools.filter((s) => s.assignedCceoId === user.staffId);
}

// ────────── Aggregations ──────────

export type CorePackageSummary = {
  totalCoreSchools: number;
  coreSchoolsAssessed: number;
  coreSchoolsNotAssessed: number;
  coreSchoolsWithZeroSsa: number;
  coreSchoolsWithZeroVisits: number;
  coreSchoolsWithZeroTraining: number;
  coreSchoolsWithOneVisitOneTraining: number;
  coreSchoolsWithTwoVisitsTwoTrainings: number;
  coreSchoolsWithThreeVisitsThreeTrainings: number;
  coreSchoolsWithFourVisitsFourTrainings: number;
  packageComplete: number;
  behindSchedule: number;
  potentialChampions: number;
  averageSsa: number;
  bestIntervention: string;
  lowestIntervention: string;
};

export function summarizeCore(schools: CoreSchoolRow[]): CorePackageSummary {
  const total = schools.length;
  const assessed = schools.filter((s) => s.latestSsaDate).length;
  const ssaScores = schools
    .map((s) => s.latestVerifiedSsaAverage)
    .filter((v): v is number => typeof v === "number");
  const avg = ssaScores.length
    ? Math.round((ssaScores.reduce((a, b) => a + b, 0) / ssaScores.length) * 100) / 100
    : 0;
  return {
    totalCoreSchools: total,
    coreSchoolsAssessed: assessed,
    coreSchoolsNotAssessed: total - assessed,
    coreSchoolsWithZeroSsa: schools.filter((s) => !s.latestSsaDate).length,
    coreSchoolsWithZeroVisits: schools.filter((s) => s.visitsCompleted === 0).length,
    coreSchoolsWithZeroTraining: schools.filter((s) => s.trainingsCompleted === 0).length,
    coreSchoolsWithOneVisitOneTraining: schools.filter((s) => s.visitsCompleted >= 1 && s.trainingsCompleted >= 1 && (s.visitsCompleted < 2 || s.trainingsCompleted < 2)).length,
    coreSchoolsWithTwoVisitsTwoTrainings: schools.filter((s) => s.visitsCompleted >= 2 && s.trainingsCompleted >= 2 && (s.visitsCompleted < 3 || s.trainingsCompleted < 3)).length,
    coreSchoolsWithThreeVisitsThreeTrainings: schools.filter((s) => s.visitsCompleted >= 3 && s.trainingsCompleted >= 3 && (s.visitsCompleted < 4 || s.trainingsCompleted < 4)).length,
    coreSchoolsWithFourVisitsFourTrainings: schools.filter((s) => s.visitsCompleted >= 4 && s.trainingsCompleted >= 4).length,
    packageComplete: schools.filter((s) => s.packageStatus === "Package Complete").length,
    behindSchedule: schools.filter((s) => s.packageStatus === "Behind Schedule").length,
    potentialChampions: schools.filter((s) => s.championStatus === "Potential Champion" || s.championStatus === "Recommended as Champion").length,
    averageSsa: avg,
    bestIntervention: "Christ-like Behavior",
    lowestIntervention: "Fees / Budget / Accounts",
  };
}

// Best performing — verified SSA + complete package + improvement
export function rankBestPerformingCoreSchools(schools: CoreSchoolRow[]): CoreSchoolRow[] {
  return [...schools].sort((a, b) => {
    const score = (s: CoreSchoolRow) =>
      (s.latestVerifiedSsaAverage ?? 0) * 10 +
      (s.visitsCompleted + s.trainingsCompleted) +
      (s.yoyImprovement ?? 0) * 5;
    return score(b) - score(a);
  });
}

// Attention list — low SSA, 0 visits/training, behind pacing, missing evidence
export function detectCoreSchoolsNeedingAttention(schools: CoreSchoolRow[]): CoreSchoolRow[] {
  return schools
    .filter((s) =>
      s.ssaStatus === "SSA Needed" ||
      s.visitsCompleted === 0 ||
      s.trainingsCompleted === 0 ||
      s.packageStatus === "Behind Schedule" ||
      s.packageStatus === "Critical Gap" ||
      s.evidenceStatus !== "Verified",
    )
    .sort((a, b) => {
      const r = (s: CoreSchoolRow) =>
        (s.latestVerifiedSsaAverage ?? 0) -
        (s.packageStatus === "Behind Schedule" ? 2 : 0);
      return r(a) - r(b);
    });
}

// Year-over-year intervention comparison for the dashboard's YoY card.
export type InterventionYoy = { intervention: string; prior: number; current: number; change: number };
export const interventionYoy: InterventionYoy[] = [
  { intervention: "Christ-like Behavior",        prior: 7.2, current: 7.8, change: 0.6 },
  { intervention: "Exposure to the Word of God", prior: 7.5, current: 8.1, change: 0.6 },
  { intervention: "Fees / Budget / Accounts",    prior: 6.4, current: 6.9, change: 0.5 },
  { intervention: "Government Requirements",     prior: 6.7, current: 7.0, change: 0.3 },
  { intervention: "Leadership Best Practice",    prior: 7.1, current: 7.6, change: 0.5 },
  { intervention: "Learning Environment",        prior: 7.3, current: 7.7, change: 0.4 },
  { intervention: "Teaching Environment",        prior: 7.0, current: 7.4, change: 0.4 },
  { intervention: "Enrollment",                  prior: 6.8, current: 7.2, change: 0.4 },
];

// ────────── Hero ("What Changed") + Quick Actions ──────────
//
// Greeting + chip values are derived in the page from the live summary so
// the hero never drifts from the KPI strip. The static defaults below act
// as a fallback if a caller renders the hero outside the page (e.g., on a
// demo storyboard).

export type CoreHeroChip = {
  label:   string;
  value:   string;
  tone:    "good" | "warn" | "info";
};

export const coreHeroDefaults = {
  greeting: "Good morning",
  primaryCta:   { label: "Plan Your Week",         href: "/planning" },
  secondaryCta: { label: "Open Champion Reviews",  href: "/ssa/core-candidates" },
};

export type CoreQuickAction = {
  key:     string;
  title:   string;
  count:   number | string;
  caption: string;
  icon:    "clipboardList" | "calendar" | "footprints" | "shieldCheck" | "trophy" | "fileText";
  href:    string;
  tone:    "edify" | "amber" | "violet" | "blue" | "red" | "green";
};

export const coreQuickActions: CoreQuickAction[] = [
  { key: "plan_visit",       title: "Plan Next Visit",       count: 8,      caption: "schools below the package bar", icon: "calendar",      href: "/planning",            tone: "edify"  },
  { key: "schedule_training",title: "Schedule Training",     count: 5,      caption: "cohorts without trainer",       icon: "clipboardList", href: "/trainings",           tone: "amber"  },
  { key: "review_champions", title: "Review Champion Candidate", count: 4,  caption: "ready for Champion review",    icon: "trophy",        href: "/ssa/core-candidates", tone: "green"  },
  { key: "log_visit",        title: "Log Visit Today",       count: 3,      caption: "scheduled today",               icon: "footprints",    href: "/trainings",           tone: "blue"   },
  { key: "open_ssa",         title: "Open SSA Form",         count: 6,      caption: "no SSA this FY",                icon: "shieldCheck",   href: "/ssa",                 tone: "red"    },
  { key: "send_debrief",     title: "Send Daily Debrief",    count: "Due",  caption: "today",                         icon: "fileText",      href: "/field-intelligence",  tone: "violet" },
];

// "Remaining tasks" rollup so dashboards stop nagging about completed basics.
export function remainingCorePackageTasks(schools: CoreSchoolRow[]) {
  let needMoreVisits = 0;
  let needMoreTrainings = 0;
  let needFinalVerification = 0;
  for (const s of schools) {
    if (s.visitsCompleted < 4) needMoreVisits++;
    if (s.trainingsCompleted < 4) needMoreTrainings++;
    if (s.packageStatus !== "Package Complete" || s.evidenceStatus !== "Verified") needFinalVerification++;
  }
  return { needMoreVisits, needMoreTrainings, needFinalVerification };
}
