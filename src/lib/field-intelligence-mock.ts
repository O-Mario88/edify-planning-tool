// Field Intelligence Engine — Daily Field Debrief → Weekly Field Reality
// Report → Leadership Decision Brief.
//
// CONTRACT (per product doc):
//   • System auto-fills activity numbers; staff write only field context.
//   • Every debrief is classified into one of 10 intelligence categories so
//     leadership can distinguish performance issues from protected field
//     constraints.
//   • Weekly summaries roll up automatically: Staff → Program Lead Team →
//     Country → RVP + HR.
//   • Raw Achievement and Context-Adjusted Achievement are reported side by
//     side so staff aren't punished for school closures, blocked days, or
//     funding delays.

import type { CurrentUser } from "./schools-mock";

// ────────── Domain types ──────────

export type DayOutcome =
  | "Very Successful"
  | "Good"
  | "Challenging"
  | "Very Difficult"
  | "Could Not Execute Planned Work";

export type DebriefBarrier =
  | "School Unavailable"
  | "School Closed"
  | "Headteacher Unavailable"
  | "Weather / Road Problem"
  | "Transport Issue"
  | "Route Difficulty"
  | "Funding Delay"
  | "Partner Unavailable"
  | "Public Holiday / Blocked Day"
  | "Staff Sickness"
  | "Emergency Assignment"
  | "Salesforce Issue"
  | "Evidence Upload Issue"
  | "Wrong School Contact"
  | "Training Materials Not Ready"
  | "Other";

export type SupportRequest =
  | "No Support Needed"
  | "Program Lead Follow-Up"
  | "Route Adjustment"
  | "Partner Support"
  | "Finance / Funding Support"
  | "M&E Support"
  | "Salesforce Support"
  | "School Contact Update"
  | "Rescheduling Help"
  | "Coaching";

export type DebriefClassification =
  | "School Availability Issue"
  | "Route / Travel Issue"
  | "Planning Issue"
  | "Funding Issue"
  | "Partner Delivery Issue"
  | "Salesforce / System Issue"
  | "Evidence / Verification Issue"
  | "Staff Support Needed"
  | "Protected Field Constraint"
  | "Accountability Concern";

export type DailyFieldDebrief = {
  id: string;
  staffId: string;
  staffName: string;
  programLeadId: string;
  countryDirectorId?: string;

  date: string;
  weekStartDate: string;
  weekEndDate: string;
  financialYear: string;

  // Auto-filled by the system
  plannedActivities: number;
  completedActivities: number;
  verifiedActivities: number;
  incompleteActivities: number;

  // Staff input
  howDayWent: DayOutcome;
  whatWentWell: string;
  whatDidNotGoWell: string;
  whyItDidNotGoWell: string;
  whatStaffDidAboutIt: string;
  whatToDoDifferentlyNextTime: string;
  supportNeeded: SupportRequest[];
  barrierCategories: DebriefBarrier[];

  // System-derived
  systemClassification: DebriefClassification;
  supervisorReviewStatus:
    | "Not Reviewed"
    | "Reviewed"
    | "Needs Clarification"
    | "Action Created"
    | "Escalated";
};

// ────────── Classification engine ──────────
//
// Maps barriers to one of 10 intelligence categories. Used both server-side
// when a debrief is submitted and during pattern-detection on rollups.
const PROTECTED_BARRIERS: DebriefBarrier[] = [
  "School Closed",
  "Headteacher Unavailable",
  "Weather / Road Problem",
  "Public Holiday / Blocked Day",
  "Emergency Assignment",
];

// Context-adjusted achievement: a missed activity caused by a protected
// barrier doesn't count against the staff member.
export function calculateRawAchievement(d: { plannedActivities: number; verifiedActivities: number }): number {
  if (d.plannedActivities <= 0) return 0;
  return Math.round((d.verifiedActivities / d.plannedActivities) * 100);
}

export function calculateContextAdjustedAchievement(d: {
  plannedActivities: number;
  verifiedActivities: number;
  barrierCategories: DebriefBarrier[];
}): number {
  if (d.plannedActivities <= 0) return 0;
  const protectedHits = d.barrierCategories.filter((b) => PROTECTED_BARRIERS.includes(b)).length;
  const adjustedDenominator = Math.max(1, d.plannedActivities - protectedHits);
  return Math.min(100, Math.round((d.verifiedActivities / adjustedDenominator) * 100));
}

// ────────── Seed: 5 staff × ~3 days = 15 debriefs ──────────

