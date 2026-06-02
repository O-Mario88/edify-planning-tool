// Accountant Console — mock data.
//
// Purpose of this tool (NOT a general accounting tool — NetSuite is):
//   1. Show how much the monthly plan costs to execute.
//   2. Automate staff weekly / monthly fund requests from approved
//      plans so the accountant just sees them and acts (release).
//   3. Track which disbursements still need a NetSuite Expense ID
//      from the staff member as proof of accountability. NetSuite is
//      the system of record for ledger + reconciliation.

// Single canonical accountant identity for the demo — matches the signed-in
// Program Accountant (Moses Tindi) so the console header and the CommandStack
// hero never show two different names on the same page.
export const accountantUser = {
  name: "Moses Tindi",
  shortName: "Moses",
  firstName: "Moses",
  initials: "MT",
  role: "Program Accountant",
  online: true,
  country: "Uganda",
  region: "North",
  flag: "🇺🇬",
};

export const periodLabel = "May 2025";

// ────────── KPI strip ──────────────────────────────────────────────────

export type AcctKpi = {
  key: string;
  label: string;
  value: string;
  caption: string;
  iconKey:
    | "available"      // cash on hand
    | "received"       // funds received this month
    | "disbursed"      // funds released
    | "pending"        // queue waiting on accountant
    | "overdue"        // accountability overdue
    | "utilization";   // % of budget spent
  delta?: string;
  ringPct?: number;
  sparkSeed?: number;
};

export const acctKpis: AcctKpi[] = [
  {
    key: "available",
    label: "Available Balance",
    value: "UGX 214.8M",
    caption: "vs Apr 2025",
    iconKey: "available",
    delta: "+18.6%",
    sparkSeed: 3,
  },
  {
    key: "received",
    label: "Funds Received This Month",
    value: "UGX 385.6M",
    caption: "2 transactions",
    iconKey: "received",
    sparkSeed: 5,
  },
  {
    key: "disbursed",
    label: "Total Disbursed This Month",
    value: "UGX 170.4M",
    caption: "46 disbursements",
    iconKey: "disbursed",
    sparkSeed: 4,
  },
  {
    key: "pending",
    label: "Pending Disbursement",
    value: "UGX 64.2M",
    caption: "12 requests",
    iconKey: "pending",
    sparkSeed: 7,
  },
  {
    key: "overdue",
    label: "Overdue Accountability",
    value: "UGX 28.7M",
    caption: "7 staff",
    iconKey: "overdue",
    delta: "-2.1%",
  },
  {
    key: "utilization",
    label: "Monthly Budget Utilization",
    value: "67%",
    caption: "UGX 802.3M of 1.2B",
    iconKey: "utilization",
    ringPct: 67,
  },
];

// ────────── Monthly Plan Cost & Approval Chain ────────────────────────

export type PlanCostLine = {
  label: string;
  amount: string;
  pct: string;
  tone: "emerald" | "blue" | "rose" | "amber" | "slate";
};

export const monthlyPlanCost = {
  total: "UGX 1.2B",
  approvedBy: "RVP",
  approvedOn: "Apr 28, 2025",
  lines: [
    { label: "Field Activities", amount: "UGX 820.0M", pct: "68%", tone: "emerald" },
    { label: "Program Ops",      amount: "UGX 180.0M", pct: "15%", tone: "blue" },
    { label: "Impact & M&E",     amount: "UGX 100.0M", pct: "8%",  tone: "rose" },
    { label: "Admin Ops",        amount: "UGX 70.0M",  pct: "6%",  tone: "amber" },
    { label: "Contingency",      amount: "UGX 30.0M",  pct: "3%",  tone: "slate" },
  ] satisfies PlanCostLine[],
};

// Kept for backward-compat with existing imports.
export const monthlyBudget = monthlyPlanCost;

export type ApprovalFlowStep = {
  role: string;
  label: string;
  status: "Approved" | "In Progress";
  meta: string;
  date: string;
};

export const approvalFlow: ApprovalFlowStep[] = [
  { role: "RVP",              label: "(Country Budget)",     status: "Approved",     meta: "",                 date: "Apr 28, 2025" },
  { role: "Program Leads",    label: "(CCEO Requests)",      status: "Approved",     meta: "32 requests",      date: "May 1 – May 25" },
  { role: "Country Director", label: "(All Other Requests)", status: "Approved",     meta: "18 requests",      date: "May 2 – May 26" },
  { role: "Accountant",       label: "(Disbursement)",       status: "In Progress",  meta: "46 disbursements", date: "May 1 – May 26" },
];

