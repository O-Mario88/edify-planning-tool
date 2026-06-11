// Weekly Fund Request + Field Disbursement — Type Layer
//
// This module is the single source of truth for the auto-generated
// weekly fund pipeline. The chain runs:
//
//   Approved Monthly Plan
//     → System breaks plan into 4 weekly Fund Requests per staff
//     → Staff confirms activities + costs   (DRAFT → SUBMITTED)
//     → Program Lead reviews                 (SUBMITTED → APPROVED / RETURNED)
//     → Accountant confirms funds-received   (APPROVED → READY_TO_DISBURSE)
//     → Accountant disburses                 (READY_TO_DISBURSE → DISBURSED)
//     → Staff confirms receipt               (DISBURSED → RECEIVED)
//     → Staff executes activities            (RECEIVED → IN_USE)
//     → Staff submits accountability         (IN_USE → ACCOUNTABILITY_SUBMITTED)
//     → Lead approves accountability         (ACCOUNTABILITY_SUBMITTED → CLOSED)
//
// Failure / control branches:
//   - CANCELLED            — request voided before disbursement
//   - RETURNED_TO_STAFF    — Lead bounced; staff must fix and resubmit
//   - ACCOUNTABILITY_RETURNED — Lead bounced accountability; staff must fix
//   - HOLD_NO_FUNDS_AVAILABLE — Accountant has no funds received yet
//   - BLOCKED_PRIOR_OUTSTANDING — previous week not closed → release locked
//
// Every state transition writes a WeeklyFundAuditEvent with the actor,
// timestamp, before/after status, and a free-text note. The audit log
// is the legal record for finance compliance.

// ────────── Core status flow ──────────────────────────────────────────

export type WeeklyFundRequestStatus =
  // Lifecycle BEFORE money moves
  | "AUTO_GENERATED"            // System created from approved plan; staff hasn't touched it
  | "DRAFT"                     // Staff opened and is editing
  | "SUBMITTED"                 // Staff confirmed; waiting on Lead
  | "RETURNED_TO_STAFF"         // Lead bounced for edits
  | "APPROVED"                  // Lead green-lit; waiting on funds at Accountant
  | "CANCELLED"                 // Voided before disbursement (audited)
  // Lifecycle while money moves
  | "HOLD_NO_FUNDS_AVAILABLE"   // Accountant has nothing to disburse
  | "BLOCKED_PRIOR_OUTSTANDING" // Previous week not accounted for
  | "READY_TO_DISBURSE"         // Funds confirmed received at country level
  | "DISBURSED"                 // Accountant sent funds to staff
  | "RECEIVED"                  // Staff confirmed receipt
  | "IN_USE"                    // Staff executing activities this week
  // Lifecycle AFTER money moves
  | "ACCOUNTABILITY_SUBMITTED"  // Staff submitted receipts/notes
  | "ACCOUNTABILITY_RETURNED"   // Lead bounced for missing receipts
  | "ACCOUNTABILITY_APPROVED"   // Lead approved — week can close
  | "CLOSED"                    // Final state; counted for next-week gate
  | "ARCHIVED";                 // Soft-frozen for audit retention only

// ────────── Status grouping (UI helpers) ──────────────────────────────

export const PRE_APPROVAL_STATUSES: WeeklyFundRequestStatus[] = [
  "AUTO_GENERATED",
  "DRAFT",
  "SUBMITTED",
  "RETURNED_TO_STAFF",
];

export const PENDING_LEAD_STATUSES: WeeklyFundRequestStatus[] = [
  "SUBMITTED",
];

export const PENDING_ACCOUNTANT_STATUSES: WeeklyFundRequestStatus[] = [
  "APPROVED",
  "HOLD_NO_FUNDS_AVAILABLE",
  "BLOCKED_PRIOR_OUTSTANDING",
  "READY_TO_DISBURSE",
];

export const IN_FIELD_STATUSES: WeeklyFundRequestStatus[] = [
  "DISBURSED",
  "RECEIVED",
  "IN_USE",
];

export const ACCOUNTABILITY_STATUSES: WeeklyFundRequestStatus[] = [
  "ACCOUNTABILITY_SUBMITTED",
  "ACCOUNTABILITY_RETURNED",
  "ACCOUNTABILITY_APPROVED",
];

