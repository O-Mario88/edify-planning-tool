// Mock data for the redesigned partner dashboard
// (/dashboards/partner). Mirrors the BFEP — Bright Future Education
// Partners — reference screen exactly: the priority actions, action
// inbox, assigned schools, upcoming activities, status buckets, and
// done-for-today checklist all read from this single source so the
// numbers in the sidebar badges, the tab counts, and the body cards
// stay aligned.
//
// In production this is replaced by server-resolved queries against
// the partner_activities table + the verification engine.

export type PartnerOrgInfo = {
  partnerId: string;
  partnerCode: string;
  shortInitials: string;
  name: string;
  mission: string;
  status: "Active" | "Paused" | "Pending Renewal";
  focalPerson: { name: string; phone: string };
  assignedDistricts: string[];
  assignedSchoolsCount: number;
  contract: { start: string; end: string; monthsLabel: string };
  edifyFocalPerson: { name: string; phone: string };
};

export type PartnerPriority = "High" | "Medium" | "Low";

export type PartnerPriorityAction = {
  id: string;
  priority: "HIGH" | "MEDIUM";
  dueLabel: string;
  activityTitle: string;
  activityType: string;
  schoolName: string;
  districtSub: string;
  dueDateLabel: string;
  reason: string;
  requires: string;
  primaryCta: { label: string; href: string };
  secondaryCta: { label: string; href: string };
};

export type EvidenceStatus = "Missing" | "Complete" | "Submitted";
export type ReportStatus = "Not Submitted" | "Draft" | "Returned" | "Submitted";
export type VerificationStatus = "Not Started" | "Returned" | "Edify Review" | "M&E Verified";
export type ActionLabel =
  | "Schedule Activity"
  | "Upload Evidence"
  | "Start Visit"
  | "Correct Report"
  | "View Status"
  | "View Details";

export type PartnerInboxRow = {
  id: string;
  priority: PartnerPriority;
  activity: string;
  activitySub: string;
  school: string;
  district: string;
  dueDateLabel: string;
  dueDateSub: string;
  facilitator: string;
  evidence: EvidenceStatus;
  report: ReportStatus;
  verification: VerificationStatus;
  actionLabel: ActionLabel;
};

// 8-tab workflow-state navigation (per Partner Evidence Assurance
// spec): each tab is a stage in the activity lifecycle, not a generic
// category. Reads as "what stage is my work in, and what do I need
// to do next?"
export type PartnerInboxTabKey =
  | "assigned"
  | "scheduleRequired"
  | "scheduled"
  | "evidenceRequired"
  | "returned"
  | "awaitingCceo"
  | "paymentProgress"
  | "completed";

export type PartnerInboxTab = {
  key: PartnerInboxTabKey;
  label: string;
  count: number;
};

export type PartnerAssignedSchool = {
  id: string;
  name: string;
  district: string;
  subCounty: string;
  parish: string;
  supportNeed: string;
  ssaWeakArea: string;
  plannedActivity: string;
  dueDate: string;
  lastSupport: string;
};

export type UpcomingBucketKey = "today" | "tomorrow" | "thisWeek" | "later";

export type PartnerUpcomingItem = {
  id: string;
  bucket: UpcomingBucketKey;
  bucketLabel: string;
  activity: string;
  activitySub: string;
  school: string;
  district: string;
  time: string;
  facilitator: string;
  ctaLabel: string;
};

export type StatusBucketKey =
  | "evidenceMissing"
  | "returnedForCorrection"
  | "awaitingVerification"
  | "verifiedCounted";

export type StatusBucket = {
  key: StatusBucketKey;
  title: string;
  count: number;
  items: { label: string; sub: string; tone: "rose" | "amber" | "blue" | "emerald" }[];
  ctaLabel: string;
  ctaHref: string;
  tone: "rose" | "amber" | "blue" | "emerald";
};

export type DoneForTodayItem = {
  id: string;
  label: string;
  done: boolean;
};

// ────────── Payment status (partner view) ──────────
//
// Partner-visible payment state. Counts roll up across all the
// partner's activities so the partner sees the whole pipeline at a
// glance ("I have 5 things waiting on the CCEO"). Mirrors the
// workflow state machine in partner-workflow.ts.