// ────────── Plan Cost Flow chart (weekly) ─────────────────────────────

export type WeeklyOverviewPoint = {
  week: string;
  range: string;
  planned: number;
  approved: number;
  disbursed: number;
};

export const weeklyOverview: WeeklyOverviewPoint[] = [
  { week: "Wk 1", range: "Apr 28 – May 4",  planned: 260, approved: 210, disbursed: 165 },
  { week: "Wk 2", range: "May 5 – May 11",  planned: 340, approved: 305, disbursed: 235 },
  { week: "Wk 3", range: "May 12 – May 18", planned: 360, approved: 340, disbursed: 268 },
  { week: "Wk 4", range: "May 19 – May 25", planned: 380, approved: 365, disbursed: 280 },
  { week: "Wk 5", range: "May 26 – May 31", planned: 370, approved: 348, disbursed: 270 },
];

// ────────── Disbursement Summary (simple, no chart) ───────────────────
//
// A plain-numbers replacement for the weekly chart. Tells the same
// story — approved vs disbursed vs still-in-queue — but as scannable
// stat rows + a simple weekly list with proportional bars.

export type DisbursementWeek = {
  week: string;
  range: string;
  amount: string;
  pct: number; // bar width relative to the biggest week
};

export const disbursementSummary = {
  disbursedTotal: "UGX 170.4M",
  disbursedCount: 46,
  approvedTotal: "UGX 234.6M",
  pendingTotal: "UGX 64.2M",
  disbursedPct: 73,
  pendingPct: 27,
  weekly: [
    { week: "Wk 1", range: "Apr 28 – May 4",  amount: "UGX 28.4M", pct: 71 },
    { week: "Wk 2", range: "May 5 – May 11",  amount: "UGX 35.2M", pct: 88 },
    { week: "Wk 3", range: "May 12 – May 18", amount: "UGX 38.6M", pct: 96 },
    { week: "Wk 4", range: "May 19 – May 25", amount: "UGX 40.1M", pct: 100 },
    { week: "Wk 5", range: "May 26 – May 31", amount: "UGX 28.1M", pct: 70 },
  ] satisfies DisbursementWeek[],
};

// ────────── Plan Cost by Category donut ───────────────────────────────

export type CategoryShare = {
  label: string;
  amount: string;
  pct: number;
  color: string;
};

export const categoryShares: CategoryShare[] = [
  { label: "Travel",        amount: "UGX 65.8M", pct: 37, color: "#10B981" },
  { label: "Accommodation", amount: "UGX 35.6M", pct: 21, color: "#3B82F6" },
  { label: "Meals & Food",  amount: "UGX 28.4M", pct: 17, color: "#8B5CF6" },
  { label: "Training",      amount: "UGX 22.0M", pct: 13, color: "#F59E0B" },
  { label: "Materials",     amount: "UGX 12.6M", pct: 7,  color: "#F43F5E" },
  { label: "Other",         amount: "UGX 8.6M",  pct: 5,  color: "#94A3B8" },
];

export const categoryDisbursedTotal = "UGX 170.4M";

// ────────── Disbursement Queue table ──────────────────────────────────

export type QueueRow = {
  priority: "High" | "Medium" | "Low";
  requestId: string;
  requester: string;
  requesterRole: "CCEO";
  activity: string;
  amountUgx: number;
  approvedBy: string;
  approverRole: "PL";
  approvedOn: string;
  status: "Ready" | "Partial" | "On Hold";
};

