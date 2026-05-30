// Monthly Plan & Funding Governance Engine.
//
// Hard contracts (enforced both client- and server-side):
//   • Monthly budgets are GENERATED from approved planned activities × active
//     Country Cost Settings. Never manually guessed.
//   • Flow: Staff → Program Lead → Country Director → RVP → Final Approved.
//   • Program Leads NEVER final-approve funds.
//   • `requestedBudget` is IMMUTABLE. Amendments live in append-only
//     BudgetAmendment records and surface through `amendedBudget`.
//   • `finalApprovedBudget` is set ONLY after RVP final approval.
//   • Status transitions are validated against `validTransitions` — illegal
//     jumps (Draft → Approved by RVP, etc.) are rejected.
//   • `assertCanApproveSubmission()` re-checks role + status server-side, so
//     bypassing the UI cannot trigger an unauthorised approval.
//   • Available funds carry a source (Country Allocation / Donor Release /
//     Carry Forward / etc.), restriction, who confirmed, and confirmation
//     date. Budgets are NEVER compared against an unexplained number.
//   • Funding Gap detection produces the standardised prioritisation copy.
//   • Priority labels carry factor lists ("Why this priority?") so leaders
//     can see what's driving the recommendation.
//   • Decision Impact Preview surfaces protected / deferred / risk lists
//     before any amendment is committed.
//   • Approval conditions become visible follow-up tasks.
//   • Program Accountant review notes are visible to CD + RVP.
//   • Final Approved plans produce a dedicated artifact + disbursement
//     tracking (approved / disbursed / spent / returned / unused / verified).

import "server-only";
import { activeFinancialYear } from "@/lib/fy-engine";
import { activeCostFor, formatUgxBig, type CostItem } from "@/lib/cost-settings-mock";

// ────────── Approval status ──────────

export const APPROVAL_STATUSES = [
  "Draft",
  "Submitted to Program Lead",
  "Returned by Program Lead",
  "Approved by Program Lead",
  "Submitted to Country Director",
  "Returned by Country Director",
  "Amended by Country Director",
  "Approved by Country Director",
  "Submitted to RVP",
  "Returned by RVP",
  "Amended by RVP",
  "Approved by RVP",
  "Final Approved",
  "Active Funding Plan",
  "Disbursed",
  "Closed",
] as const;

export type ApprovalStatus = (typeof APPROVAL_STATUSES)[number];

// ────────── Valid status transitions ──────────
//
// The engine refuses to move a submission between statuses unless the source
// status explicitly lists the target. This blocks shortcuts like Draft →
// Approved by RVP, Submitted to Program Lead → Final Approved, etc.

export const validTransitions: Record<ApprovalStatus, ApprovalStatus[]> = {
  "Draft":                         ["Submitted to Program Lead"],
  "Submitted to Program Lead":     ["Returned by Program Lead", "Approved by Program Lead"],
  "Returned by Program Lead":      ["Draft", "Submitted to Program Lead"],
  "Approved by Program Lead":      ["Submitted to Country Director"],
  "Submitted to Country Director": ["Returned by Country Director", "Amended by Country Director", "Approved by Country Director"],
  "Amended by Country Director":   ["Approved by Country Director", "Returned by Country Director"],
  "Returned by Country Director":  ["Submitted to Program Lead", "Submitted to Country Director"],
  "Approved by Country Director":  ["Submitted to RVP"],
  "Submitted to RVP":              ["Returned by RVP", "Amended by RVP", "Approved by RVP"],
  "Amended by RVP":                ["Approved by RVP", "Returned by RVP"],
  "Returned by RVP":               ["Submitted to Country Director"],
  "Approved by RVP":               ["Final Approved"],
  "Final Approved":                ["Active Funding Plan"],
  "Active Funding Plan":           ["Disbursed", "Closed"],
  "Disbursed":                     ["Closed"],
  "Closed":                        [],
};

export function canTransition(from: ApprovalStatus, to: ApprovalStatus): boolean {
  return validTransitions[from].includes(to);
}

// Class of errors thrown by `assertCanApproveSubmission`. Production code
// returns these as 403 / 409 responses.
export class ForbiddenError    extends Error { constructor(m: string) { super(m); this.name = "ForbiddenError"; } }
export class InvalidStateError extends Error { constructor(m: string) { super(m); this.name = "InvalidStateError"; } }

export type ApprovalAction =
  | "PL_APPROVE"
  | "PL_RETURN"
  | "CD_APPROVE"
  | "CD_AMEND"
  | "CD_RETURN"
  | "CD_SUBMIT_TO_RVP"
  | "RVP_FINAL_APPROVE"
  | "RVP_AMEND"
  | "RVP_RETURN"
  | "ACCOUNTANT_NOTE";

export type ActorContext = { role: string; staffId: string; name: string };

// assertCanApproveSubmission — backend role + status check. Always re-run on
// the server even if the UI hid the action. Spec contract: bypassing the UI
// must not be possible.
export function assertCanApproveSubmission(
  user: ActorContext,
  submission: MonthlyPlanSubmission,
  action: ApprovalAction,
): void {
  // Program Lead actions
  if (action === "PL_APPROVE" || action === "PL_RETURN") {
    if (user.role !== "CountryProgramLead" && user.role !== "Admin") {
      throw new ForbiddenError("Only Program Leads (or Admin) can act at the Program Lead stage.");
    }
    if (submission.status !== "Submitted to Program Lead") {
      throw new InvalidStateError(`This submission is not awaiting Program Lead review (current status: ${submission.status}).`);
    }
    return;
  }
  // Country Director actions
  if (action === "CD_APPROVE" || action === "CD_AMEND" || action === "CD_RETURN" || action === "CD_SUBMIT_TO_RVP") {
    if (!["CountryDirector", "Admin"].includes(user.role)) {
      throw new ForbiddenError("Only Country Director or Admin can act at the Country Director stage.");
    }
    if (submission.status !== "Submitted to Country Director" && submission.status !== "Amended by Country Director") {
      throw new InvalidStateError(`This submission is not awaiting Country Director review (current status: ${submission.status}).`);
    }
    return;
  }
  // RVP actions
  if (action === "RVP_FINAL_APPROVE" || action === "RVP_AMEND" || action === "RVP_RETURN") {
    if (user.role !== "RVP" && user.role !== "Admin") {
      throw new ForbiddenError("Only RVP (or Admin) can final-approve monthly funds.");
    }
    if (submission.status !== "Submitted to RVP" && submission.status !== "Amended by RVP") {
      throw new InvalidStateError(`This submission is not awaiting RVP review (current status: ${submission.status}).`);
    }
    return;
  }
  // Accountant review
  if (action === "ACCOUNTANT_NOTE") {
    if (!["ProgramAccountant", "Admin"].includes(user.role)) {
      throw new ForbiddenError("Only Program Accountant or Admin can attach a finance review note.");
    }
    return;
  }
  throw new ForbiddenError("Unknown approval action.");
}