export const dailyDebriefs: DailyFieldDebrief[] = [
  {
    id: "DB-001",
    staffId: "STF-DM-014", staffName: "Daniel Mwangi",
    programLeadId: "PL-001", countryDirectorId: "CD-UG",
    date: "2025-11-10", weekStartDate: "2025-11-10", weekEndDate: "2025-11-14", financialYear: "FY 2025/26",
    plannedActivities: 5, completedActivities: 4, verifiedActivities: 4, incompleteActivities: 1,
    howDayWent: "Good",
    whatWentWell: "Cluster training at Mukono Hub completed with strong attendance.",
    whatDidNotGoWell: "Riverside Primary closed early for parent meeting.",
    whyItDidNotGoWell: "Headteacher gave short notice — calendar wasn't updated.",
    whatStaffDidAboutIt: "Confirmed by phone with neighboring school and rerouted to nearby visit.",
    whatToDoDifferentlyNextTime: "Confirm school calendar 48 hours before travel.",
    supportNeeded: ["School Contact Update"],
    barrierCategories: ["School Closed"],
    systemClassification: "School Availability Issue",
    supervisorReviewStatus: "Not Reviewed",
  },
  {
    id: "DB-002",
    staffId: "STF-DM-014", staffName: "Daniel Mwangi",
    programLeadId: "PL-001",
    date: "2025-11-11", weekStartDate: "2025-11-10", weekEndDate: "2025-11-14", financialYear: "FY 2025/26",
    plannedActivities: 4, completedActivities: 4, verifiedActivities: 3, incompleteActivities: 0,
    howDayWent: "Very Successful",
    whatWentWell: "All 4 visits completed; 3 verified live in Salesforce.",
    whatDidNotGoWell: "1 evidence upload kept failing.",
    whyItDidNotGoWell: "Salesforce attachment timed out twice.",
    whatStaffDidAboutIt: "Logged a ticket with M&E and saved offline copy.",
    whatToDoDifferentlyNextTime: "Upload smaller image batches.",
    supportNeeded: ["Salesforce Support"],
    barrierCategories: ["Salesforce Issue", "Evidence Upload Issue"],
    systemClassification: "Salesforce / System Issue",
    supervisorReviewStatus: "Reviewed",
  },
  {
    id: "DB-003",
    staffId: "STF-DM-014", staffName: "Daniel Mwangi",
    programLeadId: "PL-001",
    date: "2025-11-12", weekStartDate: "2025-11-10", weekEndDate: "2025-11-14", financialYear: "FY 2025/26",
    plannedActivities: 5, completedActivities: 3, verifiedActivities: 3, incompleteActivities: 2,
    howDayWent: "Challenging",
    whatWentWell: "Hilltop Basic visit went well — leadership engaged.",
    whatDidNotGoWell: "Two cluster visits skipped — heavy rains blocked the road.",
    whyItDidNotGoWell: "Murram road washed out near Mukono junction.",
    whatStaffDidAboutIt: "Notified Program Lead and rescheduled for Friday.",
    whatToDoDifferentlyNextTime: "Check weather alerts before far cluster days.",
    supportNeeded: ["Rescheduling Help"],
    barrierCategories: ["Weather / Road Problem", "Route Difficulty"],
    systemClassification: "Route / Travel Issue",
    supervisorReviewStatus: "Action Created",
  },
  {
    id: "DB-004",
    staffId: "STF-GN-007", staffName: "Grace Nansubuga",
    programLeadId: "PL-001",
    date: "2025-11-10", weekStartDate: "2025-11-10", weekEndDate: "2025-11-14", financialYear: "FY 2025/26",
    plannedActivities: 6, completedActivities: 6, verifiedActivities: 5, incompleteActivities: 0,
    howDayWent: "Very Successful",
    whatWentWell: "Strong SSA review with 3 schools. Consistent evidence captured.",
    whatDidNotGoWell: "One school's gateway training was postponed.",
    whyItDidNotGoWell: "Materials hadn't arrived from partner.",
    whatStaffDidAboutIt: "Coordinated with partner to ship to next cluster.",
    whatToDoDifferentlyNextTime: "Confirm material arrival 7 days before training.",
    supportNeeded: ["Partner Support"],
    barrierCategories: ["Training Materials Not Ready", "Partner Unavailable"],
    systemClassification: "Partner Delivery Issue",
    supervisorReviewStatus: "Not Reviewed",
  },
  {
    id: "DB-005",
    staffId: "STF-GN-007", staffName: "Grace Nansubuga",
    programLeadId: "PL-001",
    date: "2025-11-11", weekStartDate: "2025-11-10", weekEndDate: "2025-11-14", financialYear: "FY 2025/26",
    plannedActivities: 5, completedActivities: 5, verifiedActivities: 5, incompleteActivities: 0,
    howDayWent: "Good",
    whatWentWell: "Verified 5 activities. Salesforce entries clean.",
    whatDidNotGoWell: "Nothing major.",
    whyItDidNotGoWell: "—",
    whatStaffDidAboutIt: "—",
    whatToDoDifferentlyNextTime: "Keep cadence.",
    supportNeeded: ["No Support Needed"],
    barrierCategories: [],
    systemClassification: "Planning Issue",
    supervisorReviewStatus: "Reviewed",
  },
  {
    id: "DB-006",
    staffId: "STF-PO-008", staffName: "Peter Ochieng",
    programLeadId: "PL-001",
    date: "2025-11-10", weekStartDate: "2025-11-10", weekEndDate: "2025-11-14", financialYear: "FY 2025/26",
    plannedActivities: 4, completedActivities: 2, verifiedActivities: 2, incompleteActivities: 2,
    howDayWent: "Very Difficult",
    whatWentWell: "Reached two priority schools and handed coaching plan.",
    whatDidNotGoWell: "Two visits missed — funding for transport hadn't been disbursed.",
    whyItDidNotGoWell: "Fund request still in Accountant review queue.",
    whatStaffDidAboutIt: "Flagged with Program Lead and Accountant.",
    whatToDoDifferentlyNextTime: "Submit fund requests on Monday for the week.",
    supportNeeded: ["Finance / Funding Support"],
    barrierCategories: ["Funding Delay"],
    systemClassification: "Funding Issue",
    supervisorReviewStatus: "Escalated",
  },
  {
    id: "DB-007",
    staffId: "STF-PO-008", staffName: "Peter Ochieng",
    programLeadId: "PL-001",
    date: "2025-11-12", weekStartDate: "2025-11-10", weekEndDate: "2025-11-14", financialYear: "FY 2025/26",
    plannedActivities: 5, completedActivities: 5, verifiedActivities: 4, incompleteActivities: 0,
    howDayWent: "Good",
    whatWentWell: "Recovered from Monday's gap with extra cluster visit.",
    whatDidNotGoWell: "Verification slow on one record.",
    whyItDidNotGoWell: "Returning evidence loop with M&E.",
    whatStaffDidAboutIt: "Resubmitted with clearer photos.",
    whatToDoDifferentlyNextTime: "Take 2 backup photos per visit.",
    supportNeeded: ["M&E Support"],
    barrierCategories: ["Evidence Upload Issue"],
    systemClassification: "Evidence / Verification Issue",
    supervisorReviewStatus: "Reviewed",
  },
  {
    id: "DB-008",
    staffId: "STF-SN-009", staffName: "Sarah Namutebi",
    programLeadId: "PL-002",
    date: "2025-11-11", weekStartDate: "2025-11-10", weekEndDate: "2025-11-14", financialYear: "FY 2025/26",
    plannedActivities: 5, completedActivities: 4, verifiedActivities: 4, incompleteActivities: 1,
    howDayWent: "Good",
    whatWentWell: "Cluster review at Omoro West clear and well-attended.",
    whatDidNotGoWell: "Missed one school — staff sick day.",
    whyItDidNotGoWell: "Personal sickness.",
    whatStaffDidAboutIt: "Updated leave/absence in HR system.",
    whatToDoDifferentlyNextTime: "Pre-arrange backup CCEO when possible.",
    supportNeeded: ["No Support Needed"],
    barrierCategories: ["Staff Sickness"],
    systemClassification: "Protected Field Constraint",
    supervisorReviewStatus: "Reviewed",
  },
  {
    id: "DB-009",
    staffId: "STF-BO-005", staffName: "Brian Okello",
    programLeadId: "PL-002",
    date: "2025-11-10", weekStartDate: "2025-11-10", weekEndDate: "2025-11-14", financialYear: "FY 2025/26",
    plannedActivities: 4, completedActivities: 1, verifiedActivities: 1, incompleteActivities: 3,
    howDayWent: "Could Not Execute Planned Work",
    whatWentWell: "One school visit reached.",
    whatDidNotGoWell: "Three schools refused entry citing exam preparation.",
    whyItDidNotGoWell: "Exam week — schools unavailable.",
    whatStaffDidAboutIt: "Confirmed with district education office and rescheduled.",
    whatToDoDifferentlyNextTime: "Sync with district calendar before exam weeks.",
    supportNeeded: ["School Contact Update", "Rescheduling Help"],
    barrierCategories: ["School Unavailable", "Wrong School Contact"],
    systemClassification: "School Availability Issue",
    supervisorReviewStatus: "Action Created",
  },
];

// ────────── Auto-fill helper ──────────
//
// In production this is filled from the planning, Salesforce, and
// verification systems. Mock returns the planned/completed/verified
// numbers for "today" given a staff id.
export function autoFillDailyDebrief(staffId: string): {
  plannedActivities: number;
  completedActivities: number;
  verifiedActivities: number;
  incompleteActivities: number;
} {
  const today = dailyDebriefs.find((d) => d.staffId === staffId && d.date === "2025-11-12");
  if (today) return {
    plannedActivities: today.plannedActivities,
    completedActivities: today.completedActivities,
    verifiedActivities: today.verifiedActivities,
    incompleteActivities: today.incompleteActivities,
  };
  return { plannedActivities: 5, completedActivities: 0, verifiedActivities: 0, incompleteActivities: 5 };
}

// ────────── Pattern detection ──────────

export type FieldBarrierPattern = {
  category: DebriefClassification;
  occurrences: number;
  affectedStaff: string[];
  examples: string[];
};

export function detectRepeatedFieldBarriers(
  debriefs: DailyFieldDebrief[] = dailyDebriefs,
): FieldBarrierPattern[] {
  const map = new Map<DebriefClassification, FieldBarrierPattern>();
  for (const d of debriefs) {
    const c = d.systemClassification;
    if (!map.has(c)) {
      map.set(c, { category: c, occurrences: 0, affectedStaff: [], examples: [] });
    }
    const row = map.get(c)!;
    row.occurrences += 1;
    if (!row.affectedStaff.includes(d.staffName)) row.affectedStaff.push(d.staffName);
    if (row.examples.length < 3) row.examples.push(d.whatDidNotGoWell);
  }
  return Array.from(map.values()).sort((a, b) => b.occurrences - a.occurrences);
}