export const queueRows: QueueRow[] = [
  { priority: "High",   requestId: "REQ-2505-1012", requester: "Sarah M.", requesterRole: "CCEO", activity: "Staff School Visits – Week 21", amountUgx: 24_600_000, approvedBy: "Peter K.", approverRole: "PL", approvedOn: "May 26, 2025", status: "Ready"  },
  { priority: "High",   requestId: "REQ-2505-1013", requester: "Grace A.", requesterRole: "CCEO", activity: "Cluster Training – Week 20",     amountUgx: 18_750_000, approvedBy: "Ruth W.",  approverRole: "PL", approvedOn: "May 26, 2025", status: "Ready"  },
  { priority: "Medium", requestId: "REQ-2505-1014", requester: "Joel O.",  requesterRole: "CCEO", activity: "Partner Follow-Up Visits",        amountUgx: 12_300_000, approvedBy: "Peter K.", approverRole: "PL", approvedOn: "May 25, 2025", status: "Ready"  },
  { priority: "Medium", requestId: "REQ-2505-1015", requester: "Moses T.", requesterRole: "CCEO", activity: "Transport – Supervision",         amountUgx: 8_600_000,  approvedBy: "Ruth W.",  approverRole: "PL", approvedOn: "May 25, 2025", status: "Partial"},
  { priority: "Low",    requestId: "REQ-2505-1016", requester: "Ruth K.",  requesterRole: "CCEO", activity: "In-School Training Materials",   amountUgx: 6_200_000,  approvedBy: "Peter K.", approverRole: "PL", approvedOn: "May 24, 2025", status: "Ready"  },
];

export const queueTabs = [
  { key: "all",     label: "All",               count: 12 },
  { key: "ready",   label: "Ready to Disburse", count: 8  },
  { key: "partial", label: "Partial",           count: 2  },
  { key: "hold",    label: "On Hold",           count: 1  },
  { key: "high",    label: "High Priority",     count: 4  },
] as const;

// ────────── NetSuite Expense ID status ─────────────────────────────────
//
// Staff's proof of accountability is the NetSuite Expense ID. Once
// they post the expense in NetSuite, they enter the Expense ID back
// here so the disbursement record is closed. Until they do, the
// disbursement is "Awaiting NetSuite ID".

export type ExpenseIdRow = {
  label: string;
  amount: string;
  pct: string;
  tone: "emerald" | "amber" | "rose";
};

export const expenseIdSummary: ExpenseIdRow[] = [
  { label: "Submitted on time", amount: "UGX 142.6M", pct: "72%", tone: "emerald" },
  { label: "Pending submission", amount: "UGX 28.7M",  pct: "15%", tone: "amber"   },
  { label: "Overdue",            amount: "UGX 28.7M",  pct: "13%", tone: "rose"    },
];

// Kept for backward-compat with existing imports.
export const accountabilitySummary = expenseIdSummary;
export type AccountabilityRow = ExpenseIdRow;

// ────────── Top Outstanding (no NetSuite ID yet) ──────────────────────

export type OutstandingExpenseIdRow = {
  staff: string;
  staffRole: "CCEO";
  initials: string;
  week: string;
  amount: string;
  daysOverdue: number;
  lastDisbursementId: string;
};

export const topOutstandingExpenseIds: OutstandingExpenseIdRow[] = [
  { staff: "Joel O.",    staffRole: "CCEO", initials: "JO", week: "Week 17 Report", amount: "UGX 8.9M", daysOverdue: 23, lastDisbursementId: "DSB-2505-0042" },
  { staff: "Lillian N.", staffRole: "CCEO", initials: "LN", week: "Week 18 Report", amount: "UGX 6.4M", daysOverdue: 18, lastDisbursementId: "DSB-2505-0049" },
  { staff: "David K.",   staffRole: "CCEO", initials: "DK", week: "Week 16 Report", amount: "UGX 5.2M", daysOverdue: 15, lastDisbursementId: "DSB-2505-0031" },
];

// Kept for backward-compat with existing imports.
export const topOverdue = topOutstandingExpenseIds;
export type OverdueRow = OutstandingExpenseIdRow;

// ────────── Upcoming Auto-Generated Requests ──────────────────────────
//
// Replaces the previous "Funds Received" register. This card surfaces
// what the system is about to auto-generate from approved monthly
// plans, so the accountant can anticipate the queue.

export type UpcomingAutoRequest = {
  scheduledFor: string;
  staff: string;
  staffRole: "CCEO";
  initials: string;
  activity: string;
  weekRange: string;
  estimatedCost: number;
  planId: string;
  status: "Scheduled" | "Generated" | "Submitted" | "Awaiting Approval";
};