export const TERMINAL_STATUSES: WeeklyFundRequestStatus[] = [
  "CLOSED",
  "CANCELLED",
  "ARCHIVED",
];

// ────────── Currency / period helpers ─────────────────────────────────

export type Money = {
  amount: number;       // canonical units (UGX shillings, no fractions)
  currency: "UGX" | "USD" | "KES";
};

export type WeekOfMonth = 1 | 2 | 3 | 4;

export type FiscalPeriod = {
  fyLabel: string;       // "FY 2026"
  quarter: "Q1" | "Q2" | "Q3" | "Q4";
  monthLabel: string;    // "May 2026"
  monthIso: string;      // "2026-05"
  weekOfMonth: WeekOfMonth;
  weekStartIso: string;  // "2026-05-13"  (Monday)
  weekEndIso: string;    // "2026-05-17"  (Friday)
};

// ────────── Activity inside a weekly request ──────────────────────────
//
// Each activity is a row sourced from the approved monthly plan.
// `originPlanLineId` lets us reconcile back to plan-level totals so
// we never disburse more than was approved.

export type WeeklyActivityKind =
  | "SchoolVisit"
  | "Cluster"
  | "TeacherTraining"
  | "FollowUp"
  | "StakeholderMeeting"
  | "Other";

export type WeeklyFundRequestActivity = {
  id: string;
  originPlanLineId: string;       // ties back to the approved monthly plan
  kind: WeeklyActivityKind;
  title: string;
  schoolName?: string;
  district?: string;
  plannedDay: string;             // "Mon 13", "Tue 14"…
  costBreakdown: WeeklyFundCostBreakdown;
  totalCost: Money;
  status: "Planned" | "Confirmed" | "Adjusted" | "Cancelled" | "Moved";
  note?: string;
};

// Five fixed cost dimensions — matches the cost-settings rules across
// the platform (transport, allowance, meals, materials, misc).
export type WeeklyFundCostBreakdown = {
  transport: Money;
  allowance: Money;
  meals: Money;
  materials: Money;
  misc: Money;
};

// ────────── Adjustment block (staff edits before submit) ──────────────

export type WeeklyActivityAdjustment = {
  activityId: string;
  type: "NewActivity" | "MovedFromAnotherWeek" | "Cancelled" | "CostAdjusted";
  reason: string;                  // mandatory note — audit trail
  costDelta?: Money;               // ± change in total request value
  requiresLeadReApproval: boolean; // true when delta crosses tolerance
};

// ────────── Requester role + approver routing ────────────────────────
//
// The system auto-routes requests to the correct approver:
//   • CCEO weekly requests          → Program Lead
//   • PL / IA / Accountant / SP / Admin → Country Director
//
// RVP sits above both, but RVP only approves the country *monthly
// budget envelope*, not individual weekly requests.

export type RequesterRole =
  | "CCEO"
  | "ProgramLead"
  | "ProgramAccountant"
  | "ImpactAssessment"
  | "SpecialProjectsCoordinator"
  | "Admin";

export type ApproverRole = "ProgramLead" | "CountryDirector";

export const REQUESTER_LABEL: Record<RequesterRole, string> = {
  CCEO:                       "CCEO",
  ProgramLead:                "Program Lead",
  ProgramAccountant:          "Accountant",
  ImpactAssessment:           "Impact Assessment",
  SpecialProjectsCoordinator: "Special Projects",
  Admin:                      "Admin / Ops",
};

// Risk surfacing — small enum used by the PL/CD queues as chip badges.
export type RiskFlag =
  | "PreviousAccountabilityPending"
  | "ExceedsApprovedWeeklyPlan"
  | "ActivityMovedAfterApproval"
  | "StaffOnLeave"
  | "HighTransportVariance"
  | "OvernightCostUnusual"
  | "MissingSalesforceIds"
  | "MissingParticipantCount";

