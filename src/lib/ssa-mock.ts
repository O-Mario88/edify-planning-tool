// SSA Performance Dashboard — mock data + recommendation engine.
//
// CONTRACT: SSA is not display-only. The same engine that powers this
// dashboard creates the staff verification todos, validates the verified
// SSA Verification ID, recalculates the verified average, flags Potential
// Core Schools, and queues October onboarding recommendations.
//
// Threshold rule (per product doc):
//   school.schoolType === "Client"
//   && all 8 SSA intervention scores present
//   && average >= 7.5
//   ⇒ verification required → on verification, Potential Core School
//   ⇒ recommend October onboarding (October = month 1 of FY)

// ────────── Portfolio self-verification (the 10% quota) ──────────
// The "every CCEO/PL self-verifies 10% of their Client schools" feature lives
// in src/lib/verification; re-exported here so the existing card + staff page +
// CPL home (which import from @/lib/ssa-mock) resolve. Client-safe.
export {
  CLIENT_SSA_VERIFICATION_RATE,
  rollupPortfolioVerification as clientVerificationRollup,
  type ClientVerificationProgress,
} from "@/lib/verification/portfolio-verification";
export {
  clientVerificationProgress,
  getClientVerificationFor,
} from "@/lib/verification/portfolio-verification-mock";

// ────────── Intervention areas (the 8) ──────────

export const SSA_EIGHT = [
  "Christ-like Behavior",
  "Exposure to the Word of God",
  "Fees / Budget / Accounts",
  "Government Requirements",
  "Leadership Best Practice",
  "Learning Environment",
  "Teaching Environment",
  "Enrollment",
] as const;

export type SsaInterventionLabel = typeof SSA_EIGHT[number];

// ────────── SSA record + record helpers ──────────

export type SsaStatus = "Draft" | "Completed" | "Verified" | "Returned";
export type SsaVerificationStatus =
  | "Not Required"
  | "Required"
  | "Awaiting ID"
  | "Submitted"
  | "Verified"
  | "Rejected";

export type SsaRecord = {
  ssaId: string;
  schoolId: string;
  schoolTypeAtAssessment: "Client" | "Core" | "New";
  assessmentDate: string;
  assessedByStaffId: string;
  christLikeBehavior?: number;
  exposureToWordOfGod?: number;
  feesBudgetAccounts?: number;
  governmentRequirements?: number;
  leadershipBestPractice?: number;
  learningEnvironment?: number;
  teachingEnvironment?: number;
  enrollment?: number;
  averageScore?: number;
  status: SsaStatus;
  verificationStatus: SsaVerificationStatus;
  verificationId?: string;
  verifiedSsaId?: string;
  verifiedAverageScore?: number;
};

// Mirrors the prompt's reference logic exactly. Returns the next-step
// recommendation for a (school, latestSsa) pair — the staff dashboard, the
// Core Candidate Queue, and the engine's todo creator all consume this.
export type CoreSchoolEvaluation =
  | null
  | { type: "SSA_INCOMPLETE"; label: string; priority: "Medium" }
  | {
      type: "SSA_VERIFICATION_REQUIRED";
      label: "SSA Verification Required";
      priority: "High";
      reason: string;
      createStaffTodo: true;
      averageScore: number;
    }
  | {
      type: "POTENTIAL_CORE_SCHOOL";
      label: "Potential Core School";
      priority: "High";
      reason: string;
      recommendOctoberOnboarding: true;
      verifiedAverageScore: number;
    };

export function calculateSsaAverage(s: SsaRecord): number | null {
  const required = [
    s.christLikeBehavior,
    s.exposureToWordOfGod,
    s.feesBudgetAccounts,
    s.governmentRequirements,
    s.leadershipBestPractice,
    s.learningEnvironment,
    s.teachingEnvironment,
    s.enrollment,
  ];
  if (required.some((v) => typeof v !== "number")) return null;
  const total = (required as number[]).reduce((a, b) => a + b, 0);
  return Math.round((total / required.length) * 100) / 100;
}

export function validateEightInterventionScores(s: SsaRecord): boolean {
  return calculateSsaAverage(s) !== null;
}