export const upcomingAutoRequests: UpcomingAutoRequest[] = [
  { scheduledFor: "May 27, 2025", staff: "Sarah M.", staffRole: "CCEO", initials: "SM", activity: "School Visits – Week 22", weekRange: "May 26 – Jun 1",  estimatedCost: 26_400_000, planId: "PLAN-2505-SM-W22", status: "Scheduled" },
  { scheduledFor: "May 27, 2025", staff: "Grace A.", staffRole: "CCEO", initials: "GA", activity: "Cluster Training – W22",  weekRange: "May 26 – Jun 1",  estimatedCost: 19_200_000, planId: "PLAN-2505-GA-W22", status: "Scheduled" },
  { scheduledFor: "May 26, 2025", staff: "Joel O.",  staffRole: "CCEO", initials: "JO", activity: "Partner Follow-Up – W22", weekRange: "May 26 – Jun 1", estimatedCost: 13_100_000, planId: "PLAN-2505-JO-W22", status: "Generated" },
  { scheduledFor: "May 25, 2025", staff: "Moses T.", staffRole: "CCEO", initials: "MT", activity: "Supervision Transport",   weekRange: "May 26 – Jun 1",  estimatedCost: 9_200_000,  planId: "PLAN-2505-MT-W22", status: "Submitted" },
  { scheduledFor: "May 25, 2025", staff: "Ruth K.",  staffRole: "CCEO", initials: "RK", activity: "Training Materials – W22",weekRange: "May 26 – Jun 1",  estimatedCost: 6_400_000,  planId: "PLAN-2505-RK-W22", status: "Awaiting Approval" },
];

// Funds Received This Month — money that has hit the country account
// from RVP/HQ. This is the inflow side of the fund flow story; the
// outflow side is the disbursement queue + recent disbursements.
export type FundsReceivedRow = {
  date: string;
  source: string;
  description: string;
  amountUgx: number;
  reference: string;
  receivedBy: string;
};

export const fundsReceivedRows: FundsReceivedRow[] = [
  { date: "May 05, 2025", source: "RVP / HQ Transfer",       description: "May 2025 Country Budget Transfer",      amountUgx: 250_000_000, reference: "TRF-2505-0001", receivedBy: "Moses T." },
  { date: "May 12, 2025", source: "RVP / HQ Transfer",       description: "Discipleship Clubs grant — Q2 tranche", amountUgx:  48_400_000, reference: "TRF-2505-0003", receivedBy: "Moses T." },
  { date: "May 18, 2025", source: "Bank Interest",           description: "USD account quarterly interest",        amountUgx:   1_600_000, reference: "INT-2505-0014", receivedBy: "Moses T." },
  { date: "May 20, 2025", source: "Additional Funding",      description: "Cluster Training Top-up",               amountUgx: 135_600_000, reference: "TRF-2505-0002", receivedBy: "Moses T." },
  { date: "May 24, 2025", source: "Field Balance Return",    description: "Week 19 unused field funds returned",   amountUgx:     780_000, reference: "BAL-2505-0021", receivedBy: "Moses T." },
];

// ────────── Recent Disbursements ──────────────────────────────────────
//
// Recent row now carries an optional `netsuiteExpenseId` field. When
// present, the row shows the ID as the proof of accountability. When
// absent, the row shows "Awaiting NetSuite ID".

export type RecentDisbursement = {
  staff: string;
  staffRole: "CCEO";
  initials: string;
  purpose: string;
  amount: string;
  date: string;
  status: "Disbursed";
  disbursementId: string;
  netsuiteExpenseId?: string;
};

export const recentDisbursements: RecentDisbursement[] = [
  { staff: "Sarah M.", staffRole: "CCEO", initials: "SM", purpose: "Staff Visits – Week 20", amount: "UGX 22.4M", date: "May 26, 2025", status: "Disbursed", disbursementId: "DSB-2505-0061", netsuiteExpenseId: "558204" },
  { staff: "Peter K.", staffRole: "CCEO", initials: "PK", purpose: "Partner Visits",         amount: "UGX 18.0M", date: "May 25, 2025", status: "Disbursed", disbursementId: "DSB-2505-0058" },
  { staff: "Grace A.", staffRole: "CCEO", initials: "GA", purpose: "Cluster Training",       amount: "UGX 16.7M", date: "May 24, 2025", status: "Disbursed", disbursementId: "DSB-2505-0055", netsuiteExpenseId: "558180" },
];

// ────────── Quick Actions ─────────────────────────────────────────────
//
// Edify-native actions only. NetSuite-overlap actions removed (Bank
// Reconciliation, Audit Trail, Export Ledger). Replaced with planning
// + workflow + NetSuite Sync.