export const RISK_LABEL: Record<RiskFlag, string> = {
  PreviousAccountabilityPending: "Prior accountability pending",
  ExceedsApprovedWeeklyPlan:     "Exceeds weekly plan",
  ActivityMovedAfterApproval:    "Activity moved after approval",
  StaffOnLeave:                  "Staff on leave",
  HighTransportVariance:         "High transport variance",
  OvernightCostUnusual:          "Overnight cost unusual",
  MissingSalesforceIds:          "Missing Salesforce IDs",
  MissingParticipantCount:       "Missing participant count",
};

// ────────── Weekly fund request entity ────────────────────────────────

export type WeeklyFundRequest = {
  id: string;                      // "WFR-2026-05-W2-STF-PC-001"
  staffId: string;
  staffName: string;
  staffRole: "CCEO" | "Cluster" | "Trainer" | "Other";
  // Refined role-aware fields (new — older mocks still use staffRole).
  requesterRole?: RequesterRole;
  approverRole?: ApproverRole;
  district: string;
  programLeadId: string;
  programLeadName: string;
  countryId: string;
  monthlyPlanId: string;           // origin plan
  weeklyPlanId?: string;           // the specific weekly plan this is auto-extracted from
  period: FiscalPeriod;

  status: WeeklyFundRequestStatus;

  // The plan-derived total (immutable, from approved monthly plan)
  plannedAmount: Money;
  // The current request total (may diverge from planned via adjustments)
  requestedAmount: Money;
  // What the Accountant actually disbursed (≤ requestedAmount)
  disbursedAmount?: Money;
  // What the staff accounted for at week close
  accountedAmount?: Money;
  // Unspent funds returned to the office
  returnedAmount?: Money;

  activities: WeeklyFundRequestActivity[];
  adjustments: WeeklyActivityAdjustment[];
  // Surfaces in PL/CD queues. Engine recomputes whenever activities,
  // adjustments, or accountability state change.
  risks?: RiskFlag[];

  // Lifecycle pointers (latest event of each kind for fast UI lookup)
  submittedAt?: string;
  approvedAt?: string;
  approvedByLeadId?: string;
  // IA verification gate (punch-list B12). When set, the Accountant
  // can mark Ready-to-Disburse and disburse. CCEO requests stay
  // gated until IA confirms; PL/IA/Accountant/Admin requests skip
  // this gate (they don't carry the CCEO data-quality risk profile).
  iaVerifiedAt?: string;
  iaVerifiedById?: string;
  disbursedAt?: string;
  disbursedByAccountantId?: string;
  receivedAt?: string;
  accountabilitySubmittedAt?: string;
  accountabilityApprovedAt?: string;
  closedAt?: string;

  // Control flags
  flags: WeeklyFundBlocker[];
  notes: string;
  source: "AUTO_FROM_PLAN" | "MANUAL_AD_HOC";  // ad-hoc must be flagged
};

// ────────── Blockers (engine outputs) ─────────────────────────────────

export type WeeklyFundBlocker =
  | "PRIOR_WEEK_NOT_CLOSED"
  | "FUNDS_NOT_RECEIVED_AT_COUNTRY"
  | "OVER_PLAN_TOLERANCE"
  | "MISSING_LEAD_APPROVAL"
  | "MISSING_RECEIPTS"
  | "ACTIVITY_NOT_ON_APPROVED_PLAN"
  | "STAFF_ON_LEAVE";

// ────────── Funds received at country level ───────────────────────────
//
// The Accountant cannot disburse to staff until this country-level
// register confirms that funds have actually been received from the
// regional office (the "treasury receipt"). All disbursements are
// drawn against one or more `FundsReceivedRecord`s and consume their
// `availableBalance`.

export type FundsReceivedRecord = {
  id: string;                      // "FR-2026-05-001"
  countryId: string;
  receivedOnIso: string;           // "2026-05-12"
  fromSource: "RVP_OFFICE" | "HQ_TREASURY" | "PARTNER";
  reference: string;               // bank reference / wire id
  totalReceived: Money;
  totalAllocated: Money;           // sum of disbursements drawn from it
  availableBalance: Money;
  monthLabel: string;              // "May 2026"
  notes?: string;
  confirmedByAccountantId: string;
  confirmedAt: string;
};

// ────────── Disbursement record ───────────────────────────────────────

export type DisbursementMethod =
  | "MobileMoney"
  | "BankTransfer"
  | "Cash"
  | "Cheque";

