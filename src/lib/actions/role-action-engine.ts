// Role Action Engine — the single brain behind the 10-Second
// Command System.
//
// Given (role, current period, last-viewed timestamp), returns a
// fully-populated RoleActionBoard with:
//   - mission header (greeting + role mission + period + summary)
//   - top-3 next actions
//   - the full unified inbox (the UI's tabs filter, the engine doesn't)
//   - done-for-today checklist
//   - changes since last login
//
// Why one engine rather than per-role files:
//
//   1. ActionItem is the only type the UI knows. One engine →
//      one normalized stream. Adding a new source (e.g.
//      partner-onboarding alerts) means one new converter,
//      not 8 UI changes.
//   2. Priority ranking is consistent across roles — the same rule
//      decides what counts as "high" so a CCEO and a CPL don't
//      experience contradictory urgency cues.
//   3. Tests run against the engine, not the dashboard. Output is
//      pure data; UIs become trivial renderers.

import type {
  ActionItem,
  ActionAffected,
  DoneCheckItem,
  MissionHeader,
  RoleActionBoard,
} from "./action-types";
import type { EdifyRole } from "@/lib/auth-public";
import { classifyApprovalSafety } from "./approval-safety";
import { changesSince } from "./last-login";

// Imports from existing engines + mocks — the whole point is to reuse,
// not duplicate.
import {
  approvalQueue as cplApprovalQueue,
  urgentSchools as cplUrgentSchools,
} from "@/lib/cpl-mock";
import { staffTargetPerformance } from "@/lib/team-targets-mock";

// ────────── Helpers ──────────