// ────────── Activity types ──────────

export type MonthlyActivityType =
  | "School Improvement Training"
  | "SSA"
  | "SSA Verification"
  | "School Visit"
  | "Core School Visit"
  | "Core School Training"
  | "Cluster Training"
  | "Partner Visit"
  | "Partner Training"
  | "Exam Result Collection"
  | "Enrollment Update"
  | "MSC Story"
  | "Special Project";

// Maps activity type → cost item it pulls its unit cost from.
const COST_ITEM_FOR: Record<MonthlyActivityType, CostItem> = {
  "School Improvement Training": "Cluster training cost",
  "SSA":                         "SSA support cost",
  "SSA Verification":            "SSA verification cost",
  "School Visit":                "Staff school visit cost",
  "Core School Visit":           "Staff school visit cost",
  "Core School Training":        "In-School coaching cost",
  "Cluster Training":            "Cluster training cost",
  "Partner Visit":               "Partner school visit cost",
  "Partner Training":            "Partner training fee",
  "Exam Result Collection":      "Exam result collection cost",
  "Enrollment Update":           "Enrollment update cost",
  "MSC Story":                   "MSC story collection cost",
  "Special Project":             "Special project session cost",
};

// ────────── Priority ──────────

export type Priority = "Critical" | "High" | "Medium" | "Low" | "Deferrable";

export type PriorityFactorKind =
  | "ssa-overdue"
  | "ssa-verification-pending"
  | "core-behind-package"
  | "training-followup-overdue"
  | "high-risk-school"
  | "low-ssa-score"
  | "special-project-deadline"
  | "previous-month-carryover"
  | "funding-deadline"
  | "partner-dependency"
  | "route-efficiency"
  | "target-risk";

export type PriorityFactor = { kind: PriorityFactorKind; detail: string };

// ────────── Available Funds (with source) ──────────

export type AvailableFundsSource =
  | "Country Allocation"
  | "Donor Release"
  | "Carry Forward"
  | "Restricted Grant"
  | "Emergency Allocation"
  | "Other";

export type AvailableFundsRecord = {
  id:              string;
  country:         string;
  financialYearId: string;
  month:           string;
  amountAvailable: number;
  currency:        string;
  source:          AvailableFundsSource;
  restriction?:    string;
  confirmedBy:     string;
  confirmedAt:     string;
  status:          "Draft" | "Confirmed" | "Archived";
  notes?:          string;
};

const FY = activeFinancialYear();

export const availableFundsRecords: AvailableFundsRecord[] = [
  { id: "af-pl-001", country: "Uganda", financialYearId: FY.id, month: "2026-05", amountAvailable: 7_840_000, currency: "UGX", source: "Country Allocation", restriction: "Program delivery activities only", confirmedBy: "Moses Tindi", confirmedAt: "May 13, 2026 · 09:10", status: "Confirmed", notes: "Q3 Uganda allocation for North PL team." },
  { id: "af-pl-002", country: "Uganda", financialYearId: FY.id, month: "2026-05", amountAvailable: 9_460_000, currency: "UGX", source: "Country Allocation", restriction: "Program delivery activities only", confirmedBy: "Moses Tindi", confirmedAt: "May 13, 2026 · 09:12", status: "Confirmed", notes: "Q3 Uganda allocation for Central PL team." },
  { id: "af-pl-003", country: "Uganda", financialYearId: FY.id, month: "2026-05", amountAvailable: 6_520_000, currency: "UGX", source: "Donor Release",       restriction: "North region only",               confirmedBy: "Moses Tindi", confirmedAt: "May 13, 2026 · 09:14", status: "Confirmed", notes: "Donor-restricted release for North operations." },
  { id: "af-pl-004", country: "Uganda", financialYearId: FY.id, month: "2026-05", amountAvailable: 7_180_000, currency: "UGX", source: "Country Allocation", restriction: undefined,                          confirmedBy: "Moses Tindi", confirmedAt: "May 13, 2026 · 09:16", status: "Confirmed" },
  { id: "af-pl-005", country: "Uganda", financialYearId: FY.id, month: "2026-05", amountAvailable: 5_540_000, currency: "UGX", source: "Carry Forward",     restriction: "Special projects only",             confirmedBy: "Moses Tindi", confirmedAt: "May 13, 2026 · 09:18", status: "Confirmed", notes: "Q2 carry-forward for EdTech 2026." },
  { id: "af-pl-006", country: "Uganda", financialYearId: FY.id, month: "2026-05", amountAvailable: 6_020_000, currency: "UGX", source: "Country Allocation", restriction: undefined,                          confirmedBy: "Moses Tindi", confirmedAt: "May 13, 2026 · 09:20", status: "Confirmed" },
];

export function getAvailableFunds(id: string): AvailableFundsRecord | undefined {
  return availableFundsRecords.find((r) => r.id === id);
}

// ────────── Models ──────────

export type PlannedActivity = {
  id:           string;
  type:         MonthlyActivityType;
  week:         1 | 2 | 3 | 4;
  schoolId?:    string;
  schoolName?:  string;
  cluster?:     string;
  district?:    string;
  quantity:     number;       // # of visits / trainings / participants
  unitCost:     number;       // resolved from active cost settings
  totalCost:    number;       // quantity × unitCost
  priority:     Priority;
  rationale:    string;       // why this activity is recommended
  partnerLed?:  boolean;
  ssaUrgent?:   boolean;
  corePackage?: boolean;
};

export type BudgetAmendment = {
  id:                  string;
  submissionId:        string;
  approvalStage:       "Country Director Review" | "RVP Review";
  originalAmount:      number;
  amendedAmount:       number;
  difference:          number;
  reason:              string;
  affectedActivities:  string[];
  affectedSchools?:    string[];
  affectedDistricts?:  string[];
  amendedBy:           string;
  amendedByRole:       "CountryDirector" | "Admin" | "RVP";
  amendedAt:           string;
  comment?:            string;
};

export type ApprovalCondition = {
  id:           string;
  text:         string;
  addedBy:      string;
  addedByRole:  "CountryDirector" | "RVP";
  addedAt:      string;
  status:       "Open" | "Met" | "Waived";
  assignedTo?:  string;
};