// ────────── Weekly compilation ──────────

export type WeeklyStaffSummary = {
  staffId: string;
  staffName: string;
  weekStart: string;
  weekEnd: string;
  totalDebriefs: number;
  plannedActivities: number;
  completedActivities: number;
  verifiedActivities: number;
  rawAchievementPercent: number;
  contextAdjustedAchievementPercent: number;
  topSuccess: string;
  topBarrier: string;
  supportRequested: SupportRequest[];
  classificationCounts: Record<DebriefClassification, number>;
  recommendedActions: string[];
};

export function generateWeeklyStaffSummary(
  staffId: string,
  debriefs: DailyFieldDebrief[] = dailyDebriefs,
): WeeklyStaffSummary | null {
  const my = debriefs.filter((d) => d.staffId === staffId);
  if (my.length === 0) return null;
  const planned = my.reduce((a, d) => a + d.plannedActivities, 0);
  const completed = my.reduce((a, d) => a + d.completedActivities, 0);
  const verified = my.reduce((a, d) => a + d.verifiedActivities, 0);
  const protectedHits = my.reduce(
    (a, d) => a + d.barrierCategories.filter((b) => PROTECTED_BARRIERS.includes(b)).length,
    0,
  );
  const raw = planned > 0 ? Math.round((verified / planned) * 100) : 0;
  const adjustedDenom = Math.max(1, planned - protectedHits);
  const adjusted = Math.min(100, Math.round((verified / adjustedDenom) * 100));

  const counts = my.reduce<Record<DebriefClassification, number>>((acc, d) => {
    acc[d.systemClassification] = (acc[d.systemClassification] ?? 0) + 1;
    return acc;
  }, {} as Record<DebriefClassification, number>);

  const supports = Array.from(new Set(my.flatMap((d) => d.supportNeeded))).filter(
    (s) => s !== "No Support Needed",
  );

  const topSuccess = my.find((d) => d.howDayWent === "Very Successful")?.whatWentWell
    ?? my[0].whatWentWell;
  const topBarrier = my.find((d) => d.systemClassification !== "Planning Issue")?.whatDidNotGoWell
    ?? my[0].whatDidNotGoWell;

  return {
    staffId,
    staffName: my[0].staffName,
    weekStart: my[0].weekStartDate,
    weekEnd: my[0].weekEndDate,
    totalDebriefs: my.length,
    plannedActivities: planned,
    completedActivities: completed,
    verifiedActivities: verified,
    rawAchievementPercent: raw,
    contextAdjustedAchievementPercent: adjusted,
    topSuccess,
    topBarrier,
    supportRequested: supports,
    classificationCounts: counts,
    recommendedActions: recommendNextWeekPlanningActions(my),
  };
}

function recommendNextWeekPlanningActions(debriefs: DailyFieldDebrief[]): string[] {
  const out: string[] = [];
  const has = (c: DebriefClassification) =>
    debriefs.some((d) => d.systemClassification === c);
  if (has("School Availability Issue")) out.push("Confirm school calendars 48h before travel.");
  if (has("Route / Travel Issue")) out.push("Pre-check weather and re-cluster long routes.");
  if (has("Funding Issue")) out.push("Submit weekly fund request by Monday morning.");
  if (has("Partner Delivery Issue")) out.push("Confirm partner material delivery 7 days ahead.");
  if (has("Salesforce / System Issue")) out.push("Open M&E ticket; upload smaller batches.");
  if (has("Evidence / Verification Issue")) out.push("Capture 2+ backup evidence photos per visit.");
  if (has("Staff Support Needed")) out.push("Schedule supervisor 1:1 this week.");
  if (out.length === 0) out.push("Hold cadence — focus on Core School pacing.");
  return out;
}

// ────────── Program Lead / Country / RVP / HR rollups ──────────

export type WeeklyTeamReport = {
  reportingUserId: string;
  reportingUserName: string;
  reportLevel: "Program Lead Team" | "Country" | "RVP" | "HR";
  periodStart: string;
  periodEnd: string;
  totalDebriefsExpected: number;
  totalDebriefsSubmitted: number;
  debriefSubmissionRate: number;
  totalPlanned: number;
  totalCompleted: number;
  totalVerified: number;
  rawAchievement: number;
  contextAdjustedAchievement: number;
  topSuccesses: string[];
  topBarriers: FieldBarrierPattern[];
  staffSupportNeeds: string[];
  schoolsNeedingFollowUp: string[];
  recommendedLeadershipActions: string[];
  decisions: LeadershipDecision[];
  reviewStatus:
    | "Auto-Generated"
    | "Ready for Review"
    | "Reviewed"
    | "Submitted"
    | "Approved";
};

export type LeadershipDecision = {
  decisionArea:
    | "Planning"
    | "Routes"
    | "Funding"
    | "Partner Delivery"
    | "Salesforce"
    | "School Availability"
    | "Staff Support"
    | "Core Schools"
    | "Special Projects";
  issue: string;
  recommendedDecision: string;
  urgency: "Low" | "Medium" | "High" | "Critical";
  ownerRole: "Program Lead" | "Country Director" | "RVP" | "HR" | "Admin";
};

function rollup(debriefs: DailyFieldDebrief[]): {
  planned: number;
  completed: number;
  verified: number;
  raw: number;
  adjusted: number;
} {
  const planned = debriefs.reduce((a, d) => a + d.plannedActivities, 0);
  const completed = debriefs.reduce((a, d) => a + d.completedActivities, 0);
  const verified = debriefs.reduce((a, d) => a + d.verifiedActivities, 0);
  const protectedHits = debriefs.reduce(
    (a, d) => a + d.barrierCategories.filter((b) => PROTECTED_BARRIERS.includes(b)).length,
    0,
  );
  const raw = planned > 0 ? Math.round((verified / planned) * 100) : 0;
  const adj = Math.min(100, Math.round((verified / Math.max(1, planned - protectedHits)) * 100));
  return { planned, completed, verified, raw, adjusted: adj };
}


export function extractLeadershipDecisions(patterns: FieldBarrierPattern[]): LeadershipDecision[] {
  const out: LeadershipDecision[] = [];
  for (const p of patterns) {
    if (p.occurrences < 2) continue;
    if (p.category === "School Availability Issue") {
      out.push({
        decisionArea: "School Availability",
        issue: `${p.occurrences} debriefs reported school unavailability across ${p.affectedStaff.length} staff.`,
        recommendedDecision: "Update school contacts and adopt 48h pre-confirmation SOP.",
        urgency: "High",
        ownerRole: "Program Lead",
      });
    } else if (p.category === "Route / Travel Issue") {
      out.push({
        decisionArea: "Routes",
        issue: `${p.occurrences} debriefs reported route or weather problems.`,
        recommendedDecision: "Re-cluster long routes and add weather check before travel days.",
        urgency: "Medium",
        ownerRole: "Country Director",
      });
    } else if (p.category === "Funding Issue") {
      out.push({
        decisionArea: "Funding",
        issue: `${p.occurrences} debriefs blocked by fund disbursement delay.`,
        recommendedDecision: "Bring fund cycle forward; escalate to Accountant + Director.",
        urgency: "Critical",
        ownerRole: "Country Director",
      });
    } else if (p.category === "Partner Delivery Issue") {
      out.push({
        decisionArea: "Partner Delivery",
        issue: `${p.occurrences} debriefs flagged partner material or availability gaps.`,
        recommendedDecision: "Confirm partner SLAs and material lead times for next quarter.",
        urgency: "High",
        ownerRole: "Country Director",
      });
    } else if (p.category === "Salesforce / System Issue" || p.category === "Evidence / Verification Issue") {
      out.push({
        decisionArea: "Salesforce",
        issue: `${p.occurrences} debriefs blocked by Salesforce or evidence upload issues.`,
        recommendedDecision: "Open ops ticket; share batch upload guidance with all CCEOs.",
        urgency: "Medium",
        ownerRole: "Admin",
      });
    } else if (p.category === "Staff Support Needed") {
      out.push({
        decisionArea: "Staff Support",
        issue: `${p.occurrences} staff requested support this week.`,
        recommendedDecision: "Schedule supervisor 1:1s; flag any 2+ repeat requests.",
        urgency: "Medium",
        ownerRole: "Program Lead",
      });
    }
  }
  return out;
}