export type PartnerPaymentStateKey =
  | "notEligible"
  | "awaitingCceo"
  | "awaitingPl"
  | "sentToAccountant"
  | "paid"
  | "returned"
  | "onHold";

export type PartnerPaymentLine = {
  key: PartnerPaymentStateKey;
  label: string;
  description: string;
  count: number;
  amountUgx: number;
  tone: "muted" | "amber" | "blue" | "emerald" | "rose";
};

export const partnerPaymentLines: PartnerPaymentLine[] = [
  {
    key: "notEligible",
    label: "Not eligible yet",
    description: "Work not completed or evidence missing.",
    count: 14, amountUgx: 0,
    tone: "muted",
  },
  {
    key: "awaitingCceo",
    label: "Awaiting CCEO confirmation",
    description: "Evidence submitted — waiting on staff confirmation.",
    count: 5, amountUgx: 1_750_000,
    tone: "amber",
  },
  {
    key: "awaitingPl",
    label: "Awaiting PL approval",
    description: "CCEO confirmed — waiting on Program Lead.",
    count: 3, amountUgx: 1_050_000,
    tone: "amber",
  },
  {
    key: "sentToAccountant",
    label: "Sent to accountant",
    description: "Approved — payment ready to clear.",
    count: 2, amountUgx: 700_000,
    tone: "blue",
  },
  {
    key: "paid",
    label: "Paid / cleared",
    description: "Cleared by accountant this month.",
    count: 16, amountUgx: 5_600_000,
    tone: "emerald",
  },
  {
    key: "returned",
    label: "Returned",
    description: "Needs correction — see action inbox.",
    count: 3, amountUgx: 0,
    tone: "rose",
  },
  {
    key: "onHold",
    label: "On hold",
    description: "Payment paused with reason.",
    count: 0, amountUgx: 0,
    tone: "rose",
  },
];

export function partnerPaymentTotals() {
  const awaitingTotal = partnerPaymentLines
    .filter((l) => l.key === "awaitingCceo" || l.key === "awaitingPl" || l.key === "sentToAccountant")
    .reduce((sum, l) => sum + l.amountUgx, 0);
  const paidThisMonth = partnerPaymentLines.find((l) => l.key === "paid")?.amountUgx ?? 0;
  return { awaitingTotal, paidThisMonth };
}

// ─────────────────────────── Data ───────────────────────────

export const partnerOrg: PartnerOrgInfo = {
  partnerId: "BFEP",
  partnerCode: "BFEP-UG-012",
  shortInitials: "BF",
  name: "Bright Future Education Partners",
  mission:
    "Support assigned schools with quality training, timely follow-up, strong evidence, and verified school improvement.",
  status: "Active",
  focalPerson: { name: "Daniel Mwangi", phone: "+256 700 123 456" },
  assignedDistricts: ["Mukono", "Kayunga"],
  assignedSchoolsCount: 24,
  contract: { start: "Jan 1, 2026", end: "Dec 31, 2026", monthsLabel: "12 months" },
  edifyFocalPerson: { name: "Sarah Nanyongo", phone: "+256 701 987 654" },
};

export const partnerPriorityActions: PartnerPriorityAction[] = [
  {
    id: "PA-001",
    priority: "HIGH",
    dueLabel: "Due Tomorrow",
    activityTitle: "Upload attendance sheet",
    activityType: "In-School Training",
    schoolName: "Hope Primary School",
    districtSub: "Mukono District · Ntenjeru Sub-county",
    dueDateLabel: "Due: Tue, May 13, 2026",
    reason: "Attendance not uploaded.",
    requires: "Attendance sheet",
    primaryCta: { label: "Upload Evidence", href: "/dashboards/partner#evidence" },
    secondaryCta: { label: "View Activity", href: "/dashboards/partner#activity" },
  },
  {
    id: "PA-002",
    priority: "HIGH",
    dueLabel: "Due May 16",
    activityTitle: "Conduct follow-up visit",
    activityType: "Follow-Up Visit",
    schoolName: "Grace Primary School",
    districtSub: "Mukono District · Nsumba Sub-county",
    dueDateLabel: "Due: Fri, May 16, 2026",
    reason: "Follow-Up visit is overdue.",
    requires: "Visit report, photos",
    primaryCta: { label: "Start Visit", href: "/dashboards/partner#visit" },
    secondaryCta: { label: "View Plan", href: "/dashboards/partner#plan" },
  },
  {
    id: "PA-003",
    priority: "MEDIUM",
    dueLabel: "Due May 15",
    activityTitle: "Correct returned report",
    activityType: "Teacher Training Debrief",
    schoolName: "Kireka Primary School",
    districtSub: "Mukono District · Kireka Sub-county",
    dueDateLabel: "Due: Thu, May 15, 2026",
    reason: "M&E returned report for correction.",
    requires: "Training debrief report",
    primaryCta: { label: "Correct Submission", href: "/dashboards/partner#correct" },
    secondaryCta: { label: "View Feedback", href: "/dashboards/partner#feedback" },
  },
];