export function evaluateCoreSchoolPotential(
  school: { schoolId: string; schoolType: "Client" | "Core" | "New" },
  latestSsa: SsaRecord | null,
): CoreSchoolEvaluation {
  if (school.schoolType !== "Client") return null;
  if (!latestSsa || latestSsa.status === "Draft" || latestSsa.status === "Returned") {
    return {
      type: "SSA_INCOMPLETE",
      label: "SSA Required Before Core Potential Review",
      priority: "Medium",
    };
  }
  const avg = calculateSsaAverage(latestSsa);
  if (avg === null) {
    return {
      type: "SSA_INCOMPLETE",
      label: "SSA Incomplete — Verification Not Ready",
      priority: "Medium",
    };
  }
  if (avg >= 7.5 && latestSsa.verificationStatus !== "Verified") {
    return {
      type: "SSA_VERIFICATION_REQUIRED",
      label: "SSA Verification Required",
      priority: "High",
      reason:
        "Client school average SSA score is 7.5+ across all 8 interventions.",
      createStaffTodo: true,
      averageScore: avg,
    };
  }
  if (avg >= 7.5 && latestSsa.verificationStatus === "Verified") {
    const verifiedAvg = latestSsa.verifiedAverageScore ?? avg;
    if (verifiedAvg >= 7.5) {
      return {
        type: "POTENTIAL_CORE_SCHOOL",
        label: "Potential Core School",
        priority: "High",
        reason:
          "Verified SSA average remains 7.5+ across all 8 interventions.",
        recommendOctoberOnboarding: true,
        verifiedAverageScore: verifiedAvg,
      };
    }
  }
  return null;
}

// Confirm a staff-supplied SSA Verification ID against an open todo. Returns
// the new state. The backend would also write to the SSA record and create
// the October onboarding recommendation when verifiedAverage >= 7.5.
export function confirmSsaVerificationId(args: {
  todoId: string;
  ssaVerificationId: string;
  verifiedSsaRecord: SsaRecord; // freshly verified record from the field
}): {
  ok: boolean;
  todoStatus: "Submitted for Review" | "Verified" | "Closed";
  flag: "Potential Core School" | "Verified — Not Core Ready";
  october?: { recommendedMonth: "October"; recommendedFinancialYear: string };
  message: string;
} {
  if (!args.ssaVerificationId.trim()) {
    return {
      ok: false,
      todoStatus: "Submitted for Review",
      flag: "Verified — Not Core Ready",
      message: "SSA Verification ID is required.",
    };
  }
  const verifiedAvg =
    args.verifiedSsaRecord.verifiedAverageScore ??
    calculateSsaAverage(args.verifiedSsaRecord) ??
    0;
  if (verifiedAvg >= 7.5) {
    return {
      ok: true,
      todoStatus: "Verified",
      flag: "Potential Core School",
      october: {
        recommendedMonth: "October",
        recommendedFinancialYear: nextOctoberFinancialYear(),
      },
      message: "Flagged as Potential Core School. Recommended for October onboarding.",
    };
  }
  return {
    ok: true,
    todoStatus: "Closed",
    flag: "Verified — Not Core Ready",
    message: "Verified SSA average below 7.5 threshold.",
  };
}

// Financial Year = October → September. The next October FY is the FY whose
// month-1 starts on the next 1 October.
export function nextOctoberFinancialYear(today: Date = new Date()): string {
  const y = today.getFullYear();
  const fyStart = today.getMonth() >= 9 ? y : y; // FY rolls over on Oct 1
  // FY label: "FY YYYY/YY+1" where the second part is the calendar year
  // following the October start.
  const startYear = today.getMonth() >= 9 ? y : y; // either way the next Oct
  void fyStart;
  return `FY ${startYear}/${String((startYear + 1) % 100).padStart(2, "0")}`;
}

// ────────── Header / filters ──────────

export const ssaHeader = {
  title: "SSA Performance",
  subtitle:
    "Track school self-assessment performance across all 8 interventions and compare district performance.",
  filters: {
    financialYear: "2024/2025",
    quarter: "Q3 (Apr–Jun 2025)",
    region: "North Region",
    district: "All Districts",
  },
  searchPlaceholder: "Search schools, districts…",
};

export const ssaUser = { name: "Sarah Mwangi", initials: "SM", role: "Country M&E" };
export const ssaNotificationCount = 3;

// ────────── KPI row ──────────

export type SsaKpi = {
  key: string;
  label: string;
  value: string;
  unit?: string;
  caption?: string;
  trend?: { delta: string; tone: "up" | "down" };
  icon: "school" | "checkCircle" | "users" | "star" | "alertTriangle" | "building";
  iconTone: "edify" | "emerald" | "amber" | "rose" | "violet";
};