export type ProgramAccountantReviewNote = {
  id:                       string;
  submissionId:             string;
  reviewedBy:               string;
  reviewedAt:               string;
  availableFundsConfirmed:  boolean;
  costSettingsConfirmed:    boolean;
  budgetErrors:             string[];
  notes:                    string;
};

export type DisbursementRecord = {
  id:                      string;
  submissionId:            string;
  approvedAmount:          number;
  disbursedAmount:         number;
  spentAmount:             number;
  returnedAmount:          number;
  unusedAmount:            number;
  verifiedCompletedValue:  number;
  variance:                number;
  lastUpdatedBy:           string;
  lastUpdatedAt:           string;
};

// Audit entry — captures previous status, new status, actor, and reason on
// every transition. The aggregated audit page uses this directly.
export type AuditEntry = {
  at:                  string;
  actor:               string;
  role:                "Staff" | "Program Lead" | "Country Director" | "RVP" | "Program Accountant" | "Admin";
  action:              "Submitted" | "Approved" | "Returned" | "Amended" | "Submitted to CD" | "Submitted to RVP" | "Activated" | "Disbursed" | "Closed" | "Accountant Note";
  previousStatus:      ApprovalStatus | null;
  newStatus:           ApprovalStatus | null;
  originalAmount?:     number;
  amendedAmount?:      number;
  reason?:             string;
  comment?:            string;
  affectedActivities?: string[];
};

export type MonthlyPlanSubmission = {
  id:                       string;
  financialYearId:          string;
  monthLabel:               string;       // "May 2026"
  monthIso:                 string;       // "2026-05"

  programLeadId:            string;
  programLeadName:          string;
  region:                   string;

  staffId:                  string;       // submitting staff
  staffName:                string;

  status:                   ApprovalStatus;
  priority:                 Priority;     // rollup priority of the submission
  priorityFactors:          PriorityFactor[];

  activities:               PlannedActivity[];

  // ─── Budget fields ──────────────────────────────────
  //  • requestedBudget is IMMUTABLE — set once on submission.
  //  • amendedBudget reflects the latest amended amount (last amendment).
  //  • finalApprovedBudget is set only at RVP Final Approval.
  // ────────────────────────────────────────────────────
  requestedBudget:          number;
  amendedBudget?:           number;
  finalApprovedBudget?:     number;

  availableFundsRecordId:   string;
  availableAllocation:      number;       // mirrored from AvailableFundsRecord.amountAvailable
  fundingGap:               number;       // requestedBudget - availableAllocation (snapshot at submission)

  amendments:               BudgetAmendment[];
  approvalConditions:       ApprovalCondition[];
  accountantNote?:          ProgramAccountantReviewNote;
  disbursement?:            DisbursementRecord;
  audit:                    AuditEntry[];
  lastAction:               string;       // "Approved by RVP" etc. — humanised
};

// ────────── Helpers ──────────

function activity({
  id, type, week, schoolName, cluster, district, quantity, priority, rationale,
  partnerLed, ssaUrgent, corePackage,
}: {
  id: string; type: MonthlyActivityType; week: 1 | 2 | 3 | 4;
  schoolName?: string; cluster?: string; district?: string;
  quantity: number; priority: Priority; rationale: string;
  partnerLed?: boolean; ssaUrgent?: boolean; corePackage?: boolean;
}): PlannedActivity {
  const unitCost  = activeCostFor(COST_ITEM_FOR[type]);
  const totalCost = unitCost * quantity;
  return { id, type, week, schoolName, cluster, district, quantity, unitCost, totalCost, priority, rationale, partnerLed, ssaUrgent, corePackage };
}

function sumBudget(activities: PlannedActivity[]): number {
  return activities.reduce((a, x) => a + x.totalCost, 0);
}

// calculatePriorityScore — derives the headline priority. Spec drivers:
// SSA-urgent + Core Package + High Risk.
export function calculatePriorityScore(a: PlannedActivity[]): Priority {
  if (a.some((x) => x.ssaUrgent))   return "Critical";
  if (a.some((x) => x.corePackage)) return "High";
  if (a.some((x) => x.priority === "High" || x.priority === "Critical")) return "High";
  if (a.length === 0) return "Deferrable";
  return "Medium";
}

// priorityFactorsFor — surfaces the "Why this priority?" data.
export function priorityFactorsFor(s: MonthlyPlanSubmission): PriorityFactor[] {
  return s.priorityFactors;
}

// ────────── Decision Impact Preview ──────────

export type DecisionImpactPreview = {
  reductionAmount:  number;
  protectedItems:   { label: string; count: number }[];
  deferredItems:    { label: string; count: number; reason: string }[];
  risks:            string[];
};

// generateDecisionImpactPreview — produces the protected/deferred/risk lists
// shown to CD/RVP before they commit an amendment.
export function generateDecisionImpactPreview(
  s: MonthlyPlanSubmission,
  newAmount: number,
): DecisionImpactPreview {
  const original = s.amendedBudget ?? s.requestedBudget;
  const reductionAmount = Math.max(0, original - newAmount);

  const protectedAct = s.activities.filter((a) => a.priority === "Critical" || a.ssaUrgent || a.corePackage);
  const deferred     = s.activities.filter((a) => a.priority === "Low" || a.priority === "Deferrable");

  const protectedItems = [
    { label: "SSA verification activities", count: protectedAct.filter((a) => a.type === "SSA Verification" || a.ssaUrgent).length },
    { label: "Core School 4+4 activities",  count: protectedAct.filter((a) => a.corePackage).length },
    { label: "Training follow-ups",         count: protectedAct.filter((a) => a.type === "Core School Training" || a.type === "Cluster Training").length },
    { label: "High-risk school visits",     count: protectedAct.filter((a) => a.priority === "Critical" && a.type === "School Visit").length },
  ].filter((p) => p.count > 0);

  const deferredItems = [
    { label: "Low-risk monitoring visits",   count: deferred.filter((a) => a.type === "School Visit").length,        reason: "Defer to next month" },
    { label: "Non-urgent partner activities",count: deferred.filter((a) => a.partnerLed).length,                       reason: "Shift to next cycle" },
    { label: "Cluster activities",           count: deferred.filter((a) => a.type === "Cluster Training").length,     reason: "Move to next month" },
  ].filter((d) => d.count > 0);

  const reductionPct = original === 0 ? 0 : Math.round((reductionAmount / original) * 100);
  const risks: string[] = [];
  if (reductionPct >= 30) risks.push(`Target achievement in ${s.region} may drop ${Math.round(reductionPct / 4)}–${Math.round(reductionPct / 3)} points this month.`);
  if (reductionPct >= 20) risks.push(`Two PL teams may need catch-up planning next month.`);
  if (deferredItems.some((d) => d.count >= 5)) risks.push(`Carry-forward backlog will grow into next month.`);
  if (risks.length === 0) risks.push("Amendment is within tolerance; no leadership escalation required.");

  return { reductionAmount, protectedItems, deferredItems, risks };
}