export type QuickAction = {
  key: string;
  label: string;
  iconKey:
    | "logFunds"
    | "disburse"
    | "partial"
    | "hold"
    | "exportLedger"
    | "reconcile"
    | "report"
    | "audit";
  tone: "emerald" | "blue" | "amber" | "rose" | "violet" | "slate";
};

export const quickActions: QuickAction[] = [
  { key: "logFunds",  label: "Log Funds Received",   iconKey: "logFunds",     tone: "emerald" },
  { key: "disb",      label: "Disburse Funds",       iconKey: "disburse",     tone: "blue"    },
  { key: "partial",   label: "Partial Disbursement", iconKey: "partial",      tone: "amber"   },
  { key: "hold",      label: "Hold Request",         iconKey: "hold",         tone: "rose"    },
  { key: "ledger",    label: "Export Ledger",        iconKey: "exportLedger", tone: "violet"  },
  { key: "reconcile", label: "Bank Reconciliation",  iconKey: "reconcile",    tone: "slate"   },
  { key: "report",    label: "Accountability Report",iconKey: "report",       tone: "emerald" },
  { key: "audit",     label: "Audit Trail",          iconKey: "audit",        tone: "rose"    },
];

// ────────── Sidebar items ─────────────────────────────────────────────

export type ConsoleNavItem = {
  key: string;
  label: string;
  iconKey:
    | "dashboard"
    | "queue"
    | "disbursements"
    | "fundsReceived"
    | "budget"
    | "approvals"
    | "accountability"
    | "reports"
    | "users"
    | "rules"
    | "settings";
  badge?: number;
};

export const consoleMainNav: ConsoleNavItem[] = [
  { key: "dashboard",      label: "Dashboard",             iconKey: "dashboard" },
  { key: "queue",          label: "Disbursement Queue",    iconKey: "queue", badge: 12 },
  { key: "disbursements",  label: "Disbursements",         iconKey: "disbursements" },
  { key: "fundsReceived",  label: "Funds Received",        iconKey: "fundsReceived" },
  { key: "budget",         label: "Budget & Plans",        iconKey: "budget" },
  { key: "approvals",      label: "Approvals",             iconKey: "approvals" },
  { key: "accountability", label: "Accountability Tracker",iconKey: "accountability" },
  { key: "reports",        label: "Reports",               iconKey: "reports" },
];

export const consoleSettingsNav: ConsoleNavItem[] = [
  { key: "users",    label: "Users & Roles",       iconKey: "users" },
  { key: "rules",    label: "Disbursement Rules",  iconKey: "rules" },
  { key: "settings", label: "System Settings",     iconKey: "settings" },
];

// ────────── Receipt Confirmation Tracker (mock) ───────────────────────
//
// Disbursements that have been released but the staff member hasn't
// confirmed receipt yet. Surfaces the operational gap between
// "money sent" and "money received". After confirmation the row drops
// off this tracker and the accountability section unlocks.

export type ReceiptTrackerRow = {
  id: string;
  staff: string;
  staffRole: "CCEO";
  initials: string;
  amountUgx: number;
  disbursedDate: string;
  hoursSince: number;
  disbursementId: string;
  status: "Awaiting" | "Confirmed" | "Disputed";
};

export const receiptTrackerRows: ReceiptTrackerRow[] = [
  { id: "RCP-2505-201", staff: "Sarah M.",   staffRole: "CCEO", initials: "SM", amountUgx: 24_600_000, disbursedDate: "May 26, 2025", hoursSince: 4,  disbursementId: "DSB-2505-0067", status: "Awaiting" },
  { id: "RCP-2505-202", staff: "Grace A.",   staffRole: "CCEO", initials: "GA", amountUgx: 18_750_000, disbursedDate: "May 26, 2025", hoursSince: 6,  disbursementId: "DSB-2505-0068", status: "Awaiting" },
  { id: "RCP-2505-203", staff: "Joel O.",    staffRole: "CCEO", initials: "JO", amountUgx: 12_300_000, disbursedDate: "May 24, 2025", hoursSince: 54, disbursementId: "DSB-2505-0061", status: "Awaiting" },
  { id: "RCP-2505-204", staff: "Ruth K.",    staffRole: "CCEO", initials: "RK", amountUgx: 6_200_000,  disbursedDate: "May 24, 2025", hoursSince: 50, disbursementId: "DSB-2505-0060", status: "Disputed" },
  { id: "RCP-2505-205", staff: "Moses T.",   staffRole: "CCEO", initials: "MT", amountUgx: 8_600_000,  disbursedDate: "May 25, 2025", hoursSince: 30, disbursementId: "DSB-2505-0064", status: "Awaiting" },
  { id: "RCP-2505-206", staff: "Peter K.",   staffRole: "CCEO", initials: "PK", amountUgx: 18_000_000, disbursedDate: "May 25, 2025", hoursSince: 12, disbursementId: "DSB-2505-0058", status: "Confirmed" },
  { id: "RCP-2505-207", staff: "Lillian N.", staffRole: "CCEO", initials: "LN", amountUgx: 14_400_000, disbursedDate: "May 24, 2025", hoursSince: 20, disbursementId: "DSB-2505-0059", status: "Confirmed" },
  { id: "RCP-2505-208", staff: "David K.",   staffRole: "CCEO", initials: "DK", amountUgx: 9_800_000,  disbursedDate: "May 23, 2025", hoursSince: 18, disbursementId: "DSB-2505-0055", status: "Confirmed" },
];