export type DisbursementRecord = {
  id: string;                      // "DSB-2026-05-W2-001"
  weeklyFundRequestId: string;
  fundsReceivedId: string;         // which treasury batch this drew from
  staffId: string;
  staffName: string;
  amount: Money;
  method: DisbursementMethod;
  reference: string;               // M-Pesa code, cheque #, etc
  disbursedAt: string;
  disbursedByAccountantId: string;
  disbursedByAccountantName: string;
  receiptConfirmedByStaffAt?: string;
  receiptNote?: string;
  reversed: boolean;
  reversedAt?: string;
  reversedReason?: string;
};

// ────────── Audit trail event ─────────────────────────────────────────

export type WeeklyFundAuditAction =
  | "AUTO_GENERATED"
  | "OPENED"
  | "EDITED"
  | "ADJUSTMENT_ADDED"
  | "SUBMITTED"
  | "APPROVED"
  | "RETURNED"
  | "CANCELLED"
  | "FUNDS_CONFIRMED_AT_COUNTRY"
  | "DISBURSED"
  | "RECEIPT_CONFIRMED"
  | "ACCOUNTABILITY_SUBMITTED"
  | "ACCOUNTABILITY_APPROVED"
  | "ACCOUNTABILITY_RETURNED"
  | "CLOSED"
  | "BLOCKER_RAISED"
  | "BLOCKER_CLEARED"
  | "OVERRIDE";

export type WeeklyFundAuditEvent = {
  id: string;
  weeklyFundRequestId: string;
  action: WeeklyFundAuditAction;
  fromStatus?: WeeklyFundRequestStatus;
  toStatus?: WeeklyFundRequestStatus;
  actorId: string;
  actorName: string;
  actorRole: "Staff" | "ProgramLead" | "Accountant" | "Director" | "System";
  at: string;                      // ISO timestamp
  note?: string;
  delta?: Money;                   // when relevant (cost change, disbursement)
};

// ────────── Notifications (out-channel) ───────────────────────────────

export type WeeklyFundNotification = {
  id: string;
  weeklyFundRequestId: string;
  audienceRole: "Staff" | "ProgramLead" | "Accountant" | "Director";
  audienceUserId: string;
  channel: "Inbox" | "Email" | "SMS";
  template:
    | "REQUEST_AUTO_GENERATED"
    | "REQUEST_SUBMITTED"
    | "REQUEST_RETURNED"
    | "REQUEST_APPROVED"
    | "REQUEST_DISBURSED"
    | "RECEIPT_REMINDER"
    | "ACCOUNTABILITY_DUE"
    | "ACCOUNTABILITY_OVERDUE"
    | "ACCOUNTABILITY_APPROVED";
  sentAt: string;
  readAt?: string;
};

// ────────── Staff balance (rolling view) ──────────────────────────────

export type StaffFundBalance = {
  staffId: string;
  staffName: string;
  district: string;
  openDisbursed: Money;            // money in field
  openAccounted: Money;            // partially returned receipts
  outstanding: Money;              // openDisbursed - openAccounted
  weeksOutstanding: number;        // count of unclosed weeks
  oldestWeekIso?: string;
  flagged: boolean;                // outstanding > tolerance OR > 2 weeks
};

// ────────── Receipt Confirmation, Accountability, Reimbursement ──────
//
// These types model the post-disbursement chain:
//
//   Accountant clicks Mark Disbursed
//   → staff notified
//   → staff confirms receipt
//   → accountability section unlocks
//   → staff completes accountability in NetSuite
//   → staff pastes NetSuite Expense ID into Edify
//   → accountant reviews + approves
//   → future releases are unlocked only after accountability is complete
//
// Reimbursement claims (staff used own money) live in a parallel flow.
// Edify never tries to do NetSuite accounting — it only captures the
// NetSuite Expense ID as proof + the operational trace.

export type FundReceiptConfirmation = {
  id: string;
  fundRequestId: string;
  disbursementId: string;
  staffId: string;
  staffName: string;
  amountDisbursedUgx: number;
  amountReceivedUgx: number;
  confirmedAt?: string;             // when staff clicked Confirm
  status: "Awaiting" | "Confirmed" | "Disputed";
  discrepancyAmountUgx?: number;
  comment?: string;
  // Operational hint — set when staff hasn't confirmed within tolerance.
  hoursSinceDisbursed: number;
};