export const ssaKpis: SsaKpi[] = [
  { key: "total",        label: "Total Schools Assessed",  value: "1,024", caption: "of 1,132 schools · 90.5% of total", icon: "school",        iconTone: "edify"   },
  { key: "completion",   label: "SSA Completion Rate",     value: "90.5",  unit: "%",     trend: { delta: "6.8pp vs Q3", tone: "up"   }, icon: "checkCircle",   iconTone: "emerald" },
  { key: "districts",    label: "Districts Reporting",     value: "6",     caption: "of 6 districts · 100%",             icon: "users",          iconTone: "edify"   },
  { key: "avg",          label: "Average SSA Score",       value: "6.42",  unit: "/ 10",  trend: { delta: "0.48 vs Q3",  tone: "up"   }, icon: "star",           iconTone: "amber"   },
  { key: "high_risk",    label: "High Risk Schools",       value: "112",   caption: "10.9% of assessed",                  icon: "alertTriangle", iconTone: "rose"    },
  { key: "below_thresh", label: "Districts Below Threshold", value: "2",  caption: "Below 6.0 average",                  icon: "building",      iconTone: "rose"    },
];

// ────────── 8 intervention performance ──────────

export type InterventionRow = {
  rank: number;
  label: SsaInterventionLabel;
  score: number; // out of 10
  performance: "High" | "Medium" | "Low";
};

export const interventionScores: InterventionRow[] = [
  { rank: 1, label: "Christ-like Behavior",        score: 7.23, performance: "High"   },
  { rank: 2, label: "Exposure to the Word of God", score: 6.95, performance: "High"   },
  { rank: 3, label: "Fees / Budget / Accounts",    score: 5.60, performance: "Medium" },
  { rank: 4, label: "Government Requirements",     score: 5.28, performance: "Medium" },
  { rank: 5, label: "Leadership Best Practice",    score: 6.72, performance: "High"   },
  { rank: 6, label: "Learning Environment",        score: 5.48, performance: "Medium" },
  { rank: 7, label: "Teaching Environment",        score: 5.17, performance: "Medium" },
  { rank: 8, label: "Enrollment",                  score: 7.01, performance: "High"   },
];

// ────────── District SSA Performance ──────────

export type PerformanceStatus = "Strong" | "Fair" | "Weak" | "Critical";

export type DistrictSsaRow = {
  rank: number;
  district: string;
  schoolsAssessed: number;
  averageScore: number;
  highestWeakness: SsaInterventionLabel;
  highRiskSchools: number;
  completionRate: number;
  trend: "up" | "down";
};

export const districtSsaPerformance: DistrictSsaRow[] = [
  { rank: 1, district: "Kitgum", schoolsAssessed: 182, averageScore: 6.86, highestWeakness: "Teaching Environment",   highRiskSchools: 14, completionRate: 94.0, trend: "up"   },
  { rank: 2, district: "Pader",  schoolsAssessed: 168, averageScore: 6.31, highestWeakness: "Government Requirements", highRiskSchools: 18, completionRate: 89.3, trend: "up"   },
  { rank: 3, district: "Lamwo",  schoolsAssessed: 159, averageScore: 6.08, highestWeakness: "Learning Environment",   highRiskSchools: 21, completionRate: 87.4, trend: "down" },
  { rank: 4, district: "Agago",  schoolsAssessed: 176, averageScore: 5.92, highestWeakness: "Fees / Budget / Accounts", highRiskSchools: 22, completionRate: 88.6, trend: "down" },
  { rank: 5, district: "Gulu",   schoolsAssessed: 189, averageScore: 6.78, highestWeakness: "Teaching Environment",   highRiskSchools: 16, completionRate: 91.5, trend: "up"   },
  { rank: 6, district: "Omoro",  schoolsAssessed: 150, averageScore: 5.71, highestWeakness: "Government Requirements", highRiskSchools: 21, completionRate: 83.3, trend: "down" },
];

export function statusForScore10(s: number): PerformanceStatus {
  if (s >= 7.5) return "Strong";
  if (s >= 6.0) return "Fair";
  if (s >= 4.5) return "Weak";
  return "Critical";
}

// ────────── Cluster SSA Performance ──────────

export type ClusterSsaRow = {
  rank: number;
  cluster: string;
  districts: string;
  schoolsAssessed: number;
  averageScore: number;
};