// ────────── Submission seeds ──────────

type SeedActivity = Parameters<typeof activity>[0];

const SUBMISSION_SEEDS: {
  id: string; status: ApprovalStatus; programLeadId: string; programLeadName: string; region: string;
  staffId: string; staffName: string;
  activities: SeedActivity[];
  amendments: Omit<BudgetAmendment, "submissionId" | "difference">[];
  approvalConditions: Omit<ApprovalCondition, "id">[];
  accountantNote?: Omit<ProgramAccountantReviewNote, "id" | "submissionId">;
  disbursement?: Omit<DisbursementRecord, "id" | "submissionId">;
  priorityFactors: PriorityFactor[];
  finalApprovedBudget?: number;
}[] = [
  {
    id: "mp-001",
    status: "Final Approved",
    programLeadId: "PL-001", programLeadName: "Daniel Mwangi", region: "North",
    staffId: "STF-DM-014", staffName: "Daniel Mwangi (team submission)",
    activities: [
      { id: "mp-001-a", type: "School Improvement Training", week: 1, cluster: "Kitgum North", district: "Kitgum", quantity: 1, priority: "Critical", rationale: "Annual gateway — required before SSA for cluster" },
      { id: "mp-001-b", type: "Cluster Training",            week: 2, cluster: "Pader Central", district: "Pader", quantity: 1, priority: "High",     rationale: "Cluster requested follow-up training" },
      { id: "mp-001-c", type: "SSA",                         week: 2, schoolName: "Sunrise Primary", district: "Kitgum", quantity: 1, priority: "Critical", rationale: "SSA Needed — last assessment 2025-03-12", ssaUrgent: true },
      { id: "mp-001-d", type: "Core School Visit",           week: 3, schoolName: "Greenfield Sec", district: "Kitgum", quantity: 1, priority: "High", rationale: "Core 4+4 package — visit 2 of 4", corePackage: true },
      { id: "mp-001-e", type: "School Visit",                week: 4, schoolName: "Riverside",      district: "Cluster", quantity: 4, priority: "Medium", rationale: "Recommended Client follow-up" },
      { id: "mp-001-f", type: "Exam Result Collection",      week: 4, schoolName: "Hilltop Basic",  district: "Cluster", quantity: 1, priority: "Low", rationale: "End-of-term collection" },
    ],
    amendments: [
      { id: "am-1", approvalStage: "Country Director Review", originalAmount: 8_950_000, amendedAmount: 7_800_000, reason: "Available funds lower than requested. Deferred 1 Cluster Training to June.", affectedActivities: ["mp-001-b"], affectedDistricts: ["Pader"], amendedBy: "Sarah Okello", amendedByRole: "CountryDirector", amendedAt: "Apr 22, 2026 · 14:10", comment: "Re-include in June plan." },
    ],
    approvalConditions: [
      { text: "Cluster Training in Pader must be re-submitted in June with confirmed school availability.", addedBy: "Sarah Okello", addedByRole: "CountryDirector", addedAt: "Apr 22, 2026 · 14:10", status: "Open", assignedTo: "PL-001" },
    ],
    accountantNote: {
      reviewedBy: "Moses Tindi", reviewedAt: "Apr 21, 2026 · 10:30",
      availableFundsConfirmed: true, costSettingsConfirmed: true,
      budgetErrors: [],
      notes: "Available funds confirmed. All cost lines reference active settings. Approved for CD review.",
    },
    disbursement: {
      approvedAmount: 7_800_000, disbursedAmount: 7_488_000, spentAmount: 6_240_000,
      returnedAmount: 0, unusedAmount: 1_248_000, verifiedCompletedValue: 5_980_000,
      variance: 1_560_000, lastUpdatedBy: "Moses Tindi", lastUpdatedAt: "May 06, 2026 · 16:00",
    },
    priorityFactors: [
      { kind: "ssa-overdue",                 detail: "1 school (Sunrise Primary) has not been assessed since Mar 2025." },
      { kind: "core-behind-package",         detail: "1 Core School (Greenfield Sec) is on visit 2 of 4 for FY 2025/26." },
      { kind: "training-followup-overdue",   detail: "Pader Central cluster training is 45 days overdue." },
    ],
    finalApprovedBudget: 7_800_000,
  },
  {
    id: "mp-002",
    status: "Submitted to RVP",
    programLeadId: "PL-002", programLeadName: "Aisha Dar", region: "Central",
    staffId: "STF-AD-021", staffName: "Aisha Dar (team submission)",
    activities: [
      { id: "mp-002-a", type: "SSA Verification",  week: 1, schoolName: "Kampala Central", district: "Kampala", quantity: 8, priority: "Critical", rationale: "10% Client verification quota — Q3 cycle close", ssaUrgent: true },
      { id: "mp-002-b", type: "Core School Training", week: 2, schoolName: "Hope Academy", district: "Wakiso", quantity: 1, priority: "High", rationale: "Core package — training 2 of 4", corePackage: true },
      { id: "mp-002-c", type: "Cluster Training",   week: 3, cluster: "Wakiso West", district: "Wakiso", quantity: 1, priority: "High", rationale: "Cluster requested SSA debrief training" },
      { id: "mp-002-d", type: "MSC Story",          week: 4, schoolName: "Living Word",   district: "Kampala", quantity: 2, priority: "Medium", rationale: "Q3 story quota" },
      { id: "mp-002-e", type: "Enrollment Update",  week: 4, schoolName: "Grace Community", district: "Kampala", quantity: 1, priority: "Medium", rationale: "Term 2 enrolment update" },
    ],
    amendments: [],
    approvalConditions: [
      { text: "Partner-led training must use a Certified partner — confirm before disbursement.", addedBy: "Sarah Okello", addedByRole: "CountryDirector", addedAt: "Apr 23, 2026 · 11:00", status: "Open", assignedTo: "PL-002" },
    ],
    accountantNote: {
      reviewedBy: "Moses Tindi", reviewedAt: "Apr 22, 2026 · 08:00",
      availableFundsConfirmed: true, costSettingsConfirmed: true,
      budgetErrors: [],
      notes: "Available funds confirmed. Hope Academy 4+4 visit cost aligns with active rate.",
    },
    priorityFactors: [
      { kind: "ssa-verification-pending", detail: "8 Client verifications are still pending to meet the 10% quota." },
      { kind: "core-behind-package",      detail: "Hope Academy is on training 2 of 4 — needs Q2 completion." },
      { kind: "target-risk",              detail: "Central region target achievement is 86% — falls below 80% without this plan." },
    ],
  },
  {
    id: "mp-003",
    status: "Approved by Country Director",
    programLeadId: "PL-003", programLeadName: "Brian Okello", region: "North",
    staffId: "STF-BO-005", staffName: "Brian Okello (team submission)",
    activities: [
      { id: "mp-003-a", type: "SSA",                week: 1, schoolName: "Lamwo Bright",  district: "Lamwo", quantity: 1, priority: "Critical", rationale: "SSA Overdue — 2024-06-04", ssaUrgent: true },
      { id: "mp-003-b", type: "Core School Visit",  week: 2, schoolName: "Pader West",    district: "Pader", quantity: 1, priority: "High", rationale: "Core package — visit 2 of 4", corePackage: true },
      { id: "mp-003-c", type: "Partner Visit",      week: 3, schoolName: "Olive Children's", district: "Lamwo", quantity: 2, priority: "Medium", rationale: "Partner-led follow-up", partnerLed: true },
      { id: "mp-003-d", type: "School Visit",       week: 4, schoolName: "Agago Junior",  district: "Agago", quantity: 3, priority: "Medium", rationale: "Recommended catch-up visit" },
    ],
    amendments: [],
    approvalConditions: [],
    accountantNote: {
      reviewedBy: "Moses Tindi", reviewedAt: "Apr 21, 2026 · 09:45",
      availableFundsConfirmed: true, costSettingsConfirmed: true,
      budgetErrors: [],
      notes: "Available funds confirmed from donor release. Restricted to North operations.",
    },
    priorityFactors: [
      { kind: "ssa-overdue",         detail: "Lamwo Bright last SSA was June 2024 — 22 months overdue." },
      { kind: "core-behind-package", detail: "Pader West is on visit 2 of 4 — Q2 catch-up needed." },
      { kind: "partner-dependency",  detail: "Olive Children's visit depends on a Certified partner." },
    ],
  },
  {
    id: "mp-004",
    status: "Approved by Program Lead",
    programLeadId: "PL-004", programLeadName: "Esther Wanjiru", region: "East",
    staffId: "STF-EW-017", staffName: "Esther Wanjiru (team submission)",
    activities: [
      { id: "mp-004-a", type: "School Improvement Training", week: 1, cluster: "Mbarara East", district: "Mbarara", quantity: 1, priority: "Critical", rationale: "Q3 cluster catch-up — required before SSA" },
      { id: "mp-004-b", type: "Core School Training", week: 2, schoolName: "Victory Academy", district: "Mukono", quantity: 1, priority: "High", rationale: "Core package — training 3 of 4", corePackage: true },
      { id: "mp-004-c", type: "School Visit",        week: 3, schoolName: "Light of Hope",   district: "Mukono", quantity: 5, priority: "Medium", rationale: "Recommended Client follow-up" },
      { id: "mp-004-d", type: "MSC Story",           week: 4, schoolName: "Mukono Bright",   district: "Mukono", quantity: 2, priority: "Low", rationale: "Q3 story quota" },
    ],
    amendments: [],
    approvalConditions: [],
    priorityFactors: [
      { kind: "core-behind-package",         detail: "Victory Academy is on training 3 of 4." },
      { kind: "training-followup-overdue",   detail: "Mbarara East cluster training overdue by 60 days." },
    ],
  },
  {
    id: "mp-005",
    status: "Returned by Country Director",
    programLeadId: "PL-005", programLeadName: "Fatima Noor", region: "Central",
    staffId: "STF-FN-003", staffName: "Fatima Noor (team submission)",
    activities: [
      { id: "mp-005-a", type: "Special Project",  week: 1, district: "Kampala", quantity: 6, priority: "High", rationale: "EdTech 2026 — Q3 sessions" },
      { id: "mp-005-b", type: "Partner Training", week: 2, district: "Kampala", quantity: 2, priority: "Medium", rationale: "Partner-led teacher training", partnerLed: true },
      { id: "mp-005-c", type: "School Visit",     week: 3, schoolName: "Wakiso Bright",  district: "Wakiso", quantity: 6, priority: "Low", rationale: "Routine follow-up" },
    ],
    amendments: [
      { id: "am-5", approvalStage: "Country Director Review", originalAmount: 6_800_000, amendedAmount: 6_800_000, reason: "Returned to Program Lead — partner certification not yet refreshed; defer partner training.", affectedActivities: ["mp-005-b"], affectedDistricts: ["Kampala"], amendedBy: "Sarah Okello", amendedByRole: "CountryDirector", amendedAt: "Apr 30, 2026 · 11:00", comment: "Re-submit once Partner Register batch is approved." },
    ],
    approvalConditions: [],
    accountantNote: {
      reviewedBy: "Moses Tindi", reviewedAt: "Apr 29, 2026 · 15:00",
      availableFundsConfirmed: true, costSettingsConfirmed: false,
      budgetErrors: ["Partner Training rate uses Apr 2026 unit cost; May 2026 rate is +5%."],
      notes: "Available funds confirmed but partner training cost rate is outdated. Recommend correction before re-submission.",
    },
    priorityFactors: [
      { kind: "special-project-deadline", detail: "EdTech 2026 has 12 sessions left this FY — 6 planned for May." },
      { kind: "partner-dependency",       detail: "Partner training depends on certification refresh." },
    ],
  },
  {
    id: "mp-006",
    status: "Submitted to Program Lead",
    programLeadId: "PL-006", programLeadName: "Imran Bashir", region: "West",
    staffId: "STF-IB-009", staffName: "Imran Bashir (team submission)",
    activities: [
      { id: "mp-006-a", type: "SSA",                week: 1, schoolName: "Hoima Hill",     district: "Hoima",   quantity: 2, priority: "High", rationale: "SSA Needed — 2024-08-14 baseline" },
      { id: "mp-006-b", type: "Core School Visit",  week: 2, schoolName: "Mbarara Centre", district: "Mbarara", quantity: 1, priority: "High", rationale: "Core package — visit 3 of 4", corePackage: true },
      { id: "mp-006-c", type: "Cluster Training",   week: 3, cluster: "Mbarara Cluster",   district: "Mbarara", quantity: 1, priority: "Medium", rationale: "Cluster requested" },
      { id: "mp-006-d", type: "Enrollment Update",  week: 4, schoolName: "Hoima Bright",   district: "Hoima",   quantity: 1, priority: "Low", rationale: "Term 2 enrolment update" },
    ],
    amendments: [],
    approvalConditions: [],
    priorityFactors: [
      { kind: "core-behind-package",    detail: "Mbarara Centre is on visit 3 of 4." },
      { kind: "previous-month-carryover", detail: "Hoima Hill SSA was deferred from April." },
    ],
  },
];