// ────────── Reimbursement Queue (mock) ────────────────────────────────
//
// Staff who used personal money on planned activities and have
// submitted a Personal Funds Claim with a NetSuite Expense ID.

export type ReimbursementRow = {
  id: string;
  staff: string;
  staffRole: "CCEO" | "ProgramLead" | "ImpactAssessment" | "ProgramAccountant" | "SpecialProjectsCoordinator" | "Admin";
  initials: string;
  activity: string;
  weekRange: string;
  amountSpentUgx: number;
  amountDisbursedUgx: number;
  amountToReimburseUgx: number;
  netsuiteExpenseId: string;
  reason: string;
  approvalRoute: "ProgramLead" | "CountryDirector" | "AccountantReview";
  status:
    | "Submitted"
    | "Supervisor Review"
    | "Queued for Accountant"
    | "Returned for Correction"
    | "Reimbursed";
  submittedAt: string;
  // New: provenance + threshold for auto-created claims
  autoCreated?: boolean;             // true → originated from reconciliation overspend
  fundReconciliationId?: string;     // links back to the reconciliation record
  overspendPct?: number;             // (spent − advanced) / advanced × 100
  thresholdFlag?: "Normal" | "HighOverspend" | "RequiresCDReview";
};

export const reimbursementQueue: ReimbursementRow[] = [
  {
    id: "REIM-2505-014",
    staff: "Sarah M.",
    staffRole: "CCEO",
    initials: "SM",
    activity: "Emergency transport — flood detour, Naguru cluster",
    weekRange: "May 19 – May 25",
    amountSpentUgx: 480_000,
    amountDisbursedUgx: 300_000,
    amountToReimburseUgx: 180_000,
    netsuiteExpenseId: "4812",
    reason: "Disbursement covered only main route; flood required boda detour",
    approvalRoute: "ProgramLead",
    status: "Queued for Accountant",
    submittedAt: "May 26, 2025",
    autoCreated: true,
    fundReconciliationId: "RCN-2505-0091",
    overspendPct: 60,
    thresholdFlag: "RequiresCDReview",
  },
  {
    id: "REIM-2505-015",
    staff: "Daniel M.",
    staffRole: "ProgramLead",
    initials: "DM",
    activity: "Cluster venue deposit — Lugazi training",
    weekRange: "May 12 – May 18",
    amountSpentUgx: 720_000,
    amountDisbursedUgx: 0,
    amountToReimburseUgx: 720_000,
    netsuiteExpenseId: "4791",
    reason: "Venue required same-day deposit; waited for plan approval afterwards",
    approvalRoute: "CountryDirector",
    status: "Supervisor Review",
    submittedAt: "May 25, 2025",
  },
  {
    id: "REIM-2505-016",
    staff: "Grace A.",
    staffRole: "CCEO",
    initials: "GA",
    activity: "Printing — Week 20 cluster materials",
    weekRange: "May 12 – May 18",
    amountSpentUgx: 220_000,
    amountDisbursedUgx: 180_000,
    amountToReimburseUgx: 40_000,
    netsuiteExpenseId: "4803",
    reason: "Print run extended after head-teacher request for extra copies",
    approvalRoute: "ProgramLead",
    status: "Submitted",
    submittedAt: "May 24, 2025",
  },
  {
    id: "REIM-2505-017",
    staff: "Lillian A.",
    staffRole: "SpecialProjectsCoordinator",
    initials: "LA",
    activity: "Discipleship Clubs launch — catering top-up",
    weekRange: "May 19 – May 25",
    amountSpentUgx: 950_000,
    amountDisbursedUgx: 600_000,
    amountToReimburseUgx: 350_000,
    netsuiteExpenseId: "4817",
    reason: "Attendance exceeded plan; CD authorised top-up via SMS",
    approvalRoute: "CountryDirector",
    status: "Queued for Accountant",
    submittedAt: "May 26, 2025",
  },
  {
    id: "REIM-2505-018",
    staff: "Ruth K.",
    staffRole: "CCEO",
    initials: "RK",
    activity: "Boda transport — last-mile village walk",
    weekRange: "May 19 – May 25",
    amountSpentUgx: 65_000,
    amountDisbursedUgx: 30_000,
    amountToReimburseUgx: 35_000,
    netsuiteExpenseId: "4820",
    reason: "Road washed out; took two boda legs to reach St Mary's",
    approvalRoute: "ProgramLead",
    status: "Returned for Correction",
    submittedAt: "May 23, 2025",
    autoCreated: true,
    fundReconciliationId: "RCN-2505-0118",
    overspendPct: 116,
    thresholdFlag: "RequiresCDReview",
  },
  {
    id: "REIM-2505-019",
    staff: "Paul Chinyama",
    staffRole: "CCEO",
    initials: "PC",
    activity: "Week 2 Field Funds — full reconciliation",
    weekRange: "May 12 – May 18",
    amountSpentUgx: 2_120_000,
    amountDisbursedUgx: 1_850_000,
    amountToReimburseUgx: 270_000,
    netsuiteExpenseId: "4781",
    reason: "Overnight stay added · Mubende cluster scheduled by PL",
    approvalRoute: "ProgramLead",
    status: "Queued for Accountant",
    submittedAt: "May 26, 2025",
    autoCreated: true,
    fundReconciliationId: "RCN-2505-0142",
    overspendPct: 14.59,
    thresholdFlag: "Normal",
  },
];