// ────────── Role-aware filters ──────────

// Maps a signed-in user to the `programLeadId` they own debriefs under.
// Demo-time shim: the seed labels Program Leads as "PL-001" / "PL-002"
// while production keys debriefs by the PL's staffId. Until the org-chart
// service exists we treat the signed-in user's staffId as their own
// programLeadId — the point is to stop hardcoding a literal so the UI
// reflects the actual signed-in user.
export function programLeadIdForUser(user: CurrentUser): string {
  return user.staffId;
}

// Visibility rule for RAW daily debriefs (per product spec):
//   • Admin                       → all debriefs (operator override).
//   • CountryDirector             → NONE. CD reads weekly compiled PL
//                                   reports, never raw daily journals.
//   • CountryProgramLead          → only debriefs from staff they supervise
//                                   (matched by programLeadId).
//   • CCEO                        → only their own authored debriefs.
//   • HR / RVP / ImpactAssessment /
//     ProgramAccountant           → NONE. These roles see aggregated /
//                                   anonymised rollups elsewhere — they
//                                   must not access named raw debriefs.
export function debriefsForUser(user: CurrentUser): DailyFieldDebrief[] {
  if (user.role === "Admin") return dailyDebriefs;
  if (user.role === "CountryDirector") return [];
  if (user.role === "CountryProgramLead") {
    const plId = programLeadIdForUser(user);
    return dailyDebriefs.filter((d) => d.programLeadId === plId);
  }
  if (user.role === "CCEO") {
    return dailyDebriefs.filter((d) => d.staffId === user.staffId);
  }
  // HR, RVP, ImpactAssessment, ProgramAccountant: no raw access.
  return [];
}

// ────────── Tiered reporting (Leadership tier) ──────────
//
// Visibility rule: Daily Debriefs stay close to the field. Weekly Reports
// move up to leadership.
//   • CCEO writes daily; only the CCEO + their Program Lead see raw debriefs.
//   • Program Lead reviews daily, writes own weekly reflection, and the
//     system compiles the Program Lead Weekly Field Report.
//   • Country Director reads weekly reports — never raw daily notes.
//   • RVP / HR see a Country Weekly Field Intelligence Report only.

export type WeeklyReportStatus =
  | "Generated"
  | "PL Editing"
  | "Submitted to CD"
  | "Returned for Clarification"
  | "Resubmitted"
  | "Reviewed by CD"
  | "Closed";

export type ProgramLeadWeeklyFieldReport = {
  id:                                string;
  programLeadId:                     string;
  programLeadName:                   string;
  team:                              string;
  region:                            string;
  financialYearId:                   string;
  weekLabel:                         string;
  weekStart:                         string;
  weekEnd:                           string;
  cceoCount:                         number;
  sourceDailyDebriefIds:             string[];
  expectedDebriefs:                  number;
  submittedDebriefs:                 number;
  debriefSubmissionRate:             number;
  totalPlannedActivities:            number;
  totalCompletedActivities:          number;
  totalVerifiedActivities:           number;
  salesforcePendingCount:            number;
  returnedRecordCount:               number;
  overdueActivitiesCount:            number;
  rawAchievementPercent:             number;
  contextAdjustedAchievementPercent: number;
  topSuccesses:                      string[];
  topBarriers:                       { category: string; count: number; recommendedAction: string }[];
  staffSupportNeeds:                 { cceoName: string; issue: string; action: string; decisionNeeded?: string }[];
  schoolsNeedingFollowUp:            { school: string; reason: string; nextStep: string; owner: string }[];
  systemGeneratedInsights:           string[];
  decisionsRequiredFromCD:           string[];
  nextWeekPriorities:                string[];
  programLeadWeeklyDebrief: {
    whatWentWell:           string;
    whatDidNotGoWell:       string;
    teamSupportProvided:    string;
    decisionsNeededFromCD:  string;
    nextWeekPriorities:     string;
  };
  status:        WeeklyReportStatus;
  submittedAt?:  string;
  reviewedAt?:   string;
  downloadablePdfUrl?: string;
};

export type CountryWeeklyFieldIntelligenceReport = {
  id:                                string;
  countryDirectorId:                 string;
  country:                           string;
  financialYearId:                   string;
  weekLabel:                         string;
  weekStart:                         string;
  weekEnd:                           string;
  totalProgramLeadReports:           number;
  submittedProgramLeadReports:       number;
  countryPlannedActivities:          number;
  countryCompletedActivities:        number;
  countryVerifiedActivities:         number;
  countryRawAchievementPercent:      number;
  countryContextAdjustedAchievementPercent: number;
  topCountrySuccesses:               string[];
  topCountryBarriers:                { category: string; count: number; regions: string[] }[];
  regionalPatterns:                  string[];
  staffSupportThemes:                string[];
  fundingIssues:                     string[];
  partnerDeliveryIssues:             string[];
  salesforceEvidenceIssues:          string[];
  decisionsRequired:                 string[];
  status:                            "Generated" | "Ready for CD Review" | "Reviewed by CD" | "Shared with RVP" | "Closed";
};

// Mock data — three Program Leads in Uganda, current week.