// Build audit trail from status by reverse-engineering the workflow path.
function buildAudit(
  status: ApprovalStatus,
  plName: string,
  amendments: Omit<BudgetAmendment, "submissionId" | "difference">[],
  approvalConditions: Omit<ApprovalCondition, "id">[],
  accountantNote?: Omit<ProgramAccountantReviewNote, "id" | "submissionId">,
): AuditEntry[] {
  const out: AuditEntry[] = [];
  const pastIdx = APPROVAL_STATUSES.indexOf(status);
  const idx = (st: ApprovalStatus) => APPROVAL_STATUSES.indexOf(st);

  out.push({ at: "Apr 15, 2026 · 09:00", actor: plName, role: "Staff", action: "Submitted",
    previousStatus: "Draft", newStatus: "Submitted to Program Lead",
    comment: "Initial monthly plan submitted." });

  if (pastIdx >= idx("Approved by Program Lead")) {
    out.push({ at: "Apr 18, 2026 · 14:30", actor: plName, role: "Program Lead", action: "Approved",
      previousStatus: "Submitted to Program Lead", newStatus: "Approved by Program Lead",
      comment: "Plan + budget reviewed. Workload realistic." });
  }
  if (pastIdx >= idx("Submitted to Country Director")) {
    out.push({ at: "Apr 19, 2026 · 09:00", actor: plName, role: "Program Lead", action: "Submitted to CD",
      previousStatus: "Approved by Program Lead", newStatus: "Submitted to Country Director" });
  }
  if (accountantNote) {
    out.push({ at: accountantNote.reviewedAt, actor: accountantNote.reviewedBy, role: "Program Accountant", action: "Accountant Note",
      previousStatus: null, newStatus: null,
      comment: accountantNote.notes });
  }
  for (const a of amendments) {
    out.push({ at: a.amendedAt, actor: a.amendedBy, role: a.amendedByRole === "RVP" ? "RVP" : "Country Director", action: "Amended",
      previousStatus: "Submitted to Country Director", newStatus: a.approvalStage === "RVP Review" ? "Amended by RVP" : "Amended by Country Director",
      originalAmount: a.originalAmount, amendedAmount: a.amendedAmount,
      reason: a.reason, comment: a.comment, affectedActivities: a.affectedActivities });
  }
  if (status === "Returned by Country Director") {
    out.push({ at: "Apr 30, 2026 · 11:00", actor: "Sarah Okello", role: "Country Director", action: "Returned",
      previousStatus: "Submitted to Country Director", newStatus: "Returned by Country Director",
      comment: "Partner certification not refreshed. Resubmit." });
  }
  if (pastIdx >= idx("Approved by Country Director")) {
    out.push({ at: "Apr 22, 2026 · 14:10", actor: "Sarah Okello", role: "Country Director", action: "Approved",
      previousStatus: amendments.length > 0 ? "Amended by Country Director" : "Submitted to Country Director",
      newStatus: "Approved by Country Director",
      comment: amendments.length > 0 ? "Approved with amendments. Funds confirmed available." : "Approved. Funds confirmed available." });
  }
  if (pastIdx >= idx("Submitted to RVP")) {
    out.push({ at: "Apr 23, 2026 · 09:00", actor: "Sarah Okello", role: "Country Director", action: "Submitted to RVP",
      previousStatus: "Approved by Country Director", newStatus: "Submitted to RVP" });
  }
  if (pastIdx >= idx("Approved by RVP")) {
    out.push({ at: "Apr 25, 2026 · 10:00", actor: "Esther Wanjiru", role: "RVP", action: "Approved",
      previousStatus: "Submitted to RVP", newStatus: "Approved by RVP",
      comment: "Final approval granted." });
  }
  if (pastIdx >= idx("Final Approved")) {
    out.push({ at: "Apr 25, 2026 · 10:01", actor: "System", role: "Admin", action: "Activated",
      previousStatus: "Approved by RVP", newStatus: "Final Approved" });
  }
  if (pastIdx >= idx("Active Funding Plan")) {
    out.push({ at: "Apr 26, 2026 · 09:00", actor: "Moses Tindi", role: "Program Accountant", action: "Activated",
      previousStatus: "Final Approved", newStatus: "Active Funding Plan",
      comment: "Funding plan active. Disbursement prep starts." });
  }
  if (pastIdx >= idx("Disbursed")) {
    out.push({ at: "Apr 28, 2026 · 13:30", actor: "Moses Tindi", role: "Program Accountant", action: "Disbursed",
      previousStatus: "Active Funding Plan", newStatus: "Disbursed",
      comment: "First disbursement released." });
  }
  if (status === "Returned by Program Lead") {
    out.push({ at: "Apr 18, 2026 · 14:30", actor: plName, role: "Program Lead", action: "Returned",
      previousStatus: "Submitted to Program Lead", newStatus: "Returned by Program Lead",
      comment: "Unrealistic workload — please rebalance weeks 2 & 3." });
  }
  for (const c of approvalConditions) {
    out.push({ at: c.addedAt, actor: c.addedBy, role: c.addedByRole === "RVP" ? "RVP" : "Country Director", action: "Approved",
      previousStatus: null, newStatus: null,
      comment: `Approval condition added: ${c.text}` });
  }
  return out;
}

