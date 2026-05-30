// Monthly Fund Request — type layer.
//
// The Monthly Fund Request (MFR) is the country-level budget envelope
// for a given month. It is NOT a spreadsheet. It is auto-generated
// from the previously-approved monthly plans + the active CD cost
// settings, then routed through the approval chain:
//
//   Planned activities (approved monthly plans)
//     → System builds MFR (auto-generated)
//     → Program Lead reviews program-scope rows
//     → Country Director reviews + adds administration budget items
//     → CD approves
//     → RVP sees the request only after CD approval
//     → RVP approves / returns / holds
//     → Finance / Accountant prepares disbursement
//
// Every numeric cell is a doorway — clicking any total / weekly amount
// reveals the source activity records that produced the number. No
// number in this system is opaque.
//
// Naming convention: kebab-case file, PascalCase types, camelCase
// fields. Mirrors the WeeklyFundRequest types in this same folder.

import type { Money } from "./weekly-fund-types";

// ────────── Lifecycle ─────────────────────────────────────────────────

export type MonthlyFundRequestStatus =
  | "AUTO_GENERATED"
  | "UNDER_PL_REVIEW"
  | "SUBMITTED_TO_CD"
  | "UNDER_CD_REVIEW"
  | "RETURNED_TO_PL"
  | "CD_APPROVED"
  | "SUBMITTED_TO_RVP"
  | "UNDER_RVP_REVIEW"
  | "RVP_APPROVED"
  | "RETURNED_TO_CD"
  | "ON_HOLD"
  | "SENT_TO_FINANCE"
  | "DISBURSEMENT_PREPARED"
  | "CLOSED";

export const MFR_STATUS_LABEL: Record<MonthlyFundRequestStatus, string> = {
  AUTO_GENERATED:        "Auto-Generated",
  UNDER_PL_REVIEW:       "Under PL Review",
  SUBMITTED_TO_CD:       "Submitted to CD",
  UNDER_CD_REVIEW:       "Under CD Review",
  RETURNED_TO_PL:        "Returned to PL",
  CD_APPROVED:           "CD Approved",
  SUBMITTED_TO_RVP:      "Submitted to RVP",
  UNDER_RVP_REVIEW:      "Under RVP Review",
  RVP_APPROVED:          "RVP Approved",
  RETURNED_TO_CD:        "Returned to CD",
  ON_HOLD:               "On Hold",
  SENT_TO_FINANCE:       "Sent to Finance",
  DISBURSEMENT_PREPARED: "Disbursement Prepared",
  CLOSED:                "Closed",
};

// Statuses where each role can act. Source of truth for the action bar.
export const PL_ACTION_STATUSES: ReadonlySet<MonthlyFundRequestStatus> = new Set([
  "AUTO_GENERATED",
  "UNDER_PL_REVIEW",
  "RETURNED_TO_PL",
]);
export const CD_ACTION_STATUSES: ReadonlySet<MonthlyFundRequestStatus> = new Set([
  "SUBMITTED_TO_CD",
  "UNDER_CD_REVIEW",
  "RETURNED_TO_CD",
]);
export const RVP_ACTION_STATUSES: ReadonlySet<MonthlyFundRequestStatus> = new Set([
  "SUBMITTED_TO_RVP",
  "UNDER_RVP_REVIEW",
  "ON_HOLD",
]);

// Statuses that mean "the request has been routed to the next stage".
export const POST_CD_APPROVAL_STATUSES: ReadonlySet<MonthlyFundRequestStatus> = new Set([
  "CD_APPROVED",
  "SUBMITTED_TO_RVP",
  "UNDER_RVP_REVIEW",
  "RVP_APPROVED",
  "RETURNED_TO_CD",
  "ON_HOLD",
  "SENT_TO_FINANCE",
  "DISBURSEMENT_PREPARED",
  "CLOSED",
]);

// ────────── Line item — staff / partner / training / admin ───────────

export type MfrLineKind =
  | "staff"
  | "partner"
  | "training"
  | "cluster"
  | "admin"
  | "special_project";

export type MfrActivityCategory =
  | "StaffVisits"
  | "PartnerVisits"
  | "SSA"
  | "ClusterTraining"
  | "GroupTrainings"
  | "Meals"
  | "Transport"
  | "Accommodation"
  | "Admin";

export type WeekBuckets = {
  w1: number;
  w2: number;
  w3: number;
  w4: number;
  w5: number; // months with 5 planning weeks
};