export const programLeadWeeklyFieldReports: ProgramLeadWeeklyFieldReport[] = [
  {
    id:                       "PLR-2025W19-001",
    programLeadId:            "STF-DM-014",
    programLeadName:          "Daniel Mwangi",
    team:                     "Northern Team A",
    region:                   "North",
    financialYearId:          "FY25",
    weekLabel:                "Week 19 · May 6 – May 10",
    weekStart:                "2025-05-06",
    weekEnd:                  "2025-05-10",
    cceoCount:                8,
    sourceDailyDebriefIds:    Array.from({ length: 37 }, (_, i) => `DDF-${i + 1}`),
    expectedDebriefs:         40,
    submittedDebriefs:        37,
    debriefSubmissionRate:    Math.round((37 / 40) * 100),
    totalPlannedActivities:   240,
    totalCompletedActivities: 187,
    totalVerifiedActivities:  152,
    salesforcePendingCount:   18,
    returnedRecordCount:      4,
    overdueActivitiesCount:   9,
    rawAchievementPercent:    78,
    contextAdjustedAchievementPercent: 89,
    topSuccesses: [
      "Strong school cooperation in Kitgum Cluster.",
      "Teachers responded well to Teaching Environment coaching.",
      "Three overdue SSA verifications were completed.",
      "Partner-supported visits improved in Lamwo.",
    ],
    topBarriers: [
      { category: "School Availability", count: 11, recommendedAction: "Adopt 48-hour pre-confirmation SOP with headteachers in Lamwo East." },
      { category: "Route / Travel",       count: 6,  recommendedAction: "Re-design Thursday Pader-Kal route — current spread exceeds 5-visits/day." },
      { category: "Salesforce / Evidence", count: 4, recommendedAction: "Submit returned records to Impact Assessment with corrected attachments." },
      { category: "Funding Delay",         count: 2,  recommendedAction: "Escalate transport advance for the Kitgum-Pader long-distance route." },
    ],
    staffSupportNeeds: [
      { cceoName: "Peter Ochieng", issue: "3 schools repeatedly closed",      action: "Switched route to Pader West for next week.", decisionNeeded: "Approve replacement schools in same district." },
      { cceoName: "Grace Njeri",   issue: "Funds delay blocking 2 trainings", action: "Requested CD escalation.",                    decisionNeeded: "Authorise transport advance." },
      { cceoName: "Brian Okello",  issue: "Returned Salesforce records (4)",  action: "Re-uploaded with verification.",              decisionNeeded: undefined },
    ],
    schoolsNeedingFollowUp: [
      { school: "Hope Children's PS",   reason: "SSA score dropped 1.4pt", nextStep: "Add coaching visit Week 20", owner: "Peter Ochieng" },
      { school: "Olive Comprehensive",  reason: "Headteacher absent twice", nextStep: "District follow-up call",   owner: "Daniel Mwangi" },
      { school: "Sunrise Junior",       reason: "Returned Salesforce ID", nextStep: "Re-verify with evidence",   owner: "Brian Okello"  },
    ],
    systemGeneratedInsights: [
      "Most missed activities were caused by school availability, not staff inactivity.",
      "Three route groups should be re-designed next week.",
      "Training follow-up is overdue in 12 schools trained in Fees / Budget / Accounts.",
      "Partner Sunrise has reached 94% of monthly capacity.",
    ],
    decisionsRequiredFromCD: [
      "Approve additional transport support for the Kitgum-Pader long-distance route.",
      "Authorise partner support for 18 overdue follow-up schools.",
      "Resolve funding delay affecting cluster training Week 20.",
      "Request Impact Assessment review for the 4 returned Salesforce records.",
    ],
    nextWeekPriorities: [
      "Complete 12 overdue Fees/Budget training follow-ups.",
      "Re-balance Thursday route to ≤ 5 visits per day.",
      "Onboard new Pader West schools to replace closures.",
    ],
    programLeadWeeklyDebrief: {
      whatWentWell:           "Team picked up overdue SSAs despite school closures. Strong morale.",
      whatDidNotGoWell:       "Three routes were too spread out. Two schools were closed on planned days.",
      teamSupportProvided:    "Ride-along with Peter Ochieng on Wednesday. Rebalanced his Thursday route.",
      decisionsNeededFromCD:  "Transport advance authorisation. Partner-support assignment for overdue follow-ups.",
      nextWeekPriorities:     "Clear Fees/Budget follow-ups, fix Thursday route, complete returned Salesforce records.",
    },
    status:                "Submitted to CD",
    submittedAt:           "2025-05-10 17:42",
    downloadablePdfUrl:    "#",
  },
  {
    id:                       "PLR-2025W19-002",
    programLeadId:            "STF-AD-021",
    programLeadName:          "Aisha Dar",
    team:                     "Central Team B",
    region:                   "Central",
    financialYearId:          "FY25",
    weekLabel:                "Week 19 · May 6 – May 10",
    weekStart:                "2025-05-06",
    weekEnd:                  "2025-05-10",
    cceoCount:                6,
    sourceDailyDebriefIds:    Array.from({ length: 28 }, (_, i) => `DDF-A-${i + 1}`),
    expectedDebriefs:         30,
    submittedDebriefs:        28,
    debriefSubmissionRate:    Math.round((28 / 30) * 100),
    totalPlannedActivities:   180,
    totalCompletedActivities: 156,
    totalVerifiedActivities:  138,
    salesforcePendingCount:   8,
    returnedRecordCount:      1,
    overdueActivitiesCount:   3,
    rawAchievementPercent:    87,
    contextAdjustedAchievementPercent: 93,
    topSuccesses: [
      "Cluster Training in Mukono Hub fully attended.",
      "All 4 Core Schools received planned visits.",
      "Salesforce backlog cleared.",
    ],
    topBarriers: [
      { category: "Partner Delivery", count: 5, recommendedAction: "Escalate facilitator no-show with Maryhill partner." },
      { category: "School Availability", count: 4, recommendedAction: "Confirm headteacher availability earlier next cycle." },
    ],
    staffSupportNeeds: [
      { cceoName: "Sarah Namutebi", issue: "Partner facilitator no-show twice", action: "Reassigned to internal facilitator.", decisionNeeded: "Partner certification review." },
    ],
    schoolsNeedingFollowUp: [
      { school: "Wakiso Bright Junior", reason: "Cluster training rescheduled twice", nextStep: "Lock new date and notify all participants", owner: "Sarah Namutebi" },
    ],
    systemGeneratedInsights: [
      "Partner Maryhill is at 78% reliability — flag for certification review.",
      "Central team verified achievement is 6 pts above country average.",
    ],
    decisionsRequiredFromCD: [
      "Authorise Maryhill partner certification review.",
      "Confirm reassignment of cluster training facilitators for Week 20.",
    ],
    nextWeekPriorities: [
      "Lock rescheduled cluster training in Wakiso.",
      "Complete partner certification audit.",
    ],
    programLeadWeeklyDebrief: {
      whatWentWell:           "Backlog cleared, Core Schools fully covered, team momentum strong.",
      whatDidNotGoWell:       "Partner facilitator no-shows undermined two trainings.",
      teamSupportProvided:    "Reassigned facilitators. Provided talk-track to staff for delivery.",
      decisionsNeededFromCD:  "Maryhill partner certification review.",
      nextWeekPriorities:     "Cluster training reschedule, partner review, SSA verification close-out.",
    },
    // Aisha is still in PL Editing mode for the demo so the editor
    // demonstrates the submit lifecycle (Submit to CD button visible).
    status:                "PL Editing",
    submittedAt:           undefined,
    downloadablePdfUrl:    "#",
  },
  {
    id:                       "PLR-2025W19-003",
    programLeadId:            "STF-PL-099",
    programLeadName:          "Brian Lumumba",
    team:                     "Western Team C",
    region:                   "West",
    financialYearId:          "FY25",
    weekLabel:                "Week 19 · May 6 – May 10",
    weekStart:                "2025-05-06",
    weekEnd:                  "2025-05-10",
    cceoCount:                7,
    sourceDailyDebriefIds:    Array.from({ length: 22 }, (_, i) => `DDF-W-${i + 1}`),
    expectedDebriefs:         35,
    submittedDebriefs:        22,
    debriefSubmissionRate:    Math.round((22 / 35) * 100),
    totalPlannedActivities:   210,
    totalCompletedActivities: 132,
    totalVerifiedActivities:  98,
    salesforcePendingCount:   24,
    returnedRecordCount:      7,
    overdueActivitiesCount:   18,
    rawAchievementPercent:    47,
    contextAdjustedAchievementPercent: 61,
    topSuccesses: [
      "Two SSA Verifications completed despite road challenges.",
    ],
    topBarriers: [
      { category: "Funding Delay",      count: 9, recommendedAction: "Disburse Q2 transport advance immediately." },
      { category: "Route / Travel",     count: 7, recommendedAction: "Re-cluster Hoima route — current configuration is unrealistic." },
      { category: "Salesforce / Evidence", count: 7, recommendedAction: "On-site review with Impact Assessment for returned records." },
    ],
    staffSupportNeeds: [
      { cceoName: "Esther Naluwu", issue: "No fuel advance for 3 days", action: "PL covered out-of-pocket; reimbursement pending.", decisionNeeded: "Urgent Accountant escalation." },
      { cceoName: "Purity Muthoni", issue: "Returned Salesforce records (5)", action: "On-call coaching scheduled.", decisionNeeded: "Impact Assessment site visit." },
    ],
    schoolsNeedingFollowUp: [
      { school: "Mbarara East Comprehensive", reason: "Overdue SSA + missed coaching", nextStep: "Special-attention plan Week 20", owner: "Esther Naluwu" },
    ],
    systemGeneratedInsights: [
      "Western Team C is 14 points below the country context-adjusted average — funding is the dominant driver.",
      "Debrief submission rate fell below 70% — staff field time eaten by manual fuel sourcing.",
    ],
    decisionsRequiredFromCD: [
      "Authorise emergency transport advance for Western Team C.",
      "Approve special-attention plan for Mbarara East Comprehensive.",
      "Request Impact Assessment site visit to address returned records.",
    ],
    nextWeekPriorities: [
      "Restore funding pipeline.",
      "Re-cluster Hoima route.",
      "Catch-up on debrief submission compliance.",
    ],
    programLeadWeeklyDebrief: {
      whatWentWell:           "Despite barriers, team completed two SSA verifications on the worst route.",
      whatDidNotGoWell:       "Funding delay cascaded into missed visits and morale dip.",
      teamSupportProvided:    "Covered fuel out-of-pocket. Daily check-ins. Submitted urgent escalation.",
      decisionsNeededFromCD:  "Emergency transport advance. IA on-site review. Replacement plan for closed schools.",
      nextWeekPriorities:     "Funding restored, route re-cluster, debrief compliance back above 90%.",
    },
    // Brian submitted Monday morning — past the Saturday EOD SLA. CD
    // report center flags this row as "Late submission".
    status:                "Submitted to CD",
    submittedAt:           "2025-05-12 09:30",
    downloadablePdfUrl:    "#",
  },
];