export const doneForTodayItems: DoneForTodayItem[] = [
  { id: "dft-1", label: "Today's assigned activity completed",   done: true  },
  { id: "dft-2", label: "Attendance/evidence uploaded",           done: true  },
  { id: "dft-3", label: "Activity report submitted",              done: true  },
  { id: "dft-4", label: "Returned corrections cleared",           done: false },
  { id: "dft-5", label: "Tomorrow's activity reviewed",           done: false },
];

// Workflow-state tabs: one tab per stage in the partner activity
// lifecycle. Counts feed the same engine as the workflow tracker.
export const partnerInboxTabs: PartnerInboxTab[] = [
  { key: "assigned",         label: "Assigned to Us",          count: 7  },
  { key: "scheduleRequired", label: "Schedule Required",       count: 3  },
  { key: "scheduled",        label: "Scheduled",               count: 5  },
  { key: "evidenceRequired", label: "Evidence Required",       count: 14 },
  { key: "returned",         label: "Returned for Correction", count: 3  },
  { key: "awaitingCceo",     label: "Awaiting CCEO",           count: 5  },
  { key: "paymentProgress",  label: "Payment Progress",        count: 6  },
  { key: "completed",        label: "Completed",               count: 16 },
];

export const partnerInboxRows: PartnerInboxRow[] = [
  {
    id: "IBX-000",
    priority: "High",
    activity: "Coaching Visit",
    activitySub: "Literacy follow-up",
    school: "Maple Grove Primary",
    district: "Kayunga",
    dueDateLabel: "Awaiting schedule",
    dueDateSub: "Assigned 2 days ago",
    facilitator: "—",
    evidence: "Missing",
    report: "Not Submitted",
    verification: "Not Started",
    actionLabel: "Schedule Activity",
  },
  {
    id: "IBX-001",
    priority: "High",
    activity: "In-School Training",
    activitySub: "Literacy Training",
    school: "Hope Primary School",
    district: "Mukono",
    dueDateLabel: "May 13, 2026",
    dueDateSub: "Tomorrow",
    facilitator: "Paul Chinyama",
    evidence: "Missing",
    report: "Not Submitted",
    verification: "Not Started",
    actionLabel: "Upload Evidence",
  },
  {
    id: "IBX-002",
    priority: "High",
    activity: "Follow-Up Visit",
    activitySub: "Math Improvement",
    school: "Grace Primary School",
    district: "Mukono",
    dueDateLabel: "May 16, 2026",
    dueDateSub: "in 4 days",
    facilitator: "Irene Mutebi",
    evidence: "Complete",
    report: "Draft",
    verification: "Not Started",
    actionLabel: "Start Visit",
  },
  {
    id: "IBX-003",
    priority: "Medium",
    activity: "Training Debrief",
    activitySub: "P3 Literacy Training",
    school: "Kireka Primary School",
    district: "Mukono",
    dueDateLabel: "May 15, 2026",
    dueDateSub: "in 3 days",
    facilitator: "Joseph Nsubuga",
    evidence: "Complete",
    report: "Returned",
    verification: "Returned",
    actionLabel: "Correct Report",
  },
  {
    id: "IBX-004",
    priority: "Medium",
    activity: "Support Visit",
    activitySub: "School Leadership",
    school: "St. Mary's Primary",
    district: "Kayunga",
    dueDateLabel: "May 17, 2026",
    dueDateSub: "in 5 days",
    facilitator: "Ruth Kabuye",
    evidence: "Complete",
    report: "Submitted",
    verification: "Edify Review",
    actionLabel: "View Status",
  },
  {
    id: "IBX-005",
    priority: "Low",
    activity: "Resource Delivery",
    activitySub: "Learning Materials",
    school: "Namilyango Primary",
    district: "Mukono",
    dueDateLabel: "May 20, 2026",
    dueDateSub: "in 8 days",
    facilitator: "Simon Otim",
    evidence: "Complete",
    report: "Submitted",
    verification: "M&E Verified",
    actionLabel: "View Details",
  },
  // ─── Wider portfolio — every assigned school across Mukono +
  // Kayunga represented at least once so the partner can see and
  // act on each one from this single inbox. Mix of states drives a
  // realistic distribution across the 8 workflow tabs.
  { id: "IBX-006", priority: "High",   activity: "In-School Training",  activitySub: "Numeracy fundamentals",  school: "Maple Grove Primary",      district: "Kayunga", dueDateLabel: "May 14, 2026", dueDateSub: "in 2 days", facilitator: "Daniel Mwangi",  evidence: "Missing",   report: "Not Submitted", verification: "Not Started",  actionLabel: "Upload Evidence" },
  { id: "IBX-007", priority: "Medium", activity: "Coaching Visit",      activitySub: "P3 teacher coaching",     school: "Eden Foundation School",   district: "Mukono",  dueDateLabel: "May 18, 2026", dueDateSub: "in 6 days", facilitator: "Ruth Kabuye",    evidence: "Complete",  report: "Draft",         verification: "Not Started",  actionLabel: "Start Visit" },
  { id: "IBX-008", priority: "Medium", activity: "Classroom Observation",activitySub: "Literacy lesson",        school: "Clover Primary School",    district: "Kayunga", dueDateLabel: "May 19, 2026", dueDateSub: "in 7 days", facilitator: "Irene Mutebi",   evidence: "Complete",  report: "Submitted",     verification: "Edify Review", actionLabel: "View Status" },
  { id: "IBX-009", priority: "High",   activity: "Follow-Up Visit",     activitySub: "Reading fluency check",   school: "Sunrise Junior School",    district: "Mukono",  dueDateLabel: "May 15, 2026", dueDateSub: "in 3 days", facilitator: "Joseph Nsubuga", evidence: "Missing",   report: "Not Submitted", verification: "Not Started",  actionLabel: "Schedule Activity" },
  { id: "IBX-010", priority: "Low",    activity: "Resource Delivery",   activitySub: "Reading books · P4",       school: "Bright Future PS",         district: "Mukono",  dueDateLabel: "May 21, 2026", dueDateSub: "in 9 days", facilitator: "Simon Otim",     evidence: "Complete",  report: "Submitted",     verification: "M&E Verified",  actionLabel: "View Details" },
  { id: "IBX-011", priority: "Medium", activity: "Teacher Training",    activitySub: "Foundational literacy",   school: "Lakeview Primary",         district: "Kayunga", dueDateLabel: "May 22, 2026", dueDateSub: "in 10 days",facilitator: "Daniel Mwangi",  evidence: "Complete",  report: "Returned",      verification: "Returned",      actionLabel: "Correct Report" },
  { id: "IBX-012", priority: "Medium", activity: "Coaching Visit",      activitySub: "Numeracy mentoring",      school: "Riverside Primary",        district: "Mukono",  dueDateLabel: "May 23, 2026", dueDateSub: "in 11 days",facilitator: "Ruth Kabuye",    evidence: "Complete",  report: "Submitted",     verification: "Edify Review",  actionLabel: "View Status" },
  { id: "IBX-013", priority: "High",   activity: "In-School Training",  activitySub: "Phonics for P1-P2",       school: "Hilltop Basic School",     district: "Mukono",  dueDateLabel: "May 24, 2026", dueDateSub: "in 12 days",facilitator: "Joseph Nsubuga", evidence: "Missing",   report: "Not Submitted", verification: "Not Started",   actionLabel: "Upload Evidence" },
  { id: "IBX-014", priority: "Low",    activity: "Follow-Up Visit",     activitySub: "Leadership check-in",     school: "Eastview Junior",          district: "Mukono",  dueDateLabel: "May 25, 2026", dueDateSub: "in 13 days",facilitator: "Irene Mutebi",   evidence: "Complete",  report: "Submitted",     verification: "M&E Verified",  actionLabel: "View Details" },
  { id: "IBX-015", priority: "Medium", activity: "Classroom Observation",activitySub: "Numeracy observation",   school: "Mukono Central PS",        district: "Mukono",  dueDateLabel: "May 26, 2026", dueDateSub: "in 14 days",facilitator: "Daniel Mwangi",  evidence: "Complete",  report: "Draft",         verification: "Not Started",   actionLabel: "Start Visit" },
  { id: "IBX-016", priority: "High",   activity: "Coaching Visit",      activitySub: "Reading comprehension",   school: "Kayunga Hill School",      district: "Kayunga", dueDateLabel: "May 27, 2026", dueDateSub: "in 15 days",facilitator: "Ruth Kabuye",    evidence: "Missing",   report: "Not Submitted", verification: "Not Started",   actionLabel: "Schedule Activity" },
  { id: "IBX-017", priority: "Medium", activity: "Teacher Training",    activitySub: "Lesson planning",         school: "Pope John PS",             district: "Mukono",  dueDateLabel: "May 28, 2026", dueDateSub: "in 16 days",facilitator: "Joseph Nsubuga", evidence: "Complete",  report: "Returned",      verification: "Returned",      actionLabel: "Correct Report" },
  { id: "IBX-018", priority: "Low",    activity: "Resource Delivery",   activitySub: "Math kits · P5-P6",        school: "Bbaale Primary",           district: "Kayunga", dueDateLabel: "May 29, 2026", dueDateSub: "in 17 days",facilitator: "Simon Otim",     evidence: "Complete",  report: "Submitted",     verification: "Edify Review",  actionLabel: "View Status" },
  { id: "IBX-019", priority: "High",   activity: "Follow-Up Visit",     activitySub: "Critical school follow-up",school: "Galiraaya Primary",       district: "Kayunga", dueDateLabel: "May 30, 2026", dueDateSub: "in 18 days",facilitator: "Daniel Mwangi",  evidence: "Missing",   report: "Not Submitted", verification: "Not Started",   actionLabel: "Upload Evidence" },
  { id: "IBX-020", priority: "Medium", activity: "In-School Training",  activitySub: "Classroom management",    school: "Ntenjeru Primary",         district: "Mukono",  dueDateLabel: "Jun 02, 2026", dueDateSub: "in 21 days",facilitator: "Irene Mutebi",   evidence: "Complete",  report: "Submitted",     verification: "M&E Verified",  actionLabel: "View Details" },
  { id: "IBX-021", priority: "Medium", activity: "Coaching Visit",      activitySub: "School leadership",       school: "Kireka Hills PS",          district: "Mukono",  dueDateLabel: "Jun 03, 2026", dueDateSub: "in 22 days",facilitator: "Ruth Kabuye",    evidence: "Missing",   report: "Not Submitted", verification: "Not Started",   actionLabel: "Schedule Activity" },
  { id: "IBX-022", priority: "Low",    activity: "Resource Delivery",   activitySub: "Library books",           school: "Kayunga Trust School",     district: "Kayunga", dueDateLabel: "Jun 04, 2026", dueDateSub: "in 23 days",facilitator: "Simon Otim",     evidence: "Complete",  report: "Submitted",     verification: "M&E Verified",  actionLabel: "View Details" },
  { id: "IBX-023", priority: "High",   activity: "In-School Training",  activitySub: "Early numeracy",          school: "Nsumba Primary",           district: "Mukono",  dueDateLabel: "Jun 05, 2026", dueDateSub: "in 24 days",facilitator: "Joseph Nsubuga", evidence: "Missing",   report: "Not Submitted", verification: "Not Started",   actionLabel: "Upload Evidence" },
  { id: "IBX-024", priority: "Medium", activity: "Classroom Observation",activitySub: "Early grade reading",    school: "Nakifuma Basic",           district: "Mukono",  dueDateLabel: "Jun 06, 2026", dueDateSub: "in 25 days",facilitator: "Daniel Mwangi",  evidence: "Complete",  report: "Draft",         verification: "Not Started",   actionLabel: "Start Visit" },
  { id: "IBX-025", priority: "Medium", activity: "Coaching Visit",      activitySub: "Headteacher mentoring",   school: "Bukoto Primary",           district: "Mukono",  dueDateLabel: "Jun 08, 2026", dueDateSub: "in 27 days",facilitator: "Ruth Kabuye",    evidence: "Complete",  report: "Returned",      verification: "Returned",      actionLabel: "Correct Report" },
  { id: "IBX-026", priority: "Low",    activity: "Follow-Up Visit",     activitySub: "Post-training review",    school: "Bweyogerere PS",           district: "Kayunga", dueDateLabel: "Jun 09, 2026", dueDateSub: "in 28 days",facilitator: "Irene Mutebi",   evidence: "Complete",  report: "Submitted",     verification: "Edify Review",  actionLabel: "View Status" },
  { id: "IBX-027", priority: "Medium", activity: "Teacher Training",    activitySub: "Phonemic awareness",      school: "Wakiso Foundation",        district: "Mukono",  dueDateLabel: "Jun 10, 2026", dueDateSub: "in 29 days",facilitator: "Daniel Mwangi",  evidence: "Missing",   report: "Not Submitted", verification: "Not Started",   actionLabel: "Schedule Activity" },
  { id: "IBX-028", priority: "High",   activity: "Coaching Visit",      activitySub: "Struggling teacher",      school: "St. Joseph PS",            district: "Kayunga", dueDateLabel: "Jun 11, 2026", dueDateSub: "in 30 days",facilitator: "Ruth Kabuye",    evidence: "Missing",   report: "Not Submitted", verification: "Not Started",   actionLabel: "Upload Evidence" },
  { id: "IBX-029", priority: "Low",    activity: "Resource Delivery",   activitySub: "Teacher guides",          school: "Kitende Christian PS",     district: "Mukono",  dueDateLabel: "Jun 12, 2026", dueDateSub: "in 31 days",facilitator: "Simon Otim",     evidence: "Complete",  report: "Submitted",     verification: "M&E Verified",  actionLabel: "View Details" },
  { id: "IBX-030", priority: "Medium", activity: "In-School Training",  activitySub: "Active learning",         school: "Lubowa Primary",           district: "Kayunga", dueDateLabel: "Jun 15, 2026", dueDateSub: "in 34 days",facilitator: "Joseph Nsubuga", evidence: "Complete",  report: "Submitted",     verification: "Edify Review",  actionLabel: "View Status" },
  { id: "IBX-031", priority: "Medium", activity: "Classroom Observation",activitySub: "Quality of instruction",  school: "Nakawuka Primary",         district: "Kayunga", dueDateLabel: "Jun 16, 2026", dueDateSub: "in 35 days",facilitator: "Daniel Mwangi",  evidence: "Missing",   report: "Not Submitted", verification: "Not Started",   actionLabel: "Schedule Activity" },
];