export type MfrLine = {
  id:                    string;
  fundRequestId:         string;
  kind:                  MfrLineKind;
  team:                  string;            // "Team East", "Team North"…
  region:                string;
  district?:             string;

  // Identity
  staffId?:              string;
  staffName?:            string;
  staffRole?:            string;
  partnerId?:            string;
  partnerName?:          string;
  particulars:           string;            // "Core, Client schools coaching and post training visits"

  // Activity category breakdown — every staff line carries all
  // category columns (zero where the staff doesn't have activities
  // in that category) so the matrix renders cleanly.
  staffVisits:           CategoryCell;
  partnerVisits:         CategoryCell;
  ssa:                   CategoryCell;
  clusterTraining:       CategoryCell;
  groupTrainings:        CategoryCell;

  // Weekly meal allocation (auto-derived from activity schedule +
  // district type + CD cost settings).
  mealsByWeek:           WeekBuckets;
  mealsTotal:            number;

  // Transport allocation (auto-derived from school count + district
  // type + CD transport rate).
  transportAllocation:   number;

  // Accommodation (overnight stays).
  accommodationAllocation: number;

  // Sum of every category for this row.
  totalMonthlyAllocation: number;

  // Pointers back to the source activities that built this line.
  sourceActivityIds:     string[];
  calculationMethod:     string;            // human-readable note
};

export type CategoryCell = {
  // For activity categories the cell has: number of items, unit cost,
  // and a total. For categories that don't apply (e.g. SSA on a
  // partner line), the count is 0 and total is 0.
  count:    number;
  unitCost: number;
  total:    number;
};

// ────────── Administration budget items (CD-added) ───────────────────

export type AdminBudgetCategory =
  | "Rent"
  | "Airtime"
  | "Internet"
  | "OfficeUtilities"
  | "OfficeSupplies"
  | "Printing"
  | "Stationery"
  | "StaffCoordination"
  | "AdministrationTransport"
  | "BankCharges"
  | "Communication"
  | "EquipmentMaintenance"
  | "MeetingCosts"
  | "Other";

export const ADMIN_BUDGET_LABEL: Record<AdminBudgetCategory, string> = {
  Rent:                    "Rent",
  Airtime:                 "Airtime",
  Internet:                "Internet",
  OfficeUtilities:         "Office utilities",
  OfficeSupplies:          "Office supplies",
  Printing:                "Printing",
  Stationery:              "Stationery",
  StaffCoordination:       "Staff coordination",
  AdministrationTransport: "Administration transport",
  BankCharges:             "Bank charges",
  Communication:           "Communication",
  EquipmentMaintenance:    "Equipment maintenance",
  MeetingCosts:            "Meeting costs",
  Other:                   "Other",
};

export type MfrAdminItem = {
  id:             string;
  fundRequestId:  string;
  category:       AdminBudgetCategory;
  itemName:       string;
  description?:   string;
  quantity:       number;
  unitCost:       number;
  totalCost:      number;
  week:           1 | 2 | 3 | 4 | 5 | "Monthly";
  justification?: string;
  addedByCdId:    string;
  addedByCdName:  string;
  createdAt:      string;
};

// ────────── Source drilldown ─────────────────────────────────────────
//
// Every numeric cell on the matrix maps back to one or more source
// records — clicking a cell opens the drawer showing the activities
// that built the number. This is the "no number is opaque" rule.

export type MfrSourceRecord = {
  id:              string;
  fundRequestId:   string;
  lineId:          string;
  sourceType:
    | "WeeklyActivity"
    | "PlannedSchoolVisit"
    | "PlannedTraining"
    | "PlannedClusterMeeting"
    | "PlannedSsaActivity"
    | "PlannedPartnerActivity"
    | "AdminItem";
  sourceId:        string;
  activityDate?:   string;            // ISO YYYY-MM-DD
  plannedWeek:     1 | 2 | 3 | 4 | 5 | null;
  schoolId?:       string;
  schoolName?:     string;
  clusterId?:      string;
  clusterName?:    string;
  staffId?:        string;
  staffName?:      string;
  partnerId?:      string;
  partnerName?:    string;
  district?:       string;
  amount:          number;
  costCategory:    MfrActivityCategory;
  description:     string;
};

// ────────── Approval event (audit trail) ─────────────────────────────

export type MfrApprovalEvent = {
  id:            string;
  fundRequestId: string;
  fromStatus:    MonthlyFundRequestStatus | "—";
  toStatus:      MonthlyFundRequestStatus;
  actorRole:     "ProgramLead" | "CountryDirector" | "RVP" | "System";
  actorId:       string;
  actorName:     string;
  at:            string;
  note?:         string;
};

// ────────── Validation warning ───────────────────────────────────────

export type MfrValidationSeverity = "critical" | "warning" | "info";