// Country-level intelligence — single rollup CD reviews + shares upward.

export const countryWeeklyFieldIntelligence: CountryWeeklyFieldIntelligenceReport = {
  id:                          "CWFIR-2025W19",
  countryDirectorId:           "STF-SO-007",
  country:                     "Uganda",
  financialYearId:             "FY25",
  weekLabel:                   "Week 19 · May 6 – May 10",
  weekStart:                   "2025-05-06",
  weekEnd:                     "2025-05-10",
  totalProgramLeadReports:     programLeadWeeklyFieldReports.length,
  submittedProgramLeadReports: programLeadWeeklyFieldReports.filter((r) => r.status !== "Generated" && r.status !== "PL Editing").length,
  countryPlannedActivities:    programLeadWeeklyFieldReports.reduce((a, r) => a + r.totalPlannedActivities, 0),
  countryCompletedActivities:  programLeadWeeklyFieldReports.reduce((a, r) => a + r.totalCompletedActivities, 0),
  countryVerifiedActivities:   programLeadWeeklyFieldReports.reduce((a, r) => a + r.totalVerifiedActivities, 0),
  countryRawAchievementPercent: Math.round(
    (programLeadWeeklyFieldReports.reduce((a, r) => a + r.totalVerifiedActivities, 0) /
     programLeadWeeklyFieldReports.reduce((a, r) => a + r.totalPlannedActivities, 0)) * 100,
  ),
  countryContextAdjustedAchievementPercent: Math.round(
    programLeadWeeklyFieldReports.reduce((a, r) => a + r.contextAdjustedAchievementPercent, 0) /
    programLeadWeeklyFieldReports.length,
  ),
  topCountrySuccesses: [
    "Three Country teams cleared 92% of overdue SSA verifications combined.",
    "Cluster trainings hit 87% attendance country-wide.",
    "Salesforce verification turnaround improved by 18%.",
  ],
  topCountryBarriers: [
    { category: "Funding Delay",       count: 11, regions: ["West"] },
    { category: "School Availability", count: 15, regions: ["North", "Central"] },
    { category: "Route / Travel",      count: 13, regions: ["North", "West"] },
    { category: "Salesforce / Evidence", count: 11, regions: ["North", "West"] },
  ],
  regionalPatterns: [
    "Western region performance is constrained by funding pipeline — not staff effort.",
    "Northern region is route-constrained — needs cluster re-design.",
    "Central region partner reliability is the dominant blocker.",
  ],
  staffSupportThemes: [
    "Out-of-pocket fuel coverage is happening — fix funding cadence.",
    "Salesforce-return coaching needs a standardised SOP.",
    "Two PLs report repeated school availability — pre-confirmation SOP needed.",
  ],
  fundingIssues: [
    "Western Team C: Q2 transport advance not yet disbursed.",
    "Cluster Training Week 20 funding pending PL → CD sign-off.",
  ],
  partnerDeliveryIssues: [
    "Maryhill (Central): facilitator no-shows × 2 — certification review recommended.",
    "Sunrise (Northern): 94% of monthly capacity used — risk of overbooking.",
  ],
  salesforceEvidenceIssues: [
    "12 returned records across two regions — Impact Assessment site visits recommended.",
  ],
  decisionsRequired: [
    "Authorise emergency transport advance for Western Team C this week.",
    "Approve Maryhill partner certification review.",
    "Authorise route re-cluster for Hoima + Pader Thursday routes.",
    "Request Impact Assessment site visit for Western + Northern returned records.",
  ],
  status: "Ready for CD Review",
};

// Helper used by the CD report center.
export function programLeadWeeklyFieldReportById(id: string): ProgramLeadWeeklyFieldReport | undefined {
  return programLeadWeeklyFieldReports.find((r) => r.id === id);
}

// ────────── Week identifiers ──────────
//
// Stable week identifier for selectors, audit logs, and join keys. Format
// is ISO-week-ish (`YYYY-Www`) without a real ISO library — the demo only
// needs string equality + ordering.

export type WeekId = `${number}-W${number}`;

export function weekIdFromLabel(label: string): WeekId {
  // "Week 19 · May 6 – May 10" → "2025-W19" (year inferred from FY).
  const m = label.match(/Week\s+(\d+)/i);
  const wk = m ? Number(m[1]) : 1;
  return `2025-W${String(wk).padStart(2, "0")}` as WeekId;
}

// ────────── Status state machine ──────────

export const REPORT_STATUS_TRANSITIONS: Record<WeeklyReportStatus, WeeklyReportStatus[]> = {
  "Generated":                  ["PL Editing"],
  "PL Editing":                 ["Submitted to CD"],
  "Submitted to CD":            ["Reviewed by CD", "Returned for Clarification"],
  "Returned for Clarification": ["Resubmitted"],
  "Resubmitted":                ["Reviewed by CD", "Returned for Clarification"],
  "Reviewed by CD":             ["Closed"],
  "Closed":                     [],
};

export function canTransitionReport(from: WeeklyReportStatus, to: WeeklyReportStatus): boolean {
  return REPORT_STATUS_TRANSITIONS[from]?.includes(to) ?? false;
}

// ────────── Audit log ──────────

export type ReportEventKind =
  | "Generated"
  | "PL Started Editing"
  | "PL Submitted"
  | "CD Returned for Clarification"
  | "PL Resubmitted"
  | "CD Reviewed"
  | "CD Closed"
  | "Decision Created";

export type ReportEvent = {
  at:        string;
  byRole:    string;
  byName:    string;
  kind:      ReportEventKind;
  detail?:   string;
};