export type AccountabilityStatus =
  | "Not Open"                  // disbursement not received yet
  | "Open"                      // unlocked, awaiting NS ID submission
  | "NetSuite ID Submitted"
  | "Under Accountant Review"
  | "Returned for Correction"
  | "Approved"
  | "Closed";

export type FundAccountability = {
  id: string;
  fundRequestId: string;
  disbursementId: string;
  staffId: string;
  staffName: string;
  weekLabel: string;            // "Week 2" — for UI grouping

  netsuiteExpenseId?: string;   // pasted from NetSuite after acquittal
  amountDisbursedUgx: number;
  amountSpentUgx?: number;
  balanceToReturnUgx?: number;  // disbursed − spent (≥ 0)
  overspendUgx?: number;        // spent − disbursed (≥ 0, drives reimbursement)

  accountabilityNote?: string;
  evidenceLinks?: string[];

  status: AccountabilityStatus;

  submittedAt?: string;
  reviewedBy?: string;
  reviewedAt?: string;
  returnedReason?: string;
};

export type ReimbursementApprovalRoute =
  | "ProgramLead"        // CCEO claims — PL verifies activity
  | "CountryDirector"    // PL/IA/Accountant/SP/Admin claims — CD verifies
  | "AccountantReview";  // direct accountant-only path

export type ReimbursementStatus =
  | "Draft"
  | "Submitted"
  | "Supervisor Review"
  | "Approved for Reimbursement"
  | "Returned for Correction"
  | "Queued for Accountant"
  | "Reimbursed"
  | "Closed";

// Why the overspend happened — picker shown to staff when amount
// spent exceeds amount advanced. Drives the reimbursement reason.
export type OverspendReason =
  | "TransportCostIncreased"
  | "AdditionalApprovedSchoolAdded"
  | "OvernightStayBecameNecessary"
  | "TrainingParticipantsExceeded"
  | "RouteChangedDueToFieldConditions"
  | "EmergencyFieldExpense"
  | "Other";

export const OVERSPEND_REASON_LABEL: Record<OverspendReason, string> = {
  TransportCostIncreased:          "Transport cost increased",
  AdditionalApprovedSchoolAdded:   "Additional approved school added",
  OvernightStayBecameNecessary:    "Overnight stay became necessary",
  TrainingParticipantsExceeded:    "Training participants exceeded plan",
  RouteChangedDueToFieldConditions:"Route changed due to field conditions",
  EmergencyFieldExpense:           "Emergency field expense",
  Other:                           "Other (explain below)",
};

// Threshold flag on auto-reimbursements. When overspend ≥ 15 % of the
// advanced amount, escalate to Country Director instead of the Lead.
export type OverspendThresholdFlag =
  | "Normal"
  | "HighOverspend"
  | "RequiresCDReview";

// Outcome of reconciliation — the deterministic answer to "did spent
// equal, undershoot, or overshoot the advanced amount?"
export type ReconciliationOutcome =
  | "Fully Accounted"
  | "Balance To Return"
  | "Reimbursement Due";

// Reconciliation record — the single source of truth for the
// difference between advanced and spent. It owns the side-effect
// pointers to the auto-created reimbursement or balance-return record.
export type FundReconciliation = {
  id: string;
  fundRequestId: string;
  disbursementId: string;
  staffId: string;
  staffName: string;

  netsuiteExpenseId: string;

  advancedAmountUgx: number;
  amountReceivedUgx: number;
  amountSpentUgx: number;

  differenceUgx: number;            // spent − advanced (signed)

  outcome: ReconciliationOutcome;

  balanceToReturnUgx: number;       // ≥ 0
  reimbursementDueUgx: number;      // ≥ 0
  overspendPct: number;             // (spent − advanced) / advanced × 100
  thresholdFlag: OverspendThresholdFlag;

  overspendReason?: OverspendReason;
  overspendNote?: string;
  accountabilityNote?: string;

  status:
    | "Draft"
    | "Submitted"
    | "Under Accountant Review"
    | "Returned for Correction"
    | "Approved"
    | "Closed";

  createdAutoReimbursementId?: string;
  createdBalanceReturnId?: string;

  submittedAt?: string;
  reviewedBy?: string;
  reviewedAt?: string;
  returnedReason?: string;
};