export type MfrValidationIssue = {
  id:       string;
  severity: MfrValidationSeverity;
  code:
    | "MISSING_DATE"
    | "MISSING_WEEK"
    | "MISSING_PARTICIPANT_COUNT"
    | "MISSING_DISTRICT"
    | "MISSING_STAFF_PRIMARY_DISTRICT"
    | "MISSING_COST_SETTING"
    | "PARTNER_ACTIVITY_NOT_SCHEDULED"
    | "ACTIVITY_OUTSIDE_MONTH"
    | "DUPLICATE_ACTIVITY"
    | "ACCOMMODATION_NO_OVERNIGHT_FLAG"
    | "EVIDENCE_MISSING_DONOR_LINKED"
    | "BUDGET_ITEM_MISSING_JUSTIFICATION";
  message:  string;
  // What to link to so the reviewer can fix it.
  lineId?:    string;
  adminItemId?: string;
  sourceActivityId?: string;
};

// ────────── Cost settings snapshot ───────────────────────────────────
//
// Frozen with the fund request at generation time so re-rendering the
// request months later still produces the same numbers even if the
// CD has since rotated cost rates.

export type MfrCostSettingsSnapshot = {
  versionId:                       string;
  fyLabel:                         string;
  capturedAtIso:                   string;

  // Visit rates
  staffVisitCostPerVisit:          number;
  partnerVisitLumpSum:             number;
  partnerVisitCostPerVisit:        number;
  ssaCostPerActivity:              number;

  // Transport (per school)
  primaryDistrictTransportPerSchool:   number;
  secondaryDistrictTransportPerSchool: number;

  // Trainings
  clusterTrainingPerSchool:        number;
  clusterTrainingSessionFee:       number;
  groupTrainingPerSchool:          number;
  inSchoolTrainingPerSchool:       number;
  trainingVenueFee:                number;
  trainingMobilisationPerParticipant: number;
  trainingFacilitatorFee:          number;

  // Meals (per person per day)
  breakfast:                       number;
  lunch:                           number;
  dinner:                          number;
  accommodation:                   number;
  participantMealsPerSession:      number;

  // Cluster meeting
  clusterMeetingPerParticipant:    number;

  // Special project
  ccSelMealsPerParticipant:        number;
  tofPrimaryFeePerSession:         number;
  tofSecondaryFeePerSession:       number;
};

// ────────── Aggregate Monthly Fund Request ───────────────────────────

export type MonthlyFundRequest = {
  id:                   string;
  monthLabel:           string;       // "April 2026"
  monthIso:             string;       // "2026-04"
  quarter:              "Q1" | "Q2" | "Q3" | "Q4";
  fyLabel:              string;       // "FY 2026"
  countryId:            string;
  countryName:          string;
  programLeadId:        string;
  programLeadName:      string;
  countryDirectorId?:   string;
  countryDirectorName?: string;
  rvpId?:               string;
  rvpName?:             string;

  status:               MonthlyFundRequestStatus;

  generatedFromIso:     string;       // YYYY-MM-01
  generatedToIso:       string;       // last day of month
  generatedAtIso:       string;
  generatedByName:      string;

  // Lifecycle pointers
  plReviewedAtIso?:     string;
  submittedToCdAtIso?:  string;
  cdApprovedAtIso?:     string;
  submittedToRvpAtIso?: string;
  rvpApprovedAtIso?:    string;
  returnedReason?:      string;

  // Totals (auto-computed; never typed by hand)
  totalProgramCost:     Money;
  totalAdminCost:       Money;
  grandTotal:           Money;

  // Lines grouped by team / partners / special project
  lines:                MfrLine[];
  adminItems:           MfrAdminItem[];
  sources:              MfrSourceRecord[];
  approvalHistory:      MfrApprovalEvent[];
  validationIssues:     MfrValidationIssue[];

  costSettings:         MfrCostSettingsSnapshot;
  notes?:               string;
};

// ────────── Team / category grouping helpers ─────────────────────────

export const MFR_TEAMS = [
  "Team East",
  "Team North",
  "Team West",
  "Team Central",
  "Partners",
  "Special Projects",
  "Administration",
] as const;
export type MfrTeam = (typeof MFR_TEAMS)[number];

export const CATEGORY_HEADER_LABEL: Record<MfrActivityCategory, string> = {
  StaffVisits:     "Staff Visits",
  PartnerVisits:   "Partner Visits",
  SSA:             "SSA",
  ClusterTraining: "Cluster Training",
  GroupTrainings:  "Group Trainings",
  Meals:           "Disbursement for Meals",
  Transport:       "Transport",
  Accommodation:   "Accommodation",
  Admin:           "Administration",
};