// Pre-seeded audit trails for the three demo reports.
export const reportEventLog: Record<string, ReportEvent[]> = {
  "PLR-2025W19-001": [
    { at: "2025-05-09 23:55", byRole: "System",       byName: "Field Intelligence Engine", kind: "Generated",         detail: "Auto-compiled from 37 daily debriefs across 8 CCEOs." },
    { at: "2025-05-10 09:14", byRole: "ProgramLead", byName: "Daniel Mwangi",            kind: "PL Started Editing" },
    { at: "2025-05-10 17:42", byRole: "ProgramLead", byName: "Daniel Mwangi",            kind: "PL Submitted",      detail: "Submitted to CD with 4 decisions required." },
  ],
  "PLR-2025W19-002": [
    { at: "2025-05-09 23:55", byRole: "System",      byName: "Field Intelligence Engine", kind: "Generated" },
    { at: "2025-05-10 14:30", byRole: "ProgramLead", byName: "Aisha Dar",                kind: "PL Started Editing", detail: "Still drafting; submission outstanding." },
  ],
  "PLR-2025W19-003": [
    { at: "2025-05-09 23:55", byRole: "System",      byName: "Field Intelligence Engine", kind: "Generated",         detail: "Auto-compiled from 22 daily debriefs (below 90% submission)." },
    { at: "2025-05-10 11:02", byRole: "ProgramLead", byName: "Brian Lumumba",            kind: "PL Started Editing" },
    { at: "2025-05-12 09:30", byRole: "ProgramLead", byName: "Brian Lumumba",            kind: "PL Submitted",      detail: "Submitted Monday — past Saturday SLA. Flagged emergency transport advance for CD." },
  ],
};

// ────────── Decision Actions ──────────
//
// Working-circle constraints from the product brief:
//   • CD assigns decisions to: Program Lead, Impact Assessment,
//     Program Accountant, Special Project Coordinator. CD does NOT assign
//     directly to CCEOs.
//   • RVP assigns decisions to: Country Director, Human Resource. RVP
//     does NOT assign directly to Program Leads or below.
//   • Program Lead can self-assign Program Lead-owned actions.

export type DecisionOwnerRole =
  | "ProgramLead"
  | "ImpactAssessment"
  | "ProgramAccountant"
  | "SpecialProjectCoordinator"
  | "CountryDirector"
  | "HumanResource"
  | "RVP";

export type DecisionCreatorRole = "CountryDirector" | "RVP" | "ProgramLead";

export type DecisionStatus =
  | "Pending"
  | "In Progress"
  | "Approved"
  | "Returned"
  | "Closed";

export type DecisionAction = {
  id:               string;
  title:            string;
  description:      string;
  createdAt:        string;
  createdByRole:    DecisionCreatorRole;
  createdByName:    string;
  sourceReportId:   string;          // PL Weekly Field Report id (back-link)
  sourceLine:       string;          // original "Decisions Required" text
  assigneeRole:     DecisionOwnerRole;
  assigneeName:     string;
  deadline:         string;          // YYYY-MM-DD
  priority:         "Low" | "Medium" | "High" | "Critical";
  status:           DecisionStatus;
  history:          { at: string; byRole: string; byName: string; event: string }[];
};

// Who can a creator route a decision to?
export const DECISION_ROUTING: Record<DecisionCreatorRole, DecisionOwnerRole[]> = {
  CountryDirector: ["ProgramLead", "ImpactAssessment", "ProgramAccountant", "SpecialProjectCoordinator"],
  RVP:             ["CountryDirector", "HumanResource"],
  ProgramLead:     ["ProgramLead", "ImpactAssessment", "ProgramAccountant"], // PL can self-track + ask IA/Accountant
};

export function canRouteDecision(creatorRole: DecisionCreatorRole, assigneeRole: DecisionOwnerRole): boolean {
  return DECISION_ROUTING[creatorRole]?.includes(assigneeRole) ?? false;
}

// Pre-seeded decisions so the CD dashboard isn't empty on first load. Once
// the user creates more from the PL report renderer they merge in via the
// client-side store.
export const decisionActions: DecisionAction[] = [
  {
    id:               "DA-2025W19-001",
    title:            "Authorise emergency transport advance — Western Team C",
    description:      "Esther Naluwu (Western Team C) had no fuel for 3 days; PL covered out-of-pocket. Restore Q2 transport pipeline immediately.",
    createdAt:        "2025-05-10 19:45",
    createdByRole:    "CountryDirector",
    createdByName:    "Sarah Okello",
    sourceReportId:   "PLR-2025W19-003",
    sourceLine:       "Authorise emergency transport advance for Western Team C.",
    assigneeRole:     "ProgramAccountant",
    assigneeName:     "Moses Tindi",
    deadline:         "2025-05-13",
    priority:         "Critical",
    status:           "In Progress",
    history: [
      { at: "2025-05-10 19:45", byRole: "CountryDirector",   byName: "Sarah Okello", event: "Decision created from PLR-2025W19-003 (Western Team C)" },
      { at: "2025-05-11 08:30", byRole: "ProgramAccountant", byName: "Moses Tindi",  event: "Acknowledged, sourcing funds" },
    ],
  },
  {
    id:               "DA-2025W19-002",
    title:            "Approve Maryhill partner certification review",
    description:      "Maryhill facilitator no-shows cancelled two cluster trainings (Central Team B). Need IA-led certification review before next cohort.",
    createdAt:        "2025-05-10 16:45",
    createdByRole:    "CountryDirector",
    createdByName:    "Sarah Okello",
    sourceReportId:   "PLR-2025W19-002",
    sourceLine:       "Authorise Maryhill partner certification review.",
    assigneeRole:     "ImpactAssessment",
    assigneeName:     "Grace Alimo",
    deadline:         "2025-05-20",
    priority:         "High",
    status:           "Pending",
    history: [
      { at: "2025-05-10 16:45", byRole: "CountryDirector", byName: "Sarah Okello", event: "Decision created from PLR-2025W19-002 (Central Team B)" },
    ],
  },
  {
    id:               "DA-2025W19-003",
    title:            "Approve replacement schools — Lamwo East closures",
    description:      "3 Lamwo East schools repeatedly closed during planned visits. Approve PL-proposed replacements in same district for Week 20.",
    createdAt:        "2025-05-10 18:10",
    createdByRole:    "CountryDirector",
    createdByName:    "Sarah Okello",
    sourceReportId:   "PLR-2025W19-001",
    sourceLine:       "Approve additional transport support for the Kitgum-Pader long-distance route.",
    assigneeRole:     "ProgramLead",
    assigneeName:     "Daniel Mwangi",
    deadline:         "2025-05-12",
    priority:         "High",
    status:           "Approved",
    history: [
      { at: "2025-05-10 18:10", byRole: "CountryDirector", byName: "Sarah Okello",   event: "Decision created from PLR-2025W19-001 (Northern Team A)" },
      { at: "2025-05-11 07:55", byRole: "CountryDirector", byName: "Sarah Okello",   event: "Approved replacement schools; PL to update Week 20 plan" },
    ],
  },
  {
    id:               "DA-2025W19-004",
    title:            "Schedule on-site review for 12 returned Salesforce records",
    description:      "Northern + Western teams have 11 returned records combined. Coordinate IA on-site visits to coach evidence formatting.",
    createdAt:        "2025-05-10 19:50",
    createdByRole:    "CountryDirector",
    createdByName:    "Sarah Okello",
    sourceReportId:   "PLR-2025W19-001",
    sourceLine:       "Request Impact Assessment review for the 4 returned Salesforce records.",
    assigneeRole:     "ImpactAssessment",
    assigneeName:     "Grace Alimo",
    deadline:         "2025-05-17",
    priority:         "High",
    status:           "In Progress",
    history: [
      { at: "2025-05-10 19:50", byRole: "CountryDirector",   byName: "Sarah Okello", event: "Decision created from PLR-2025W19-001 + PLR-2025W19-003" },
      { at: "2025-05-11 10:20", byRole: "ImpactAssessment", byName: "Grace Alimo",  event: "Site visits scheduled May 14–16" },
    ],
  },
  {
    id:               "DA-2025W19-005",
    title:            "Special Project coordinator: Mbarara catch-up plan",
    description:      "Mbarara East Comprehensive needs a special-attention plan. SPC to design joint coaching + SSA verification visit.",
    createdAt:        "2025-05-10 20:05",
    createdByRole:    "CountryDirector",
    createdByName:    "Sarah Okello",
    sourceReportId:   "PLR-2025W19-003",
    sourceLine:       "Approve special-attention plan for Mbarara East Comprehensive.",
    assigneeRole:     "SpecialProjectCoordinator",
    assigneeName:     "Joseph Kabuye",
    deadline:         "2025-05-19",
    priority:         "Medium",
    status:           "Pending",
    history: [
      { at: "2025-05-10 20:05", byRole: "CountryDirector", byName: "Sarah Okello", event: "Decision created from PLR-2025W19-003 (Western Team C)" },
    ],
  },
  {
    id:               "DA-2025W19-RVP-001",
    title:            "RVP review: Uganda Q2 funding pipeline gap",
    description:      "Country Director flagged repeated funding delays cascading into staff field-impact. RVP to review and authorise Q3 advance schedule.",
    createdAt:        "2025-05-11 08:00",
    createdByRole:    "RVP",
    createdByName:    "Esther Wanjiru",
    sourceReportId:   "CWFIR-2025W19",
    sourceLine:       "Funding pipeline drift across Western region.",
    assigneeRole:     "CountryDirector",
    assigneeName:     "Sarah Okello",
    deadline:         "2025-05-15",
    priority:         "High",
    status:           "Pending",
    history: [
      { at: "2025-05-11 08:00", byRole: "RVP", byName: "Esther Wanjiru", event: "Routed to CD from country intelligence report" },
    ],
  },
];