export const partnerAssignedSchools: PartnerAssignedSchool[] = [
  {
    id: "SCH-HOPE",
    name: "Hope Primary School",
    district: "Mukono District",
    subCounty: "Ntenjeru Sub-county",
    parish: "Ntenjeru",
    supportNeed: "Improve early grade literacy",
    ssaWeakArea: "Teaching & Learning",
    plannedActivity: "In-School Training (Literacy)",
    dueDate: "May 13, 2026",
    lastSupport: "Apr 22, 2026",
  },
  {
    id: "SCH-GRACE",
    name: "Grace Primary School",
    district: "Mukono District",
    subCounty: "Nsumba Sub-county",
    parish: "Nsumba",
    supportNeed: "Improve numeracy skills",
    ssaWeakArea: "Teaching & Learning",
    plannedActivity: "Follow-Up Visit",
    dueDate: "May 16, 2026",
    lastSupport: "Apr 25, 2026",
  },
  {
    id: "SCH-KIREKA",
    name: "Kireka Primary School",
    district: "Mukono District",
    subCounty: "Kireka Sub-county",
    parish: "Kireka",
    supportNeed: "Strengthen classroom management",
    ssaWeakArea: "Leadership & Governance",
    plannedActivity: "Teacher Training Debrief",
    dueDate: "May 15, 2026",
    lastSupport: "Apr 28, 2026",
  },
  {
    id: "SCH-STMARY",
    name: "St. Mary's Primary School",
    district: "Kayunga District",
    subCounty: "Kayunga Sub-county",
    parish: "Kayunga",
    supportNeed: "Improve leadership & planning",
    ssaWeakArea: "Leadership & Governance",
    plannedActivity: "Support Visit",
    dueDate: "May 17, 2026",
    lastSupport: "Apr 30, 2026",
  },
];