function humaniseLastAction(s: ApprovalStatus): string {
  if (s === "Submitted to Program Lead")     return "Staff submitted plan to PL";
  if (s === "Returned by Program Lead")      return "PL returned to staff";
  if (s === "Approved by Program Lead")      return "PL approved, awaiting CD submission";
  if (s === "Submitted to Country Director") return "PL submitted to CD";
  if (s === "Returned by Country Director")  return "CD returned to PL";
  if (s === "Amended by Country Director")   return "CD amended budget";
  if (s === "Approved by Country Director")  return "CD approved, awaiting RVP submission";
  if (s === "Submitted to RVP")              return "CD submitted to RVP";
  if (s === "Returned by RVP")               return "RVP returned to CD";
  if (s === "Amended by RVP")                return "RVP amended budget";
  if (s === "Approved by RVP")               return "RVP final-approved";
  if (s === "Final Approved")                return "Final Approved";
  if (s === "Active Funding Plan")           return "Funding plan active";
  if (s === "Disbursed")                     return "Funds disbursed";
  if (s === "Closed")                        return "Closed";
  return "Draft";
}

// Build final list with computed totals + audit + amendments tied to id.
export const monthlyPlanSubmissions: MonthlyPlanSubmission[] = SUBMISSION_SEEDS.map((seed) => {
  const activities          = seed.activities.map((a) => activity(a));
  const requestedBudget     = sumBudget(activities);
  const availableFundsRecord= availableFundsRecords.find((f) => f.id === `af-${seed.programLeadId.toLowerCase()}`)
    ?? availableFundsRecords[0];
  const availableAllocation = availableFundsRecord.amountAvailable;
  const amendments: BudgetAmendment[] = seed.amendments.map((a) => ({
    ...a,
    submissionId: seed.id,
    difference: a.amendedAmount - a.originalAmount,
  }));
  const conditions: ApprovalCondition[] = seed.approvalConditions.map((c, i) => ({
    ...c, id: `${seed.id}-cond-${i + 1}`,
  }));
  const accountantNote = seed.accountantNote
    ? { ...seed.accountantNote, id: `${seed.id}-acct`, submissionId: seed.id }
    : undefined;
  const disbursement = seed.disbursement
    ? { ...seed.disbursement, id: `${seed.id}-disb`, submissionId: seed.id }
    : undefined;
  const amendedBudget = amendments.length > 0
    ? amendments[amendments.length - 1].amendedAmount
    : undefined;
  return {
    id:                     seed.id,
    financialYearId:        FY.id,
    monthLabel:             "May 2026",
    monthIso:               "2026-05",
    programLeadId:          seed.programLeadId,
    programLeadName:        seed.programLeadName,
    region:                 seed.region,
    staffId:                seed.staffId,
    staffName:              seed.staffName,
    status:                 seed.status,
    priority:               calculatePriorityScore(activities),
    priorityFactors:        seed.priorityFactors,
    activities,
    requestedBudget,
    amendedBudget,
    finalApprovedBudget:    seed.finalApprovedBudget,
    availableFundsRecordId: availableFundsRecord.id,
    availableAllocation,
    fundingGap:             requestedBudget - availableAllocation,
    amendments,
    approvalConditions:     conditions,
    accountantNote,
    disbursement,
    audit:                  buildAudit(seed.status, seed.programLeadName, seed.amendments, seed.approvalConditions, seed.accountantNote),
    lastAction:             humaniseLastAction(seed.status),
  };
});