export const clusterSsaPerformance: ClusterSsaRow[] = [
  { rank: 1, cluster: "Kitgum North",       districts: "Kitgum",        schoolsAssessed: 64, averageScore: 7.05 },
  { rank: 2, cluster: "Pader Central",      districts: "Pader",         schoolsAssessed: 58, averageScore: 6.42 },
  { rank: 3, cluster: "Lamwo East",         districts: "Lamwo",         schoolsAssessed: 51, averageScore: 6.18 },
  { rank: 4, cluster: "Agago Hub",          districts: "Agago",         schoolsAssessed: 60, averageScore: 5.90 },
  { rank: 5, cluster: "Gulu Municipality",  districts: "Gulu",          schoolsAssessed: 72, averageScore: 6.92 },
  { rank: 6, cluster: "Omoro West",         districts: "Omoro",         schoolsAssessed: 49, averageScore: 5.62 },
];

// ────────── Intervention heatmap ──────────

export type HeatmapRow = { district: string; scores: number[]; }; // length 8 (matches SSA_EIGHT)

export const interventionHeatmap: HeatmapRow[] = [
  { district: "Kitgum", scores: [7.6, 7.2, 6.1, 5.9, 7.1, 6.3, 5.7, 7.8] },
  { district: "Pader",  scores: [7.1, 6.7, 5.6, 5.1, 6.5, 5.6, 5.3, 7.2] },
  { district: "Lamwo",  scores: [6.9, 6.3, 5.2, 4.9, 6.1, 4.8, 4.6, 6.8] },
  { district: "Agago",  scores: [6.6, 6.1, 4.7, 4.6, 5.9, 4.9, 4.5, 6.7] },
  { district: "Gulu",   scores: [7.4, 7.0, 6.0, 5.7, 6.9, 6.2, 5.5, 7.6] },
  { district: "Omoro",  scores: [6.4, 5.7, 4.8, 4.4, 5.6, 4.5, 4.2, 6.3] },
];

// ────────── District Performance heat panel (right of intervention chart) ──────────

export type DistrictHeatTile = {
  district: string;
  score: number;
  status: PerformanceStatus;
};

export const districtHeatTiles: DistrictHeatTile[] = [
  { district: "Kitgum", score: 6.86, status: "Fair" },
  { district: "Pader",  score: 6.31, status: "Fair" },
  { district: "Lamwo",  score: 6.08, status: "Fair" },
  { district: "Agago",  score: 5.92, status: "Weak" },
  { district: "Gulu",   score: 6.78, status: "Fair" },
  { district: "Omoro",  score: 5.71, status: "Weak" },
];

// ────────── Action insights ──────────

export type ActionInsight = {
  id: string;
  tone: "danger" | "warning" | "success" | "info";
  title: string;
  body: string;
  cta: string;
  href: string;
};

export const actionInsights: ActionInsight[] = [
  {
    id: "ai-below",
    tone: "danger",
    title: "Districts Below Target",
    body: "2 districts have an average score below the 6.0 target. Focus support on Agago and Omoro.",
    cta: "View district performance →",
    href: "#districts",
  },
  {
    id: "ai-needs",
    tone: "warning",
    title: "Interventions Needing Attention",
    body: "Teaching Environment (5.17) and Government Requirements (5.28) are the weakest overall. Prioritize coaching and compliance support.",
    cta: "View intervention details →",
    href: "#interventions",
  },
  {
    id: "ai-risk",
    tone: "warning",
    title: "High-Risk Schools",
    body: "112 schools are high-risk (score < 4.0 in at least one intervention). Immediate follow-up and targeted support needed.",
    cta: "View at-risk schools →",
    href: "#urgent",
  },
  {
    id: "ai-positive",
    tone: "success",
    title: "Positive Momentum",
    body: "Overall SSA score improved by 0.48 points vs Q3. Continue strengthening best-performing areas.",
    cta: "View trend analysis →",
    href: "#trend",
  },
];

// ────────── Schools Requiring Urgent Attention (intervention-driven) ──────────

export type UrgentInterventionSchool = {
  rank: number;
  school: string;
  district: string;
  lowestIntervention: SsaInterventionLabel;
  lowestScore: number;
  recommendedAction: string;
  riskStatus: "Critical" | "High" | "Medium";
};