export const partnerUpcoming: PartnerUpcomingItem[] = [
  {
    id: "UP-1",
    bucket: "today",
    bucketLabel: "Today · Mon, May 12",
    activity: "In-School Training",
    activitySub: "Literacy (P1-P3 Teachers)",
    school: "Hope Primary School",
    district: "Mukono District",
    time: "9:00 AM - 1:00 PM",
    facilitator: "Paul Chinyama",
    ctaLabel: "Start Activity",
  },
  {
    id: "UP-2",
    bucket: "tomorrow",
    bucketLabel: "Tomorrow · Tue, May 13",
    activity: "Follow-Up Visit",
    activitySub: "Numeracy Improvement",
    school: "Grace Primary School",
    district: "Mukono District",
    time: "10:00 AM - 12:00 PM",
    facilitator: "Irene Mutebi",
    ctaLabel: "Start Visit",
  },
  {
    id: "UP-3",
    bucket: "thisWeek",
    bucketLabel: "This Week",
    activity: "Teacher Training Debrief",
    activitySub: "P3 Literacy Training",
    school: "Kireka Primary School",
    district: "Mukono District",
    time: "May 16, 2026 · 9:00 AM",
    facilitator: "Joseph Nsubuga",
    ctaLabel: "Submit Report",
  },
  // Support Visit (St. Mary's, May 17) intentionally lives only in the
  // Partner Action Inbox (IBX-004), not in this upcoming carousel — a
  // second card under "This Week" would orphan it visually alongside
  // the 1-card columns. The action is still 1 click away from the
  // inbox table below.
  {
    id: "UP-4",
    bucket: "later",
    bucketLabel: "Later",
    activity: "Resource Delivery",
    activitySub: "Textbooks & Learning Materials",
    school: "Namilyango Primary School",
    district: "Mukono District",
    time: "May 20, 2026 · 8:00 AM",
    facilitator: "Simon Otim",
    ctaLabel: "View Plan",
  },
];