export function getMonthlySubmission(id: string): MonthlyPlanSubmission | undefined {
  return monthlyPlanSubmissions.find((s) => s.id === id);
}

// ────────── Rollup helpers ──────────

export function monthlyApprovalKpis() {
  const subs = monthlyPlanSubmissions;
  const sum = (predicate: (s: MonthlyPlanSubmission) => boolean) =>
    subs.filter(predicate).reduce((a, s) => a + (s.amendedBudget ?? s.requestedBudget), 0);
  const requested = subs.reduce((a, s) => a + s.requestedBudget, 0);
  const available = subs.reduce((a, s) => a + s.availableAllocation, 0);
  const gap       = requested - available;
  const amendedThisMonth = subs.filter((s) => s.amendments.length > 0).length;
  return {
    totalRequested:        requested,
    totalAvailable:        available,
    approvedByPl:          sum((s) => s.status === "Approved by Program Lead" || pastStage(s.status, "Program Lead")),
    pendingCd:             sum((s) => s.status === "Submitted to Country Director" || s.status === "Approved by Program Lead"),
    fundingGap:            gap,
    submittedToRvp:        sum((s) => s.status === "Submitted to RVP"),
    finalApproved:         sum((s) => s.status === "Final Approved" || s.status === "Active Funding Plan" || s.status === "Disbursed" || s.status === "Approved by RVP"),
    returnedForCorrection: subs.filter((s) =>
      s.status === "Returned by Program Lead" ||
      s.status === "Returned by Country Director" ||
      s.status === "Returned by RVP"
    ).length,
    amendedThisMonth,
    activeFundingPlans:    subs.filter((s) => s.status === "Final Approved" || s.status === "Active Funding Plan" || s.status === "Disbursed").length,
  };
}

function pastStage(status: ApprovalStatus, stage: "Program Lead" | "Country Director" | "RVP"): boolean {
  const order = APPROVAL_STATUSES.indexOf(status);
  const markers = {
    "Program Lead":     APPROVAL_STATUSES.indexOf("Approved by Program Lead"),
    "Country Director": APPROVAL_STATUSES.indexOf("Approved by Country Director"),
    "RVP":              APPROVAL_STATUSES.indexOf("Approved by RVP"),
  };
  return order >= markers[stage];
}

// ────────── CD funds-matching ──────────

export type FundsMatchingRow = {
  submissionId:        string;
  programLead:         string;
  region:              string;
  requested:           number;
  amended?:            number;
  available:           number;
  gap:                 number;
  priority:            Priority;
  status:              ApprovalStatus;
  criticalActivities:  number;
  deferrableActivities:number;
  recommendation:      string;
  availableFunds:      AvailableFundsRecord;
};

export function generateFundsMatching(): FundsMatchingRow[] {
  return monthlyPlanSubmissions.map((s) => {
    const crit = s.activities.filter((a) => a.priority === "Critical" || a.ssaUrgent).length;
    const defr = s.activities.filter((a) => a.priority === "Deferrable" || a.priority === "Low").length;
    const recommendation =
      s.fundingGap <= 0
        ? "Fully fundable from available allocation."
        : crit > 0
          ? `Prioritise the ${crit} critical activity(ies). Defer ${defr} low-priority activity to next month.`
          : `Funding gap of ${formatUgxBig(s.fundingGap)}. Recommend partial funding or reallocation from surplus regions.`;
    const af = getAvailableFunds(s.availableFundsRecordId)!;
    return {
      submissionId:         s.id,
      programLead:          s.programLeadName,
      region:               s.region,
      requested:            s.requestedBudget,
      amended:              s.amendedBudget,
      available:            s.availableAllocation,
      gap:                  s.fundingGap,
      priority:             s.priority,
      status:               s.status,
      criticalActivities:   crit,
      deferrableActivities: defr,
      recommendation,
      availableFunds:       af,
    };
  });
}

// ────────── Amendment metrics ──────────

export type AmendmentMetrics = {
  totalAmendments:        number;
  totalAmountReduced:     number;
  totalAmountIncreased:   number;
  topReason:              string;
  activitiesMostReduced:  { type: MonthlyActivityType; count: number }[];
  regionsMostAmended:     { region: string; count: number }[];
  programLeadsMostReturned: { name: string; count: number }[];
  fundingGapAfter:        number;
};