// Balance Return — created when amount spent < amount advanced. Staff
// must confirm *how* they returned the unused funds before the
// accountability closes.
export type BalanceReturnMethod =
  | "MobileMoney"
  | "Bank"
  | "Cash"
  | "OffsetAgainstNextRequest";

export type BalanceReturnStatus =
  | "Pending"
  | "Confirmed"
  | "Disputed";

export type BalanceReturn = {
  id: string;
  fundReconciliationId: string;
  fundRequestId: string;
  staffId: string;
  staffName: string;
  amountUgx: number;
  method?: BalanceReturnMethod;
  reference?: string;
  status: BalanceReturnStatus;
  createdAt: string;
  confirmedAt?: string;
  comment?: string;
};

export type ReimbursementClaim = {
  id: string;
  staffId: string;
  staffName: string;
  staffRole: "CCEO" | "ProgramLead" | "ImpactAssessment" | "ProgramAccountant" | "SpecialProjectsCoordinator" | "Admin";

  // Optional links back to a plan / activity / request.
  activityId?: string;
  activityTitle?: string;
  weeklyPlanId?: string;
  fundRequestId?: string;

  // When the claim was auto-generated from a reconciliation overspend,
  // these point back to the originating record + flag the auto path.
  fundReconciliationId?: string;
  autoCreated?: boolean;
  thresholdFlag?: OverspendThresholdFlag;

  amountSpentUgx: number;
  amountPreviouslyDisbursedUgx: number;
  amountToReimburseUgx: number;

  reasonPersonalFundsUsed: string;
  overspendReason?: OverspendReason;
  netsuiteExpenseId: string;
  evidenceLinks?: string[];

  approvalRoute: ReimbursementApprovalRoute;
  status: ReimbursementStatus;

  submittedAt: string;
  approvedBy?: string;
  approvedAt?: string;
  reimbursedBy?: string;
  reimbursedAt?: string;
  transactionReference?: string;
  returnedReason?: string;
};

// ────────── Country Monthly Budget (RVP-approved envelope) ────────────
//
// RVP approves the COUNTRY MONTHLY BUDGET — not individual weekly
// requests. Once RVP approves this envelope, weekly fund-request
// auto-generation becomes active for the month.

export type CountryMonthlyBudgetStatus =
  | "DRAFT"
  | "PENDING_RVP"
  | "RETURNED"
  | "APPROVED"
  | "APPROVED_WITH_CONDITIONS"
  | "CLOSED";

export type CountryBudgetCategory =
  | "FieldWork"
  | "AdminOps"
  | "SpecialProjects"
  | "Contingency"
  | "Training"
  | "PartnerWork";

export type CountryMonthlyBudgetLine = {
  category: CountryBudgetCategory;
  label: string;
  amount: Money;
  note?: string;
};

export type CountryMonthlyBudget = {
  id: string;
  countryId: string;
  countryName: string;
  flag: string;
  monthLabel: string;          // "May 2026"
  monthIso: string;
  fyLabel: string;
  quarter: "Q1" | "Q2" | "Q3" | "Q4";
  status: CountryMonthlyBudgetStatus;
  total: Money;
  lines: CountryMonthlyBudgetLine[];
  submittedByCdId: string;
  submittedByCdName: string;
  submittedAt?: string;
  approvedByRvpId?: string;
  approvedByRvpName?: string;
  approvedAt?: string;
  conditions?: string;
  notes?: string;
};

// ────────── Country fund snapshot ─────────────────────────────────────

export type CountryFundSnapshot = {
  countryId: string;
  monthLabel: string;
  totalReceived: Money;
  totalDisbursed: Money;
  totalAccountedFor: Money;
  totalOutstanding: Money;
  totalReturned: Money;
  weekStartIso: string;
  pendingDisbursements: number;
  pendingApprovals: number;
  pendingAccountabilities: number;
  blockedRequests: number;
};