export const partnerStatusBuckets: StatusBucket[] = [
  {
    key: "evidenceMissing",
    tone: "rose",
    title: "Evidence Missing",
    count: 14,
    items: [
      { label: "In-School Trainings",  sub: "5", tone: "rose" },
      { label: "Support Visits",       sub: "4", tone: "rose" },
      { label: "Classroom Observations", sub: "5", tone: "rose" },
    ],
    ctaLabel: "Upload Missing Evidence",
    ctaHref: "/dashboards/partner#evidence",
  },
  {
    key: "returnedForCorrection",
    tone: "amber",
    title: "Returned for Correction",
    count: 3,
    items: [
      { label: "Kireka Primary School",      sub: "Training Debrief Report", tone: "amber" },
      { label: "St. Mary's Primary School",  sub: "Visit Report",            tone: "amber" },
      { label: "Namilyango Primary School",  sub: "Debrief Report",          tone: "amber" },
    ],
    ctaLabel: "Correct Submissions",
    ctaHref: "/dashboards/partner#correct",
  },
  {
    key: "awaitingVerification",
    tone: "blue",
    title: "Awaiting Verification",
    count: 7,
    items: [
      { label: "Training Activities",   sub: "3", tone: "blue" },
      { label: "Support Visits",        sub: "2", tone: "blue" },
      { label: "Resource Deliveries",   sub: "2", tone: "blue" },
    ],
    ctaLabel: "View Submission Status",
    ctaHref: "/dashboards/partner#status",
  },
  {
    key: "verifiedCounted",
    tone: "emerald",
    title: "Verified / Counted",
    count: 16,
    items: [
      { label: "Training Activities",   sub: "M&E Verified", tone: "emerald" },
      { label: "Support Visits",        sub: "M&E Verified", tone: "emerald" },
      { label: "Resource Deliveries",   sub: "M&E Verified", tone: "emerald" },
    ],
    ctaLabel: "View Impact",
    ctaHref: "/dashboards/partner#impact",
  },
];