export function amendmentMetrics(): AmendmentMetrics {
  const amendments = monthlyPlanSubmissions.flatMap((s) => s.amendments);
  const totalReduced = amendments
    .filter((a) => a.difference < 0)
    .reduce((acc, a) => acc + Math.abs(a.difference), 0);
  const totalIncreased = amendments
    .filter((a) => a.difference > 0)
    .reduce((acc, a) => acc + a.difference, 0);

  // Most common reason — substring match for the most frequent keyword.
  const reasons = amendments.map((a) => a.reason);
  const reasonCounts = reasons.reduce<Record<string, number>>((acc, r) => {
    const key = r.split(/[.;,]/)[0].slice(0, 60);
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});
  const topReason = Object.entries(reasonCounts).sort(([, a], [, b]) => b - a)[0]?.[0]
    ?? "—";

  // Activities most often appearing in `affectedActivities`.
  const activityHits: Record<string, number> = {};
  for (const a of amendments) {
    for (const actId of a.affectedActivities) {
      const submission = monthlyPlanSubmissions.find((s) => s.id === a.submissionId);
      const act = submission?.activities.find((x) => x.id === actId);
      if (!act) continue;
      activityHits[act.type] = (activityHits[act.type] ?? 0) + 1;
    }
  }
  const activitiesMostReduced = Object.entries(activityHits)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5)
    .map(([type, count]) => ({ type: type as MonthlyActivityType, count }));

  // Regions most often amended.
  const regionHits: Record<string, number> = {};
  for (const a of amendments) {
    const s = monthlyPlanSubmissions.find((x) => x.id === a.submissionId);
    if (s) regionHits[s.region] = (regionHits[s.region] ?? 0) + 1;
  }
  const regionsMostAmended = Object.entries(regionHits)
    .sort(([, a], [, b]) => b - a)
    .map(([region, count]) => ({ region, count }));

  // PLs with most returned plans.
  const plReturned: Record<string, number> = {};
  for (const s of monthlyPlanSubmissions) {
    if (s.status.startsWith("Returned")) {
      plReturned[s.programLeadName] = (plReturned[s.programLeadName] ?? 0) + 1;
    }
  }
  const programLeadsMostReturned = Object.entries(plReturned)
    .sort(([, a], [, b]) => b - a)
    .map(([name, count]) => ({ name, count }));

  const fundingGapAfter = monthlyPlanSubmissions.reduce((acc, s) => {
    const after = (s.amendedBudget ?? s.requestedBudget) - s.availableAllocation;
    return acc + Math.max(0, after);
  }, 0);

  return {
    totalAmendments: amendments.length,
    totalAmountReduced: totalReduced,
    totalAmountIncreased: totalIncreased,
    topReason,
    activitiesMostReduced,
    regionsMostAmended,
    programLeadsMostReturned,
    fundingGapAfter,
  };
}

// ────────── Final Approved Monthly Funding Plan artifact ──────────

export type FinalApprovedFundingPlan = {
  submissionId:         string;
  programLead:          string;
  region:               string;
  month:                string;
  approvedActivities:   PlannedActivity[];
  approvedBudget:       number;
  amendmentSummary:     { count: number; netDelta: number; reasons: string[] };
  conditions:           ApprovalCondition[];
  fundingSource:        AvailableFundsSource;
  fundingSourceNote?:   string;
  disbursementSchedule: { week: 1 | 2 | 3 | 4; amount: number }[];
  programAccountantNextSteps: string[];
};

export function generateFinalApprovedFundingPlan(
  s: MonthlyPlanSubmission,
): FinalApprovedFundingPlan | null {
  if (s.finalApprovedBudget == null) return null;
  const af = getAvailableFunds(s.availableFundsRecordId)!;
  const byWeek = [1, 2, 3, 4].map((w) => ({
    week: w as 1 | 2 | 3 | 4,
    amount: s.activities.filter((a) => a.week === w).reduce((acc, a) => acc + a.totalCost, 0),
  }));
  return {
    submissionId:         s.id,
    programLead:          s.programLeadName,
    region:               s.region,
    month:                s.monthLabel,
    approvedActivities:   s.activities,
    approvedBudget:       s.finalApprovedBudget,
    amendmentSummary: {
      count: s.amendments.length,
      netDelta: s.amendments.reduce((a, m) => a + m.difference, 0),
      reasons: s.amendments.map((a) => a.reason),
    },
    conditions:           s.approvalConditions,
    fundingSource:        af.source,
    fundingSourceNote:    af.restriction ?? af.notes,
    disbursementSchedule: byWeek,
    programAccountantNextSteps: [
      "Confirm bank details for each disbursement line",
      "Release Week 1 disbursement within 3 business days",
      "Track utilization weekly against Active Funding Plan",
      "Flag any deviation > 10% for CD review",
    ],
  };
}

// ────────── Status tone helper ──────────

export function statusTone(status: ApprovalStatus): "edify" | "green" | "amber" | "rose" | "violet" | "sky" | "slate" {
  if (status === "Draft")                                      return "slate";
  if (status === "Submitted to Program Lead")                  return "sky";
  if (status === "Submitted to Country Director")              return "sky";
  if (status === "Submitted to RVP")                           return "violet";
  if (status === "Approved by Program Lead")                   return "amber";
  if (status === "Approved by Country Director")               return "amber";
  if (status === "Amended by Country Director")                return "amber";
  if (status === "Amended by RVP")                             return "amber";
  if (status === "Approved by RVP")                            return "green";
  if (status === "Final Approved")                             return "green";
  if (status === "Active Funding Plan")                        return "green";
  if (status === "Disbursed")                                  return "green";
  if (status === "Closed")                                     return "slate";
  return "rose"; // returned by anyone
}

// Priority factor labels — used in the "Why?" drawer.
export const PRIORITY_FACTOR_LABEL: Record<PriorityFactorKind, string> = {
  "ssa-overdue":                "SSA overdue",
  "ssa-verification-pending":   "SSA verification pending",
  "core-behind-package":        "Core School behind 4+4 package",
  "training-followup-overdue":  "Training follow-up overdue",
  "high-risk-school":           "High-risk school",
  "low-ssa-score":              "Low SSA score",
  "special-project-deadline":   "Special project deadline",
  "previous-month-carryover":   "Previous-month carry-over",
  "funding-deadline":           "Funding deadline",
  "partner-dependency":         "Partner dependency",
  "route-efficiency":           "Route efficiency",
  "target-risk":                "Target risk",
};