export function decisionActionsForAssignee(assigneeName: string): DecisionAction[] {
  return decisionActions.filter((d) => d.assigneeName === assigneeName);
}
export function decisionActionsForCreator(creatorName: string): DecisionAction[] {
  return decisionActions.filter((d) => d.createdByName === creatorName);
}
export function decisionActionsForReport(reportId: string): DecisionAction[] {
  return decisionActions.filter((d) => d.sourceReportId === reportId);
}

// ────────── Compile-from-debriefs (replaces hand-seeded numbers) ──────────
//
// Where the seeded report has hand-written numbers, the compile path
// derives the same numbers from the dailyDebriefs[] mock. For now it only
// powers the submission-rate truth-test on the report center; the rich
// narrative + decisions still come from the seeded objects (until each
// CCEO writes a real debrief).

export function compileSubmissionStats(plId: string, weekId: WeekId): {
  weekId:              WeekId;
  expectedDebriefs:    number;
  submittedDebriefs:   number;
  submissionRate:      number;
  contributingStaff:   string[];
} {
  // Demo-time: filter dailyDebriefs by PL; in production the week-window
  // filter joins on debrief.date ∈ [weekStart, weekEnd].
  const teamDebriefs = dailyDebriefs.filter((d) => d.programLeadId === plId);
  const contributing = Array.from(new Set(teamDebriefs.map((d) => d.staffName)));
  const expected     = Math.max(contributing.length, 6); // demo: assume 6/8 team size
  const submitted    = teamDebriefs.length;
  return {
    weekId,
    expectedDebriefs:  expected,
    submittedDebriefs: submitted,
    submissionRate:    expected === 0 ? 0 : Math.round((submitted / expected) * 100),
    contributingStaff: contributing,
  };
}

// ────────── HR + RVP aggregated views ──────────
//
// CD works with PL / IA / Program Accountant / Special Project Coordinator.
// RVP works with HR and CD. HR + RVP MUST NOT see named CCEOs or raw
// daily debrief content — only aggregated, anonymised barrier/support
// patterns and country-level decisions.

export type AggregatedFieldContext = {
  weekLabel:            string;
  totalDebriefsExpected: number;
  totalDebriefsSubmitted: number;
  debriefSubmissionRatePct: number;
  rawAchievementPct:    number;
  contextAdjustedAchievementPct: number;
  topBarriersByCategory: { category: string; occurrences: number }[];
  supportRequestThemes:  { theme: string; teamsAffected: number }[];
  teamHealth:            { team: string; status: "On Track" | "Needs Attention" | "Critical"; topBarrier?: string }[];
  // Sparse decisions, with assignee role only (no names exposed downstream).
  decisionsForReview:    { area: string; urgency: "Low" | "Medium" | "High" | "Critical" }[];
};

export function hrAggregatedFieldContext(): AggregatedFieldContext {
  const totals = programLeadWeeklyFieldReports.reduce(
    (a, r) => ({
      expected:  a.expected  + r.expectedDebriefs,
      submitted: a.submitted + r.submittedDebriefs,
    }),
    { expected: 0, submitted: 0 },
  );
  const barriers = new Map<string, number>();
  for (const r of programLeadWeeklyFieldReports) {
    for (const b of r.topBarriers) barriers.set(b.category, (barriers.get(b.category) ?? 0) + b.count);
  }
  const themes  = new Map<string, Set<string>>();
  for (const r of programLeadWeeklyFieldReports) {
    for (const s of r.staffSupportNeeds) {
      const theme = s.issue.split(/\s/).slice(0, 3).join(" ");
      if (!themes.has(theme)) themes.set(theme, new Set());
      themes.get(theme)!.add(r.team);
    }
  }
  return {
    weekLabel:                programLeadWeeklyFieldReports[0]?.weekLabel ?? "",
    totalDebriefsExpected:    totals.expected,
    totalDebriefsSubmitted:   totals.submitted,
    debriefSubmissionRatePct: Math.round((totals.submitted / totals.expected) * 100),
    rawAchievementPct:        countryWeeklyFieldIntelligence.countryRawAchievementPercent,
    contextAdjustedAchievementPct: countryWeeklyFieldIntelligence.countryContextAdjustedAchievementPercent,
    topBarriersByCategory:    Array.from(barriers.entries())
                                .map(([category, occurrences]) => ({ category, occurrences }))
                                .sort((a, b) => b.occurrences - a.occurrences),
    supportRequestThemes:     Array.from(themes.entries())
                                .map(([theme, teams]) => ({ theme, teamsAffected: teams.size }))
                                .sort((a, b) => b.teamsAffected - a.teamsAffected),
    teamHealth:               programLeadWeeklyFieldReports.map((r) => ({
      team:        r.team,
      status:      r.contextAdjustedAchievementPercent >= 85 ? "On Track"
                : r.contextAdjustedAchievementPercent >= 70 ? "Needs Attention"
                : "Critical",
      topBarrier:  r.topBarriers[0]?.category,
    })),
    decisionsForReview:       decisionActions
                                .filter((d) => d.status === "Pending" || d.status === "In Progress")
                                .map((d) => ({ area: d.title.split(" — ")[0], urgency: d.priority })),
  };
}

export function rvpCountrySummary(): AggregatedFieldContext & { country: string } {
  return {
    country: countryWeeklyFieldIntelligence.country,
    ...hrAggregatedFieldContext(),
  };
}

// Cross-dashboard summary used by callout cards
export function fieldIntelligenceSummaryFor(user: CurrentUser) {
  const visible = debriefsForUser(user);
  const r = rollup(visible);
  const patterns = detectRepeatedFieldBarriers(visible);
  return {
    debriefsThisWeek: visible.length,
    raw: r.raw,
    adjusted: r.adjusted,
    topBarrier: patterns[0]?.category,
    decisionCount: extractLeadershipDecisions(patterns).length,
    needsTodaysDebrief:
      user.role === "CCEO" &&
      !visible.some((d) => d.staffId === user.staffId && d.date === "2025-11-12"),
  };
}