export const urgentInterventionSchools: UrgentInterventionSchool[] = [
  { rank: 1, school: "Bright Future P/S",   district: "Lamwo", lowestIntervention: "Teaching Environment",   lowestScore: 3.2, recommendedAction: "On-site Coaching + Follow-up Visit", riskStatus: "Critical" },
  { rank: 2, school: "Hope Academy P/S",    district: "Agago", lowestIntervention: "Government Requirements", lowestScore: 3.4, recommendedAction: "Compliance Support + Monitoring",   riskStatus: "Critical" },
  { rank: 3, school: "Unity Primary School", district: "Omoro", lowestIntervention: "Fees / Budget / Accounts", lowestScore: 3.6, recommendedAction: "Financial Management Support",     riskStatus: "High"     },
  { rank: 4, school: "St. Peter's P/S",     district: "Agago", lowestIntervention: "Learning Environment",   lowestScore: 3.7, recommendedAction: "Learning Materials & Environment Support", riskStatus: "High" },
  { rank: 5, school: "Light of Grace P/S",  district: "Lamwo", lowestIntervention: "Teaching Environment",   lowestScore: 3.8, recommendedAction: "Teacher Coaching + Mentoring",       riskStatus: "High"     },
];

// ────────── Quarterly trend ──────────

// FY runs Oct → Sep: Q1 Oct–Dec · Q2 Jan–Mar · Q3 Apr–Jun · Q4 Jul–Sep.
export const ssaQuarterlyTrend = [
  { q: "Q4 (Jul–Sep 2023)", score: 5.42 },
  { q: "Q1 (Oct–Dec 2023)", score: 5.68 },
  { q: "Q2 (Jan–Mar 2024)", score: 5.81 },
  { q: "Q3 (Apr–Jun 2024)", score: 6.02 },
  { q: "Q4 (Jul–Sep 2024)", score: 6.11 },
  { q: "Q1 (Oct–Dec 2024)", score: 6.18 },
  { q: "Q2 (Jan–Mar 2025)", score: 5.94 },
  { q: "Q3 (Apr–Jun 2025)", score: 6.42 },
];

export const ssaTrendTarget = 6.0;

// ────────── Core School Candidate workflow ──────────

export type CoreCandidateStatus =
  | "Awaiting Verification"
  | "Awaiting SSA Verification ID"
  | "Verified — Potential Core"
  | "Verified — Not Core Ready"
  | "Recommended for October Onboarding"
  | "Scheduled for Core Onboarding";

export type CoreSchoolCandidate = {
  candidateId: string;
  schoolId: string;
  schoolName: string;
  district: string;
  currentSchoolType: "Client";
  assignedCceoId: string;
  assignedCceoName: string;
  originalSsaId: string;
  originalSsaAverage: number; // 0–10
  verificationTodoId?: string;
  verificationStatus: CoreCandidateStatus;
  ssaVerificationId?: string;
  verifiedSsaAverage?: number;
  potentialCoreFlag: boolean;
  recommendedOnboardingMonth?: "October";
  onboardingRecommendationStatus?:
    | "Recommended"
    | "Scheduled"
    | "Submitted for Approval"
    | "Approved"
    | "Completed";
};