function greetingForHour(h: number): string {
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

function isoIn(days: number, now: Date = new Date()): string {
  const d = new Date(now);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString();
}

function periodLabel(now: Date = new Date()): string {
  return now.toLocaleDateString("en-US", { month: "long", year: "numeric" });
}

// ────────── CCEO ──────────

function cceoBoard(name: string, now: Date, sinceCookie: Date | null): RoleActionBoard {
  const firstName = name.split(" ")[0];
  const header: MissionHeader = {
    greeting: `${greetingForHour(now.getUTCHours())}, ${firstName}.`,
    mission: "Walk the schools. Coach the teachers. Log it before sundown.",
    periodLabel: `${periodLabel(now)} · Week ${Math.ceil(now.getUTCDate() / 7)}`,
    summary: "You have 3 visits today, 1 pending fund slip, and 2 schools that haven't been touched this month.",
  };

  // Top 3 — handpicked from the canonical CCEO flow: visit → log → fund.
  const nextThree: ActionItem[] = [
    {
      id: "cceo-visit-today",
      role: "CCEO",
      priority: 1,
      category: "FieldVisit",
      title: "Visit Bright Future PS today (10:30)",
      description: "Closest school on your route; SSA is below 5 and no visit logged this month.",
      affectedEntity: { kind: "School", id: "S-GN-1", label: "Bright Future PS" },
      dueDate: now.toISOString(),
      riskLevel: "High",
      status: "Pending",
      approvalSafety: "SafeToApprove",
      primaryAction: { label: "Open route", intent: "open", href: "/route" },
      secondaryAction: { label: "Reschedule", intent: "open", href: "/my-plan" },
      sourceModule: "planning",
      inboxTab: "NeedsFollowUp",
    },
    {
      id: "cceo-week2-fund",
      role: "CCEO",
      priority: 2,
      category: "FundApproval",
      title: "Submit Week 2 fund slip (UGX 1.2M)",
      description: "Approved Monday; submit your receipts before Friday 17:00 or this week stays open.",
      affectedEntity: { kind: "Fund", id: "WFR-W2", label: "Week 2 fund slip", amountUgx: 1_200_000 },
      dueDate: isoIn(2, now),
      riskLevel: "Medium",
      status: "InProgress",
      approvalSafety: "SafeToApprove",
      primaryAction: { label: "Submit receipts", intent: "submit", href: "/weekly-funds" },
      secondaryAction: { label: "View slip", intent: "open", href: "/weekly-funds" },
      sourceModule: "weekly-funds",
      inboxTab: "NeedsFollowUp",
    },
    {
      id: "cceo-evidence-mukono",
      role: "CCEO",
      priority: 3,
      category: "EvidenceUpload",
      title: "Upload Evidence for 2 visits at Mukono Central",
      description: "Activities logged but photos / forms missing. They won't pass M&E verification without evidence.",
      affectedEntity: { kind: "School", id: "S-MK-1", label: "Mukono Central PS" },
      dueDate: isoIn(1, now),
      riskLevel: "Medium",
      status: "InProgress",
      approvalSafety: "SafeToApprove",
      primaryAction: { label: "Upload Evidence", intent: "submit", href: "/data-intake" },
      sourceModule: "data-intake",
      inboxTab: "NeedsFollowUp",
    },
  ];

  // Full inbox: the three above plus a Blocked + a Completed.
  const inbox: ActionItem[] = [
    ...nextThree,
    {
      id: "cceo-debrief",
      role: "CCEO",
      priority: 4,
      category: "Debrief",
      title: "Daily debrief — Tuesday",
      description: "Today's debrief is open. Two lines on what you saw is enough.",
      affectedEntity: { kind: "Activity", id: "DB-TUE", label: "Tuesday debrief" },
      dueDate: now.toISOString(),
      riskLevel: "Low",
      status: "Pending",
      approvalSafety: "SafeToApprove",
      primaryAction: { label: "Write debrief", intent: "submit", href: "/today" },
      sourceModule: "data-intake",
      inboxTab: "NeedsApproval",
    },
    {
      id: "cceo-blocked-funds",
      role: "CCEO",
      priority: 5,
      category: "FundApproval",
      title: "Week 3 fund slip is blocked",
      description: "Prior week not closed — once Week 2 receipts land, Week 3 unlocks automatically.",
      affectedEntity: { kind: "Fund", id: "WFR-W3", label: "Week 3 fund slip" },
      riskLevel: "Medium",
      status: "AwaitingOther",
      approvalSafety: "Blocked",
      primaryAction: { label: "See blocker", intent: "open", href: "/weekly-funds" },
      sourceModule: "weekly-funds",
      inboxTab: "Blocked",
    },
    {
      id: "cceo-done-1",
      role: "CCEO",
      priority: 5,
      category: "FieldVisit",
      title: "Visit logged: St. Mary's PS",
      description: "Activity verified and Salesforce-matched this morning. Nothing else needed.",
      affectedEntity: { kind: "School", id: "S-SM-1", label: "St. Mary's PS" },
      riskLevel: "Low",
      status: "Completed",
      approvalSafety: "SafeToApprove",
      primaryAction: { label: "View", intent: "open", href: "/queue" },
      sourceModule: "planning",
      inboxTab: "CompletedToday",
    },
    // Partner-derived items — the spec's rule: partner work flows
    // into staff dashboards in the right places (joint-work the
    // CCEO is observer on; follow-ups partners requested after
    // their trainings in this CCEO's schools).
    ...partnerItemsForCceo(now),
    // SSA-driven recommendations — turn weak-area signals into
    // concrete "Add to plan" actions the CCEO can accept in one click.
    ...ssaRecommendationsForCceo(),
  ];

  const doneToday: DoneCheckItem[] = [
    { id: "today-visit",    label: "Today's visit logged",              satisfiedWhen: "an Activity created for today by the user", done: false, detail: "0 of 1 today" },
    { id: "today-evidence", label: "Evidence uploaded for today's work", satisfiedWhen: "every logged activity has at least one attachment", done: false, detail: "0 of 1" },
    { id: "today-funds",    label: "Week 2 fund slip submitted",        satisfiedWhen: "the active week's fund request is in AccountabilitySubmitted+", done: false },
    { id: "today-debrief",  label: "Daily debrief sent",                satisfiedWhen: "today's debrief record exists", done: false },
  ];

  return {
    role: "CCEO",
    header,
    nextThree,
    inbox,
    doneToday,
    changedSince: changesSince(sinceCookie, "CCEO", now),
  };
}

// ────────── Country Program Lead ──────────

function cplBoard(name: string, now: Date, sinceCookie: Date | null): RoleActionBoard {
  const firstName = name.split(" ")[0];
  const header: MissionHeader = {
    greeting: `${greetingForHour(now.getUTCHours())}, ${firstName}.`,
    mission: "Coach the field. Close the gaps. Multiply the wins.",
    periodLabel: periodLabel(now),
    summary: "5 plans are safe to approve, 1 staff has dropped to Critical pace, and 3 schools moved to High Risk overnight.",
  };

  // Convert the CPL approval queue into ActionItem[], running each
  // through the safety classifier. The mock data doesn't have rich
  // safety inputs yet — we synthesise based on the "issues" string.
  const approvalActions: ActionItem[] = cplApprovalQueue.slice(0, 6).map<ActionItem>((row, idx) => {
    const hasIssue = row.issues.length > 0;
    const safety = classifyApprovalSafety({
      kind: "MonthlyPlan",
      costSettingsActive: true,
      blockingValidationFlags: row.issues.includes("Attachments Missing") ? ["Attachments Missing"] : [],
      nonBlockingValidationFlags: row.issues.filter((i) => i !== "Attachments Missing"),
      isFirstTimeWithActor: false,
    });
    const affected: ActionAffected = { kind: "Plan", id: row.id, label: `${row.staff}'s May plan` };
    return {
      id: `cpl-plan-${row.id}`,
      role: "CountryProgramLead",
      priority: hasIssue ? 3 : 2,
      category: "PlanApproval",
      title: `Approve ${row.staff}'s May plan`,
      description: hasIssue
        ? `Submitted ${row.submitted}. Flagged: ${row.issues.join(", ")}.`
        : `Submitted ${row.submitted}. ${row.activitiesCovered}. Passes all checks.`,
      affectedEntity: affected,
      dueDate: isoIn(2 - idx, now),
      riskLevel: hasIssue ? "Medium" : "Low",
      status: "Pending",
      approvalSafety: safety.safety,
      primaryAction: { label: row.primary, intent: row.primary === "Approve" ? "approve" : "review", href: "/approvals" },
      secondaryAction: { label: "Open detail", intent: "open", href: "/approvals" },
      sourceModule: "planning",
      // Blocked items go to the Blocked tab regardless of the source
      // category — the contract is that Blocked is the system's way of
      // saying "stop, fix this first."
      inboxTab: safety.safety === "Blocked" ? "Blocked" : "NeedsApproval",
    };
  });

  // Behind-pace staff from team-targets-mock.
  const behindStaff = staffTargetPerformance
    .filter((s) => s.achievementPercent < 70)
    .slice(0, 3);
  const staffActions: ActionItem[] = behindStaff.map((s, i) => ({
    id: `cpl-staff-${s.staffId}`,
    role: "CountryProgramLead",
    priority: s.achievementPercent < 40 ? 1 : 2,
    category: "StaffSupport",
    title: `${s.staffName} is at ${s.achievementPercent}% pace`,
    description: s.achievementPercent < 40
      ? "Mid-year still below 40% across every major category. Schedule a support conversation."
      : "Below the 70% threshold for two consecutive weeks. Worth a check-in before it slides further.",
    affectedEntity: { kind: "Staff", id: s.staffId, label: s.staffName },
    dueDate: isoIn(i + 1, now),
    riskLevel: s.achievementPercent < 40 ? "Critical" : "High",
    status: "Pending",
    approvalSafety: "NeedsReview",
    primaryAction: { label: "Open coaching plan", intent: "review", href: "/team-targets" },
    secondaryAction: { label: "View pace detail", intent: "open", href: "/team-targets" },
    sourceModule: "team-targets",
    inboxTab: "NeedsReview",
  }));

  // High-risk schools.
  const schoolActions: ActionItem[] = cplUrgentSchools.slice(0, 3).map((sc) => ({
    id: `cpl-school-${sc.id}`,
    role: "CountryProgramLead",
    priority: sc.risk === "High" ? 2 : 3,
    category: "SchoolRisk",
    title: `${sc.school} is High Risk`,
    description: `SSA ${sc.ssaScore} · ${sc.issue} · ${sc.district} District. Assign a visit this week.`,
    affectedEntity: { kind: "School", id: sc.id, label: sc.school },
    dueDate: isoIn(4, now),
    riskLevel: sc.risk === "High" ? "High" : "Medium",
    status: "Pending",
    approvalSafety: "NeedsReview",
    primaryAction: { label: "Assign visit", intent: "review", href: "/route" },
    secondaryAction: { label: "Open school", intent: "open", href: "/schools" },
    sourceModule: "ssa",
    inboxTab: "NeedsFollowUp",
  }));

  // Blocked example — funds blocked by prior-week dependency.
  const blockedAction: ActionItem = {
    id: "cpl-blocked-week3",
    role: "CountryProgramLead",
    priority: 4,
    category: "FundApproval",
    title: "3 Week 3 fund slips waiting on Week 2 accountability",
    description: "Engine will unblock automatically once Grace, James, and Purity close Week 2. No PL action needed yet.",
    affectedEntity: { kind: "System", id: "cpl-blocked-week3", label: "Week 3 queue" },
    riskLevel: "Low",
    status: "AwaitingOther",
    approvalSafety: "Blocked",
    primaryAction: { label: "Notify staff", intent: "review", href: "/weekly-funds" },
    sourceModule: "weekly-funds",
    inboxTab: "Blocked",
  };

  const completedToday: ActionItem = {
    id: "cpl-completed-1",
    role: "CountryProgramLead",
    priority: 5,
    category: "PlanApproval",
    title: "Approved: Esther Adong's May plan",
    description: "Cleared this morning. UGX 3.8M flowing into the fund queue.",
    affectedEntity: { kind: "Plan", id: "ap-1", label: "Esther Adong's May plan" },
    riskLevel: "Low",
    status: "Completed",
    approvalSafety: "SafeToApprove",
    primaryAction: { label: "View", intent: "open", href: "/approvals" },
    sourceModule: "planning",
    inboxTab: "CompletedToday",
  };

  const allItems: ActionItem[] = [
    ...staffActions,
    ...approvalActions,
    ...schoolActions,
    blockedAction,
    completedToday,
    // Partner work that needs CPL eyes — patterns of returns or
    // partner-supported schools still at risk. The spec is explicit:
    // partner coverage, gaps, and risks appear on the CPL dashboard.
    ...partnerItemsForCpl(now),
    // Workload-guardrail signals — flag staff approaching healthy
    // load thresholds so the CPL can rebalance before pace drops.
    // Phrased as "recommend support", not as performance critique.
    ...workloadRiskItemsForCpl(now),
  ];
  const nextThree = [...allItems]
    .filter((i) => i.status !== "Completed" && i.approvalSafety !== "Blocked")
    .sort((a, b) => a.priority - b.priority)
    .slice(0, 3);

  const doneToday: DoneCheckItem[] = [
    { id: "cpl-safe",       label: "Safe-to-approve plans cleared",     satisfiedWhen: "all PlanApproval items with SafeToApprove are resolved", done: false, detail: `0 of ${approvalActions.filter((a) => a.approvalSafety === "SafeToApprove").length} cleared` },
    { id: "cpl-returns",    label: "Blocked plans returned with reason", satisfiedWhen: "every Blocked plan in the inbox has a returnedReason", done: false },
    { id: "cpl-staff",      label: "Behind-pace staff reviewed",         satisfiedWhen: "every staff at <70% has a SupportReview record from this week", done: false, detail: `${behindStaff.length} staff to review` },
    { id: "cpl-school",     label: "High-risk schools triaged",          satisfiedWhen: "every High-Risk school has at least one planned visit this week", done: false, detail: `${cplUrgentSchools.length} schools` },
    { id: "cpl-debrief",    label: "Field intelligence reviewed",        satisfiedWhen: "today's submitted debriefs marked Read", done: false },
  ];

  return {
    role: "CountryProgramLead",
    header,
    nextThree,
    inbox: allItems,
    doneToday,
    changedSince: changesSince(sinceCookie, "CountryProgramLead", now),
  };
}

// ────────── Country Director ──────────

function cdBoard(name: string, now: Date, sinceCookie: Date | null): RoleActionBoard {
  const firstName = name.split(" ")[0];
  const header: MissionHeader = {
    greeting: `${greetingForHour(now.getUTCHours())}, ${firstName}.`,
    mission: "Hold the line on quality. Sign off what's ready. Protect the field.",
    periodLabel: periodLabel(now),
    summary: "Cost-settings for Q2 are still Draft, 12 PL-approved plans await your final sign-off, and one district's SSA dropped 8pp this week.",
  };

  const inbox: ActionItem[] = [
    {
      id: "cd-cost-settings",
      role: "CountryDirector",
      priority: 1,
      category: "CostSettings",
      title: "Activate Q2 cost-settings",
      description: "Plans approved by PLs cannot move to funding until Q2 rates are Active. This is the single biggest unblocker on your queue.",
      affectedEntity: { kind: "Country", id: "UG", label: "Uganda · Q2 cost-settings" },
      dueDate: isoIn(0, now),
      riskLevel: "Critical",
      status: "Pending",
      approvalSafety: "SafeToApprove",
      primaryAction: { label: "Review and activate", intent: "approve", href: "/cost-settings" },
      secondaryAction: { label: "See plans blocked", intent: "open", href: "/approvals" },
      sourceModule: "cost-settings",
      inboxTab: "NeedsApproval",
    },
    {
      id: "cd-final-signoff",
      role: "CountryDirector",
      priority: 2,
      category: "FundApproval",
      title: "Final sign-off: 12 PL-approved plans · UGX 38M",
      description: "PL approval is complete on all 12. None over the 10% tolerance. Safe to bulk-approve.",
      affectedEntity: { kind: "Fund", id: "cd-batch-may", label: "12 May plans · UGX 38M", amountUgx: 38_000_000 },
      dueDate: isoIn(1, now),
      riskLevel: "High",
      status: "Pending",
      approvalSafety: "SafeToApprove",
      primaryAction: { label: "Bulk approve 12", intent: "approve", href: "/approvals" },
      secondaryAction: { label: "Open Queue", intent: "open", href: "/approvals" },
      sourceModule: "fund-approvals",
      inboxTab: "NeedsApproval",
    },
    {
      id: "cd-cert",
      role: "CountryDirector",
      priority: 3,
      category: "CertifyData",
      title: "Certify April data quality",
      description: "M&E has cleared the queue. Your signature closes the month and unlocks RVP-level reporting.",
      affectedEntity: { kind: "Country", id: "UG-APR", label: "Uganda · April 2026 data" },
      dueDate: isoIn(3, now),
      riskLevel: "Medium",
      status: "Pending",
      approvalSafety: "NeedsReview",
      primaryAction: { label: "Open certification", intent: "review", href: "/quality-checks" },
      sourceModule: "data-intake",
      inboxTab: "NeedsApproval",
    },
    {
      id: "cd-district-risk",
      role: "CountryDirector",
      priority: 3,
      category: "SchoolRisk",
      title: "Kitgum District SSA dropped 8pp this week",
      description: "Four schools moved Critical. Worth a call with the regional PL today.",
      affectedEntity: { kind: "District", id: "kitgum", label: "Kitgum District" },
      dueDate: isoIn(1, now),
      riskLevel: "High",
      status: "Pending",
      approvalSafety: "NeedsReview",
      primaryAction: { label: "Open District view", intent: "review", href: "/ssa" },
      sourceModule: "ssa",
      inboxTab: "NeedsReview",
    },
    {
      id: "cd-rvp-clarification",
      role: "CountryDirector",
      priority: 4,
      category: "FundApproval",
      title: "RVP has questions on the May funding envelope",
      description: "Esther asked for variance commentary on the 7% over-plan delta. Reply before tomorrow's regional call.",
      affectedEntity: { kind: "Fund", id: "may-envelope", label: "May envelope · UGX 142M", amountUgx: 142_000_000 },
      dueDate: isoIn(1, now),
      riskLevel: "Medium",
      status: "AwaitingOther",
      approvalSafety: "NeedsReview",
      primaryAction: { label: "Reply with commentary", intent: "review", href: "/funds/approvals" },
      sourceModule: "fund-approvals",
      inboxTab: "NeedsFollowUp",
    },
    {
      id: "cd-blocked-sf",
      role: "CountryDirector",
      priority: 5,
      category: "DataVerification",
      title: "3 plans waiting on M&E quality check",
      description: "M&E queue is busy; no CD action available until they clear. You'll be notified when ready.",
      affectedEntity: { kind: "System", id: "cd-blocked-sf", label: "Q1 data certification queue" },
      riskLevel: "Low",
      status: "AwaitingOther",
      approvalSafety: "Blocked",
      primaryAction: { label: "See queue", intent: "open", href: "/data-verification" },
      sourceModule: "data-intake",
      inboxTab: "Blocked",
    },
    {
      id: "cd-done-1",
      role: "CountryDirector",
      priority: 5,
      category: "FundApproval",
      title: "Signed: West region April envelope · UGX 28M",
      description: "Cleared at 09:14. Funds released to accountant queue.",
      affectedEntity: { kind: "Fund", id: "west-apr", label: "West · April · UGX 28M", amountUgx: 28_000_000 },
      riskLevel: "Low",
      status: "Completed",
      approvalSafety: "SafeToApprove",
      primaryAction: { label: "View", intent: "open", href: "/approvals" },
      sourceModule: "fund-approvals",
      inboxTab: "CompletedToday",
    },
  ];

  const nextThree = [...inbox]
    .filter((i) => i.status !== "Completed" && i.approvalSafety !== "Blocked")
    .sort((a, b) => a.priority - b.priority)
    .slice(0, 3);

  const doneToday: DoneCheckItem[] = [
    { id: "cd-costsettings", label: "Q2 cost-settings activated", satisfiedWhen: "CostSetting.status = Active for the current FY-quarter", done: false },
    { id: "cd-signoff",      label: "PL-approved plans signed",   satisfiedWhen: "all SafeToApprove FundApproval items resolved",              done: false, detail: "0 of 12 cleared" },
    { id: "cd-cert",         label: "Data certification reviewed", satisfiedWhen: "DataCertification action resolved or deferred",             done: false },
    { id: "cd-district",     label: "Risk districts reviewed",     satisfiedWhen: "every district >5pp drop has a noted action",               done: false, detail: "1 of 1" },
  ];

  return {
    role: "CountryDirector",
    header,
    nextThree,
    inbox,
    doneToday,
    changedSince: changesSince(sinceCookie, "CountryDirector", now),
  };
}

// ────────── Partner boards (Operating Layer) ──────────
//
// The three partner user types share the same engine entry — what
// varies is which actions are surfaced. PartnerAdmin sees plans,
// returns, and impact; PartnerFieldOfficer sees today's activities;
// PartnerViewer sees only verified items + no CTAs.

import { partnerActivities, partnerUserByEmail, partnerById } from "@/lib/partner/partner-mock";
import type { PartnerUserType, PartnerActivity } from "@/lib/partner/partner-types";

// ────────── SimpleHealthyFocused engines ──────────
//
// Workload-guardrails + SSA-driven planning feed ActionItems into
// the right roles' boards. The product principle: surface workload
// risk on HR + CPL so leadership notices burnout BEFORE the system
// penalises the staff for what the load made impossible.

import { detectWorkloadFlags, recommendInterventions, type WorkloadDetectionInput } from "@/lib/workload/workload-guardrails";
import { recommendedActionsForPortfolio, type SsaSchoolSnapshot } from "@/lib/ssa-planning/ssa-planning";

// Hand-tuned snapshot for the demo CCEO (Paul Chinyama). In production
// these come from the FWI portfolio + planning data joins.
const DEMO_CCEO_WORKLOAD_INPUT: WorkloadDetectionInput = {
  staffId: "STF-PC-001",
  staffName: "Paul Chinyama",
  portfolio: {
    staffId: "STF-PC-001",
    staffName: "Paul Chinyama",
    periodIso: "2026-05",
    schoolCount: 44, partnerSchoolCount: 10, districtCount: 5,
    secondaryDistrictCount: 3, highRiskSchoolCount: 8,
    avgSsaWeakness: 6.5, avgDistanceKm: 88, hotelTripsCount: 6,
    totalTravelKm: 1680, partnersManaged: 3, specialProjectsActive: 1,
  },
  pendingTaskCount: 12,
  specialProjectsActive: 1,
  avgDailyTravelKm: 92,
  targetRatioVsMedian: 1.15,
};

// Hand-tuned weak-area snapshots for the CCEO inbox (SSA recs).
const DEMO_SSA_SNAPSHOTS: SsaSchoolSnapshot[] = [
  {
    schoolId: "SCH-GN-3", schoolName: "Sunrise School",
    districtId: "DST-KITGUM",
    ssaScore: 4.4, weakestArea: "TeachingAndLearning",
    weakestAreaScore: 3.2, daysSinceLastSupportInArea: 78,
    assignedCceoId: "STF-PC-001",
  },
  {
    schoolId: "SCH-GN-4", schoolName: "Kapchorwa Comm. PS",
    districtId: "DST-LAMWO",
    ssaScore: 5.6, weakestArea: "LearningEnvironment",
    weakestAreaScore: 4.8, daysSinceLastSupportInArea: 35,
    assignedCceoId: "STF-PC-001",
  },
];

// Workload risk → ActionItem for HR + CPL.
function workloadRiskItemsForCpl(now: Date): ActionItem[] {
  const flags = detectWorkloadFlags(DEMO_CCEO_WORKLOAD_INPUT);
  const recs  = recommendInterventions(DEMO_CCEO_WORKLOAD_INPUT, flags);
  if (recs.length === 0) return [];
  const top = recs[0];
  return [{
    id: `cpl-workload-${DEMO_CCEO_WORKLOAD_INPUT.staffId}`,
    role: "CountryProgramLead",
    priority: 2,
    category: "StaffSupport",
    title: `${DEMO_CCEO_WORKLOAD_INPUT.staffName} is carrying heavy load`,
    description: `${flags.length} workload flag${flags.length === 1 ? "" : "s"} active. Recommended: ${top.message}`,
    affectedEntity: { kind: "Staff", id: DEMO_CCEO_WORKLOAD_INPUT.staffId, label: DEMO_CCEO_WORKLOAD_INPUT.staffName },
    dueDate: new Date(now.getTime() + 3 * 86400_000).toISOString(),
    riskLevel: "High",
    status: "Pending",
    approvalSafety: "NeedsReview",
    primaryAction: { label: "Review portfolio", intent: "review", href: "/team-targets" },
    secondaryAction: { label: "See workload detail", intent: "open", href: "/team-targets" },
    sourceModule: "workload-guardrails",
    inboxTab: "NeedsReview",
    isWorkloadRisk: true,
    affectedStaff: DEMO_CCEO_WORKLOAD_INPUT.staffName,
  }];
}

function workloadRiskItemsForHr(now: Date): ActionItem[] {
  const flags = detectWorkloadFlags(DEMO_CCEO_WORKLOAD_INPUT);
  if (flags.length === 0) return [];
  return [{
    id: `hr-workload-${DEMO_CCEO_WORKLOAD_INPUT.staffId}`,
    role: "HumanResource",
    priority: 1,
    category: "StaffSupport",
    title: `Workload guardrail: ${DEMO_CCEO_WORKLOAD_INPUT.staffName}`,
    description: `Healthy thresholds crossed on ${flags.length} dimension${flags.length === 1 ? "" : "s"}. Recommend supportive conversation, not performance review.`,
    affectedEntity: { kind: "Staff", id: DEMO_CCEO_WORKLOAD_INPUT.staffId, label: DEMO_CCEO_WORKLOAD_INPUT.staffName },
    dueDate: new Date(now.getTime() + 2 * 86400_000).toISOString(),
    riskLevel: "High",
    status: "Pending",
    approvalSafety: "NeedsReview",
    primaryAction: { label: "Open support workflow", intent: "review", href: "/team-targets" },
    sourceModule: "workload-guardrails",
    inboxTab: "NeedsReview",
    isWorkloadRisk: true,
    affectedStaff: DEMO_CCEO_WORKLOAD_INPUT.staffName,
  }];
}

// SSA-driven recommendations for the CCEO inbox.
function ssaRecommendationsForCceo(): ActionItem[] {
  // Cap to 2 to avoid swamping the inbox.
  return recommendedActionsForPortfolio(DEMO_SSA_SNAPSHOTS)
    .slice(0, 2)
    .map((item) => ({
      ...item,
      // Annotate the new SHF flags for downstream digest filtering.
      isSchoolFacing: true,
      schoolSupportArea: item.id.includes("LearningEnvironment")
        ? "LearningEnvironment"
        : "TeachingAndLearning",
    }));
}

// ────────── Cross-role partner integration ──────────
//
// The Partner Operating Layer spec is explicit: partner work flows
// into staff dashboards in the right places, not into a separate
// side module. These three helpers convert partner activities into
// ActionItems for CCEO, CPL, and M&E boards.
//
// Reusable across boards — each board calls the helper and merges
// the returned items into its own inbox. The Next-3 ranking then
// considers partner items alongside staff items naturally.

function partnerItemsForCceo(now: Date): ActionItem[] {
  const out: ActionItem[] = [];
  // Partner follow-up requests pointing at CCEO follow-up.
  for (const a of partnerActivities.filter((p) => p.followUpRequested?.kind === "CceoFollowUpVisit").slice(0, 2)) {
    const partner = partnerById(a.partnerId);
    out.push({
      id: `cceo-partner-followup-${a.id}`,
      role: "CCEO",
      priority: 2,
      category: "FieldVisit",
      title: `Follow Up: ${a.schoolName} (after ${partner?.shortName ?? "partner"} training)`,
      description: a.followUpRequested?.reason ?? "Partner has requested CCEO follow-up after their activity.",
      affectedEntity: { kind: "School", id: a.schoolId, label: a.schoolName },
      dueDate: a.followUpRequested?.byDate ?? isoIn(7, now),
      riskLevel: "Medium", status: "Pending", approvalSafety: "NeedsReview",
      primaryAction: { label: "Schedule visit", intent: "submit", href: "/route" },
      secondaryAction: { label: "Open partner activity", intent: "open", href: "/dashboards/partner" },
      sourceModule: "planning",
      inboxTab: "NeedsFollowUp",
    });
  }
  // Joint-work activities where the CCEO is an observer.
  for (const a of partnerActivities.filter((p) => p.jointWorkId).slice(0, 2)) {
    const partner = partnerById(a.partnerId);
    out.push({
      id: `cceo-partner-joint-${a.id}`,
      role: "CCEO",
      priority: 3,
      category: "FieldVisit",
      title: `Joint visit with ${partner?.shortName ?? "partner"}: ${a.schoolName}`,
      description: `You're listed as observer on this ${humaniseKind(a.kind)}. Confirm date + arrive prepared with the joint checklist.`,
      affectedEntity: { kind: "Activity", id: a.id, label: a.schoolName },
      dueDate: a.scheduledDate, riskLevel: "Low", status: "Pending", approvalSafety: "SafeToApprove",
      primaryAction: { label: "Open joint checklist", intent: "open", href: "/dashboards/partner" },
      sourceModule: "planning",
      inboxTab: "NeedsFollowUp",
    });
  }
  return out;
}

function partnerItemsForCpl(now: Date): ActionItem[] {
  const out: ActionItem[] = [];
  // Returned-for-correction partner activities — CPL needs to know
  // when a partner is producing repeat-rejected work (informs the
  // partner-review conversation).
  const returned = partnerActivities.filter((p) => p.verificationStatus === "ReturnedForCorrection");
  if (returned.length > 0) {
    const partner = partnerById(returned[0].partnerId);
    out.push({
      id: `cpl-partner-returned-${returned[0].id}`,
      role: "CountryProgramLead",
      priority: 3, category: "DataVerification",
      title: `${partner?.shortName ?? "Partner"} has ${returned.length} returned submissions`,
      description: `M&E returned ${returned.length} ${partner?.shortName ?? "partner"} activit${returned.length === 1 ? "y" : "ies"} this period. Worth a partner-review meeting if the pattern continues.`,
      affectedEntity: { kind: "System", id: `partner-returned-${returned[0].partnerId}`, label: partner?.name ?? "Partner" },
      dueDate: isoIn(2, now), riskLevel: "Medium", status: "Pending", approvalSafety: "NeedsReview",
      primaryAction: { label: "Open partner dashboard", intent: "open", href: "/dashboards/partner" },
      sourceModule: "ssa",
      inboxTab: "NeedsReview",
    });
  }
  return out;
}

function partnerItemsForMe(now: Date): ActionItem[] {
  const out: ActionItem[] = [];
  const pending = partnerActivities.filter((p) => p.verificationStatus === "UnderReview" || p.verificationStatus === "EvidenceMissing" && p.status === "Completed");
  if (pending.length > 0) {
    out.push({
      id: `me-partner-queue`,
      role: "ImpactAssessment",
      priority: 1, category: "DataVerification",
      title: `${pending.length} partner submission${pending.length === 1 ? "" : "s"} awaiting verification`,
      description: `Partner activities flow through the same verification queue as staff activities. None can count toward national targets until you clear them.`,
      affectedEntity: { kind: "System", id: "me-partner-queue", label: "Partner verification queue" },
      dueDate: isoIn(1, now), riskLevel: "High", status: "Pending", approvalSafety: "NeedsReview",
      primaryAction: { label: "Open verification queue", intent: "review", href: "/data-verification" },
      sourceModule: "data-intake",
      inboxTab: "NeedsReview",
    });
  }
  // Fraud-flagged partner activities — Spot Check escalation.
  const flagged = partnerActivities.filter((p) => p.fraudFlags.length > 0);
  if (flagged.length > 0) {
    out.push({
      id: `me-partner-flagged`,
      role: "ImpactAssessment",
      priority: 1, category: "DataVerification",
      title: `${flagged.length} partner activity flagged for Spot Check`,
      description: `Possible duplicate or out-of-scope work detected. Marked Needs Review — never auto-rejected; your judgment closes it out.`,
      affectedEntity: { kind: "System", id: "me-partner-flagged", label: "Spot-check queue" },
      dueDate: isoIn(0, now), riskLevel: "Critical", status: "Pending", approvalSafety: "NeedsReview",
      primaryAction: { label: "Open Spot Check queue", intent: "review", href: "/data-verification" },
      sourceModule: "data-intake",
      inboxTab: "NeedsReview",
    });
  }
  return out;
}

function humaniseKind(k: PartnerActivity["kind"]): string {
  return k.replace(/([A-Z])/g, " $1").trim().toLowerCase();
}

// ────────── Partner boards (Operating Layer) ──────────

function partnerBoard(
  email: string,
  name: string,
  userType: PartnerUserType,
  now: Date,
  sinceCookie: Date | null,
): RoleActionBoard {
  const partnerUser = partnerUserByEmail(email);
  const partnerId = partnerUser?.partnerId ?? "P-LIT";
  const partnerName = partnerId === "P-LIT" ? "Literacy Training Uganda" : "Numeracy First";
  const allActivities = partnerActivities.filter((a) => a.partnerId === partnerId);
  const firstName = name.split(" ")[0];

  // Headline summary: tally the inbox-worthy items.
  const evidenceMissing = allActivities.filter((a) => a.verificationStatus === "EvidenceMissing" && a.status === "Completed");
  const returned        = allActivities.filter((a) => a.verificationStatus === "ReturnedForCorrection");
  const scheduledSoon   = allActivities.filter((a) => a.status === "Scheduled" && Date.parse(a.scheduledDate) <= now.getTime() + 7 * 86400_000);
  const followUps       = allActivities.filter((a) => a.followUpRequested && a.followUpRequested.kind !== "None");

  const header: MissionHeader = {
    greeting: `${greetingForHour(now.getUTCHours())}, ${firstName}.`,
    mission: userType === "PartnerViewer"
      ? "See what's been delivered, verified, and improving."
      : "Deliver verified school support. Close gaps. Prove impact.",
    periodLabel: `${periodLabel(now)} · ${partnerName}`,
    summary: userType === "PartnerViewer"
      ? `${allActivities.filter((a) => a.verificationStatus === "Counted" || a.verificationStatus === "Verified").length} verified activities this period; you can review all approved reports.`
      : `${scheduledSoon.length} activities scheduled this week, ${returned.length} returned for correction, ${evidenceMissing.length} waiting on evidence.`,
  };

  // ─── Build inbox actions ───
  const inbox: ActionItem[] = [];

  // Returned-for-correction items — highest priority (the partner is blocking themselves).
  for (const a of returned.slice(0, 4)) {
    inbox.push({
      id: `pa-returned-${a.id}`,
      role: userType === "PartnerAdmin" ? "PartnerAdmin" : userType === "PartnerFieldOfficer" ? "PartnerFieldOfficer" : "PartnerViewer",
      priority: 1, category: "DataVerification",
      title: `Fix returned activity: ${a.title}`,
      description: `M&E returned this for correction. Until it's resolved, the activity doesn't count toward your verified delivery.`,
      affectedEntity: { kind: "Activity", id: a.id, label: a.schoolName },
      dueDate: isoIn(2, now), riskLevel: "High", status: "Pending",
      approvalSafety: "NeedsReview",
      primaryAction: { label: userType === "PartnerViewer" ? "View" : "Open correction", intent: userType === "PartnerViewer" ? "open" : "submit", href: "/dashboards/partner" },
      sourceModule: "data-intake",
      inboxTab: userType === "PartnerViewer" ? "NeedsFollowUp" : "NeedsReview",
    });
  }

  // Evidence missing — Field Officer top action.
  for (const a of evidenceMissing.slice(0, 3)) {
    inbox.push({
      id: `pa-evidence-${a.id}`,
      role: userType === "PartnerAdmin" ? "PartnerAdmin" : "PartnerFieldOfficer",
      priority: 2, category: "EvidenceUpload",
      title: `Upload Evidence: ${a.title}`,
      description: `Activity completed but required evidence is missing. Verification can't start.`,
      affectedEntity: { kind: "Activity", id: a.id, label: a.schoolName },
      dueDate: isoIn(1, now), riskLevel: "Medium", status: "InProgress",
      approvalSafety: userType === "PartnerViewer" ? "Blocked" : "SafeToApprove",
      primaryAction: { label: "Upload Evidence", intent: "submit", href: "/dashboards/partner" },
      sourceModule: "data-intake",
      inboxTab: userType === "PartnerViewer" ? "Blocked" : "NeedsFollowUp",
    });
  }

  // Scheduled activities this week.
  for (const a of scheduledSoon.slice(0, 3)) {
    inbox.push({
      id: `pa-scheduled-${a.id}`,
      role: userType === "PartnerAdmin" ? "PartnerAdmin" : "PartnerFieldOfficer",
      priority: 3, category: "FieldVisit",
      title: `${a.title}`,
      description: `Scheduled at ${a.schoolName} (${a.districtId}). ${a.jointWorkId ? "Joint activity — Edify staff is also assigned." : "Partner-led."}`,
      affectedEntity: { kind: "Activity", id: a.id, label: a.schoolName },
      dueDate: a.scheduledDate, riskLevel: "Low", status: "Pending",
      approvalSafety: "SafeToApprove",
      primaryAction: { label: "Open activity", intent: "open", href: "/dashboards/partner" },
      sourceModule: "planning",
      inboxTab: "NeedsFollowUp",
    });
  }

  // Follow-Up requests (cross-handoff with staff — partner sees their own).
  for (const a of followUps.slice(0, 2)) {
    inbox.push({
      id: `pa-followup-${a.id}`,
      role: userType === "PartnerAdmin" ? "PartnerAdmin" : "PartnerFieldOfficer",
      priority: 3, category: "FieldVisit",
      title: `Follow-Up due: ${a.schoolName}`,
      description: a.followUpRequested?.reason ?? "Follow-Up requested after partner activity.",
      affectedEntity: { kind: "School", id: a.schoolId, label: a.schoolName },
      dueDate: a.followUpRequested?.byDate ?? isoIn(7, now),
      riskLevel: "Medium", status: "Pending", approvalSafety: "NeedsReview",
      primaryAction: { label: "Schedule follow-up", intent: "submit", href: "/dashboards/partner" },
      sourceModule: "planning",
      inboxTab: "NeedsFollowUp",
    });
  }

  // Recently verified completed item, so the Completed Today tab has something.
  const recentlyCounted = allActivities.find((a) => a.verificationStatus === "Counted");
  if (recentlyCounted) {
    inbox.push({
      id: `pa-counted-${recentlyCounted.id}`,
      role: userType === "PartnerAdmin" ? "PartnerAdmin" : "PartnerFieldOfficer",
      priority: 5, category: "DataVerification",
      title: `Counted: ${recentlyCounted.title}`,
      description: `M&E verified and counted. Visible on the partner impact dashboard.`,
      affectedEntity: { kind: "School", id: recentlyCounted.schoolId, label: recentlyCounted.schoolName },
      riskLevel: "Low", status: "Completed", approvalSafety: "SafeToApprove",
      primaryAction: { label: "View", intent: "open", href: "/dashboards/partner" },
      sourceModule: "data-intake",
      inboxTab: "CompletedToday",
    });
  }

  const nextThree = [...inbox]
    .filter((i) => i.status !== "Completed" && i.approvalSafety !== "Blocked")
    .sort((a, b) => a.priority - b.priority)
    .slice(0, 3);

  // Done-for-today checklist (varies by user type).
  const doneToday: DoneCheckItem[] = userType === "PartnerViewer"
    ? [
        { id: "pv-1", label: "Reviewed today's verified work", satisfiedWhen: "all Counted activities opened at least once today", done: false },
        { id: "pv-2", label: "Checked partner impact summary", satisfiedWhen: "impact card opened this session", done: false },
      ]
    : userType === "PartnerFieldOfficer"
    ? [
        { id: "pfo-1", label: "Today's activity logged",         satisfiedWhen: "every scheduled activity for today has a status update", done: false },
        { id: "pfo-2", label: "Evidence uploaded for completions", satisfiedWhen: "no Completed activity has missing required evidence", done: false, detail: `${evidenceMissing.length} pending` },
        { id: "pfo-3", label: "Returned activities re-submitted",  satisfiedWhen: "no items in ReturnedForCorrection state", done: false, detail: `${returned.length} pending` },
      ]
    : [
        { id: "pa-1", label: "Plans submitted for this week",      satisfiedWhen: "every planned-for-this-week activity is in Submitted+ status", done: false },
        { id: "pa-2", label: "Returned items addressed",           satisfiedWhen: "no ReturnedForCorrection in the inbox", done: false, detail: `${returned.length} pending` },
        { id: "pa-3", label: "Follow-Up handoffs confirmed",       satisfiedWhen: "every follow-up requested has an assignee", done: false, detail: `${followUps.length} requested` },
        { id: "pa-4", label: "Partner impact reviewed for the week", satisfiedWhen: "impact summary card opened this session", done: false },
      ];

  return {
    role: userType === "PartnerAdmin" ? "PartnerAdmin" : userType === "PartnerFieldOfficer" ? "PartnerFieldOfficer" : "PartnerViewer",
    header,
    nextThree,
    inbox,
    doneToday,
    changedSince: changesSince(sinceCookie, "Admin", now), // partner change-stream not yet seeded — reuse Admin's for visual completeness
  };
}

// ────────── Stub boards for the other 5 roles ──────────
//
// Same structure, shorter action list — the infrastructure is in
// place so backfilling per-role data is mechanical (one converter
// per upstream module). These render cleanly today and prove the
// component contract works for every role.

function stubBoard(role: EdifyRole, name: string, now: Date, sinceCookie: Date | null): RoleActionBoard {
  const firstName = name.split(" ")[0];
  const header: MissionHeader = {
    greeting: `${greetingForHour(now.getUTCHours())}, ${firstName}.`,
    mission: missionFor(role),
    periodLabel: periodLabel(now),
    summary: stubSummaryFor(role),
  };
  const inbox = stubInboxFor(role, now);
  const nextThree = inbox.filter((i) => i.status !== "Completed" && i.approvalSafety !== "Blocked").slice(0, 3);
  return {
    role,
    header,
    nextThree,
    inbox,
    doneToday: stubDoneFor(role),
    changedSince: changesSince(sinceCookie, role, now),
  };
}

function missionFor(role: EdifyRole): string {
  switch (role) {
    case "RVP":               return "See the region. Unblock the countries. Hold the strategic line.";
    case "ProgramAccountant": return "Move the money. Close the loop. Reconcile by Friday.";
    case "ImpactAssessment":  return "Verify what really happened. Certify what's true.";
    case "HumanResource":     return "Notice the human cost. Surface the hidden leaders.";
    case "Admin":             return "Keep the system clean. Catch what breaks before users do.";
    default:                  return "Plan smart. Execute with focus. Lead with impact.";
  }
}

function stubSummaryFor(role: EdifyRole): string {
  switch (role) {
    case "RVP":               return "Kenya needs an intervention call this week; Uganda's May envelope is over plan by 7%; Q1 regional report is ready.";
    case "ProgramAccountant": return "8 fund slips approved and ready to disburse; 2 reimbursement claims pending; 1 balance return overdue by 3 days.";
    case "ImpactAssessment":  return "12 possible-match records await your review; 3 no-match activities need manual creation; April records ready for CD cert.";
    case "HumanResource":     return "Purity is flagged under fairness rules — high load, low pace; recognition shortlist of 4 is ready.";
    case "Admin":             return "1 new signup awaiting role assignment; 1 failed import this morning; audit log shows a role-switch spike to investigate.";
    default:                  return "Nothing urgent on your queue right now.";
  }
}

function stubInboxFor(role: EdifyRole, now: Date): ActionItem[] {
  // A small but representative set per role — proves the inbox renders
  // and the bulk-approve component reads the right shape.
  const base = (idx: number): Partial<ActionItem> => ({
    role,
    sourceModule: "insights",
    status: "Pending",
    riskLevel: "Medium",
    dueDate: isoIn(idx, now),
  });

  switch (role) {
    case "RVP":
      return [
        { ...base(0), id: "rvp-1", priority: 1, category: "RegionalEscalation",
          title: "Kenya country call — staff pace red flag",
          description: "5 of 8 CCEOs below 60% pace. Country PL has asked for guidance on portfolio rebalancing.",
          affectedEntity: { kind: "Country", id: "ke", label: "Kenya" },
          riskLevel: "High", approvalSafety: "NeedsReview",
          primaryAction: { label: "Open country view", intent: "review", href: "/dashboards/rvp" },
          inboxTab: "NeedsReview" } as ActionItem,
        { ...base(1), id: "rvp-2", priority: 2, category: "FundApproval",
          title: "Uganda May envelope · UGX 142M",
          description: "7% over plan. CD has supplied variance commentary. Safe to approve at country level.",
          affectedEntity: { kind: "Fund", id: "ug-may", label: "Uganda · May", amountUgx: 142_000_000 },
          approvalSafety: "SafeToApprove",
          primaryAction: { label: "Approve envelope", intent: "approve", href: "/funds/approvals" },
          inboxTab: "NeedsApproval" } as ActionItem,
        { ...base(3), id: "rvp-3", priority: 3, category: "RegionalEscalation",
          title: "Export Q1 regional report",
          description: "All three countries have certified Q1 data. Report is ready for board distribution.",
          affectedEntity: { kind: "System", id: "rvp-q1", label: "Q1 regional report" },
          riskLevel: "Low", approvalSafety: "SafeToApprove",
          primaryAction: { label: "Export PDF", intent: "submit", href: "/reports" },
          inboxTab: "NeedsFollowUp" } as ActionItem,
      ];
    case "ProgramAccountant":
      return [
        { ...base(0), id: "acc-1", priority: 1, category: "Disbursement",
          title: "Disburse 8 approved fund slips",
          description: "All passed PL + CD approval. Country funds available. Safe to disburse in one batch.",
          affectedEntity: { kind: "Fund", id: "acc-batch", label: "8 fund slips · UGX 9.4M", amountUgx: 9_400_000 },
          riskLevel: "High", approvalSafety: "SafeToApprove",
          primaryAction: { label: "Bulk disburse", intent: "disburse", href: "/dashboards/accountant" },
          inboxTab: "NeedsApproval" } as ActionItem,
        { ...base(0), id: "acc-2", priority: 2, category: "BalanceReturn",
          title: "Abdi Hassan · balance return 3 days overdue",
          description: "UGX 180K owed. Send a reminder; escalate to PL if no response by EOD.",
          affectedEntity: { kind: "Staff", id: "STF-AH-044", label: "Abdi Hassan" },
          riskLevel: "High", approvalSafety: "NeedsReview",
          primaryAction: { label: "Send reminder", intent: "submit", href: "/dashboards/accountant" },
          inboxTab: "NeedsFollowUp" } as ActionItem,
        { ...base(2), id: "acc-3", priority: 3, category: "Reimbursement",
          title: "James Otieno · reimbursement claim UGX 220K",
          description: "Over-spend reason supplied. Under 10% so PL route applies. Safe to approve.",
          affectedEntity: { kind: "Fund", id: "reim-1", label: "James Otieno claim", amountUgx: 220_000 },
          approvalSafety: "SafeToApprove",
          primaryAction: { label: "Approve claim", intent: "approve", href: "/weekly-funds" },
          inboxTab: "NeedsApproval" } as ActionItem,
      ];
    case "ImpactAssessment":
      return [
        { ...base(0), id: "ia-1", priority: 1, category: "DataVerification",
          title: "12 possible matches need your call",
          description: "Activities logged by CCEOs against schools where Salesforce shows a similar record. Confirm or split.",
          affectedEntity: { kind: "System", id: "ia-batch", label: "12 possible-match records" },
          riskLevel: "Medium", approvalSafety: "NeedsReview",
          primaryAction: { label: "Review Queue", intent: "review", href: "/data-verification" },
          inboxTab: "NeedsReview" } as ActionItem,
        { ...base(0), id: "ia-2", priority: 2, category: "DataVerification",
          title: "3 no-match records · Mbale region",
          description: "Salesforce has no candidate. Either the school is new (create) or the activity is invalid (reject).",
          affectedEntity: { kind: "District", id: "mbale", label: "Mbale region" },
          riskLevel: "High", approvalSafety: "NeedsReview",
          primaryAction: { label: "Resolve", intent: "review", href: "/data-verification" },
          inboxTab: "NeedsReview" } as ActionItem,
        { ...base(2), id: "ia-3", priority: 3, category: "CertifyData",
          title: "April records ready for CD certification",
          description: "Your verification queue is empty for April. Send to CD for sign-off.",
          affectedEntity: { kind: "Country", id: "ug-apr", label: "Uganda · April" },
          approvalSafety: "SafeToApprove",
          primaryAction: { label: "Send to CD", intent: "submit", href: "/quality-checks" },
          inboxTab: "NeedsFollowUp" } as ActionItem,
        // Partner verification queue — partner work obeys the same
        // counting rules as staff work, so M&E processes both
        // through one queue.
        ...partnerItemsForMe(now),
      ];
    case "HumanResource":
      return [
        { ...base(0), id: "hr-1", priority: 1, category: "StaffSupport",
          title: "Purity Muthoni · fairness flag",
          description: "Pace 46% but FWI shows 95th-percentile portfolio load. Recommend support conversation, not coaching warning.",
          affectedEntity: { kind: "Staff", id: "STF-PM-031", label: "Purity Muthoni" },
          riskLevel: "High", approvalSafety: "NeedsReview",
          primaryAction: { label: "Open support workflow", intent: "review", href: "/team-targets" },
          inboxTab: "NeedsReview" } as ActionItem,
        { ...base(1), id: "hr-2", priority: 2, category: "StaffSupport",
          title: "4 staff qualify for May recognition",
          description: "Met or exceeded targets under above-average portfolio load. Shortlist ready for your review.",
          affectedEntity: { kind: "System", id: "hr-recog", label: "May recognition shortlist" },
          approvalSafety: "SafeToApprove",
          primaryAction: { label: "Review shortlist", intent: "approve", href: "/team-targets" },
          inboxTab: "NeedsApproval" } as ActionItem,
        { ...base(2), id: "hr-3", priority: 3, category: "StaffSupport",
          title: "James Otieno leave May 18–20 — pace impact noted",
          description: "Pace targets auto-adjusted in fairness model. No action needed; FYI for the upcoming staff review.",
          affectedEntity: { kind: "Staff", id: "STF-JO-022", label: "James Otieno" },
          riskLevel: "Low", approvalSafety: "SafeToApprove",
          primaryAction: { label: "View leave", intent: "open", href: "/leave" },
          inboxTab: "NeedsFollowUp" } as ActionItem,
        // Workload guardrail signals from the SHF engine — flag staff
        // crossing healthy thresholds BEFORE the system penalises them.
        ...workloadRiskItemsForHr(now),
      ];
    case "Admin":
      return [
        { ...base(0), id: "ad-1", priority: 1, category: "AdminSetup",
          title: "Assign Role: new.cceo@edify.org",
          description: "Signup landed at 09:12. No role yet — must be assigned before they can land on a dashboard.",
          affectedEntity: { kind: "Staff", id: "new-cceo", label: "new.cceo@edify.org" },
          riskLevel: "Medium", approvalSafety: "NeedsReview",
          primaryAction: { label: "Assign Role", intent: "approve", href: "/admin" },
          inboxTab: "NeedsApproval" } as ActionItem,
        { ...base(0), id: "ad-2", priority: 2, category: "AdminSetup",
          title: "Failed import: school-roster.csv",
          description: "3 rows rejected (missing district). Either fix the file or skip those rows.",
          affectedEntity: { kind: "System", id: "import-1", label: "school-roster.csv" },
          riskLevel: "High", approvalSafety: "NeedsReview",
          primaryAction: { label: "Open import log", intent: "review", href: "/admin" },
          inboxTab: "NeedsReview" } as ActionItem,
        { ...base(1), id: "ad-3", priority: 3, category: "AdminSetup",
          title: "Audit spike: 12 role-switches in 1h",
          description: "Worth a glance — usually a tester running through roles, but the system surfaces it just in case.",
          affectedEntity: { kind: "System", id: "audit-spike", label: "Role-switch endpoint" },
          riskLevel: "Low", approvalSafety: "SafeToApprove",
          primaryAction: { label: "Open activity log", intent: "open", href: "/admin/audit-log" },
          inboxTab: "NeedsFollowUp" } as ActionItem,
      ];
    default:
      return [];
  }
}

function stubDoneFor(role: EdifyRole): DoneCheckItem[] {
  switch (role) {
    case "RVP":               return [
      { id: "rvp-d1", label: "Country envelopes triaged",  satisfiedWhen: "every country submission has a decision", done: false },
      { id: "rvp-d2", label: "Risk countries reviewed",    satisfiedWhen: "every country at risk has an action note", done: false },
      { id: "rvp-d3", label: "Regional report exported",   satisfiedWhen: "Q1 report PDF generated this week", done: false },
    ];
    case "ProgramAccountant": return [
      { id: "acc-d1", label: "Approved fund slips disbursed",   satisfiedWhen: "Disbursement queue is empty", done: false },
      { id: "acc-d2", label: "Overdue reconciliations chased",  satisfiedWhen: "every overdue accountability has a reminder logged today", done: false },
      { id: "acc-d3", label: "Balance returns confirmed",       satisfiedWhen: "every BalanceReturn moved Pending → Confirmed", done: false },
    ];
    case "ImpactAssessment":  return [
      { id: "ia-d1", label: "Possible matches resolved",   satisfiedWhen: "queue at 0", done: false },
      { id: "ia-d2", label: "No-match records handled",    satisfiedWhen: "every no-match has either a new school or a reject reason", done: false },
      { id: "ia-d3", label: "Certified records sent up",   satisfiedWhen: "ready-for-CD queue empty", done: false },
    ];
    case "HumanResource":     return [
      { id: "hr-d1", label: "Fairness flags reviewed",     satisfiedWhen: "every fairness-flagged staff has a notation", done: false },
      { id: "hr-d2", label: "Recognition shortlist sent",  satisfiedWhen: "monthly recognition email sent", done: false },
      { id: "hr-d3", label: "Leave conflicts logged",      satisfiedWhen: "every leave with pace impact noted in team-targets", done: false },
    ];
    case "Admin":             return [
      { id: "ad-d1", label: "New signups have a role",        satisfiedWhen: "no pending users", done: false },
      { id: "ad-d2", label: "Failed imports triaged",         satisfiedWhen: "no errored imports older than 24h", done: false },
      { id: "ad-d3", label: "Audit exceptions reviewed",      satisfiedWhen: "every flagged event has an action note", done: false },
    ];
    default: return [];
  }
}

// ────────── Public API ──────────

export type EngineContext = {
  role: EdifyRole;
  name: string;
  /// User email — required for partner roles so the engine can
  /// resolve which partner organisation they belong to. Optional
  /// for non-partner roles (engine ignores it).
  email?: string;
  now?: Date;
  /// Raw cookie string from the request — engine reads
  /// `edify-last-viewed` itself so the call site stays simple.
  cookieHeader?: string | null;
};

export function buildRoleActionBoard(ctx: EngineContext): RoleActionBoard {
  const now = ctx.now ?? new Date();
  const sinceCookie = parseLastViewed(ctx.cookieHeader ?? null);
  switch (ctx.role) {
    case "CCEO":                return cceoBoard(ctx.name, now, sinceCookie);
    case "CountryProgramLead":  return cplBoard(ctx.name, now, sinceCookie);
    case "CountryDirector":     return cdBoard(ctx.name, now, sinceCookie);
    case "PartnerAdmin":
    case "PartnerFieldOfficer":
    case "PartnerViewer":
      return partnerBoard(ctx.email ?? "", ctx.name, ctx.role, now, sinceCookie);
    default:                    return stubBoard(ctx.role, ctx.name, now, sinceCookie);
  }
}

function parseLastViewed(cookieHeader: string | null): Date | null {
  if (!cookieHeader) return null;
  // Re-uses the same parsing from last-login.ts to avoid a circular
  // import here — duplicated by design, small + stable.
  for (const pair of cookieHeader.split(";")) {
    const idx = pair.indexOf("=");
    if (idx < 0) continue;
    const k = pair.slice(0, idx).trim();
    if (k !== "edify-last-viewed") continue;
    const value = decodeURIComponent(pair.slice(idx + 1).trim());
    const t = Date.parse(value);
    return Number.isFinite(t) ? new Date(t) : null;
  }
  return null;
}