// ────────── Balance Return Queue ──────────────────────────────────────
//
// Created automatically when amount spent < amount advanced. Staff
// must declare the return method (MobileMoney / Bank / Cash / Offset)
// before the accountability can close.

export type BalanceReturnRow = {
  id: string;
  staff: string;
  staffRole: "CCEO";
  initials: string;
  weekLabel: string;
  amountAdvancedUgx: number;
  amountSpentUgx: number;
  balanceToReturnUgx: number;
  netsuiteExpenseId: string;
  method?: "MobileMoney" | "Bank" | "Cash" | "OffsetAgainstNextRequest";
  reference?: string;
  status: "Pending" | "Confirmed" | "Disputed";
  createdAt: string;
};

export const balanceReturnQueue: BalanceReturnRow[] = [
  {
    id: "BAL-2505-021",
    staff: "Joseph N.",
    staffRole: "CCEO",
    initials: "JN",
    weekLabel: "Week 19 field funds",
    amountAdvancedUgx: 1_650_000,
    amountSpentUgx: 1_460_000,
    balanceToReturnUgx: 190_000,
    netsuiteExpenseId: "4769",
    status: "Pending",
    createdAt: "May 24, 2025",
  },
  {
    id: "BAL-2505-022",
    staff: "Aisha N.",
    staffRole: "CCEO",
    initials: "AN",
    weekLabel: "Week 20 field funds",
    amountAdvancedUgx: 980_000,
    amountSpentUgx: 920_000,
    balanceToReturnUgx: 60_000,
    netsuiteExpenseId: "4794",
    method: "MobileMoney",
    reference: "MPSA-XKQE-2271",
    status: "Confirmed",
    createdAt: "May 25, 2025",
  },
  {
    id: "BAL-2505-023",
    staff: "Simon O.",
    staffRole: "CCEO",
    initials: "SO",
    weekLabel: "Week 18 field funds",
    amountAdvancedUgx: 2_100_000,
    amountSpentUgx: 1_580_000,
    balanceToReturnUgx: 520_000,
    netsuiteExpenseId: "4752",
    status: "Pending",
    createdAt: "May 22, 2025",
  },
];