// Seeded candidates that demonstrate every step of the workflow.
export const coreSchoolCandidates: CoreSchoolCandidate[] = [
  {
    candidateId: "CC-001",
    schoolId: "SCH-CC-101",
    schoolName: "Hope Bright P/S",
    district: "Kitgum",
    currentSchoolType: "Client",
    assignedCceoId: "STF-DM-014",
    assignedCceoName: "Daniel Mwangi",
    originalSsaId: "SSA-2025-Q4-101",
    originalSsaAverage: 7.6,
    verificationTodoId: "TODO-SSA-VER-101",
    verificationStatus: "Awaiting Verification",
    potentialCoreFlag: false,
  },
  {
    candidateId: "CC-002",
    schoolId: "SCH-CC-102",
    schoolName: "St. Mary's Junior",
    district: "Pader",
    currentSchoolType: "Client",
    assignedCceoId: "STF-GN-007",
    assignedCceoName: "Grace Nansubuga",
    originalSsaId: "SSA-2025-Q4-102",
    originalSsaAverage: 7.8,
    verificationTodoId: "TODO-SSA-VER-102",
    verificationStatus: "Awaiting SSA Verification ID",
    potentialCoreFlag: false,
  },
  {
    candidateId: "CC-003",
    schoolId: "SCH-CC-103",
    schoolName: "Riverside Children's",
    district: "Gulu",
    currentSchoolType: "Client",
    assignedCceoId: "STF-PO-008",
    assignedCceoName: "Peter Ochieng",
    originalSsaId: "SSA-2025-Q4-103",
    originalSsaAverage: 7.9,
    verificationStatus: "Verified — Potential Core",
    ssaVerificationId: "SSA-VER-2025-103",
    verifiedSsaAverage: 7.85,
    potentialCoreFlag: true,
    recommendedOnboardingMonth: "October",
    onboardingRecommendationStatus: "Recommended",
  },
  {
    candidateId: "CC-004",
    schoolId: "SCH-CC-104",
    schoolName: "Sunrise Primary",
    district: "Lamwo",
    currentSchoolType: "Client",
    assignedCceoId: "STF-SK-001",
    assignedCceoName: "Sarah Khan",
    originalSsaId: "SSA-2025-Q4-104",
    originalSsaAverage: 7.6,
    verificationStatus: "Verified — Not Core Ready",
    ssaVerificationId: "SSA-VER-2025-104",
    verifiedSsaAverage: 7.2,
    potentialCoreFlag: false,
  },
  {
    candidateId: "CC-005",
    schoolId: "SCH-CC-105",
    schoolName: "Eastview Junior",
    district: "Agago",
    currentSchoolType: "Client",
    assignedCceoId: "STF-SN-009",
    assignedCceoName: "Sarah Namutebi",
    originalSsaId: "SSA-2025-Q4-105",
    originalSsaAverage: 7.7,
    verificationStatus: "Recommended for October Onboarding",
    ssaVerificationId: "SSA-VER-2025-105",
    verifiedSsaAverage: 7.92,
    potentialCoreFlag: true,
    recommendedOnboardingMonth: "October",
    onboardingRecommendationStatus: "Submitted for Approval",
  },
];

// ────────── Staff verification todos ──────────

export type SsaVerificationTodo = {
  todoId: string;
  type: "SSA Verification";
  schoolId: string;
  schoolName: string;
  assignedStaffId: string;
  source: "Recommendation Engine";
  priority: "High";
  reason: string;
  status:
    | "Recommended"
    | "SSA Verification Required"
    | "Awaiting SSA Verification ID"
    | "Submitted for Review"
    | "Verified"
    | "Potential Core School"
    | "Closed";
  originalSsaId: string;
  ssaVerificationId?: string;
  dueDate?: string;
};

export const ssaVerificationTodos: SsaVerificationTodo[] = [
  {
    todoId: "TODO-SSA-VER-101",
    type: "SSA Verification",
    schoolId: "SCH-CC-101",
    schoolName: "Hope Bright P/S",
    assignedStaffId: "STF-DM-014",
    source: "Recommendation Engine",
    priority: "High",
    reason: "Client school SSA average 7.6 across all 8 interventions.",
    status: "SSA Verification Required",
    originalSsaId: "SSA-2025-Q4-101",
    dueDate: "2025-06-20",
  },
  {
    todoId: "TODO-SSA-VER-102",
    type: "SSA Verification",
    schoolId: "SCH-CC-102",
    schoolName: "St. Mary's Junior",
    assignedStaffId: "STF-GN-007",
    source: "Recommendation Engine",
    priority: "High",
    reason: "Client school SSA average 7.8 across all 8 interventions.",
    status: "Awaiting SSA Verification ID",
    originalSsaId: "SSA-2025-Q4-102",
    dueDate: "2025-06-22",
  },
];

// ────────── Cross-dashboard rollups ──────────

export function ssaCoreCandidateSummary() {
  const eligibleClients = coreSchoolCandidates.length;
  const awaitingVerification = coreSchoolCandidates.filter(
    (c) =>
      c.verificationStatus === "Awaiting Verification" ||
      c.verificationStatus === "Awaiting SSA Verification ID",
  ).length;
  const flaggedPotential = coreSchoolCandidates.filter((c) => c.potentialCoreFlag).length;
  const octoberRecommended = coreSchoolCandidates.filter(
    (c) => c.onboardingRecommendationStatus === "Recommended" || c.onboardingRecommendationStatus === "Submitted for Approval",
  ).length;
  return { eligibleClients, awaitingVerification, flaggedPotential, octoberRecommended };
}
