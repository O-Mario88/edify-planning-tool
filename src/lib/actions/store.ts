// In-memory store for W3 (Plan), W4 (CostSetting), W5 (WeeklyFundRequest,
// FundsReceived, Disbursement, Reimbursement, BalanceReturn).
//
// EVERY shape here mirrors prisma/schema.prisma exactly. The production
// swap is mechanical: replace the array operations in the server-action
// files with `prisma.X.create / update / findUnique`, wrapped in a
// `prisma.$transaction([...])` alongside the AuditEvent + Notification
// emits. The action signatures, return types, and validation order do
// not change.
//
// Stored on `globalThis` so:
//   • HMR doesn't lose state mid-session
//   • Server-side dev runtime keeps a single consistent view
//   • Tests can call `__resetEntityStore()` between cases

import "server-only";

// ─── Plan + PlannedActivity (W3) ───────────────────────────────────

export type PlanStatus =
  | "Draft"
  | "SubmittedForApproval"
  | "Approved"
  | "Returned"
  | "Active"
  | "Closed";

export type PlanRecord = {
  id:             string;
  authorId:       string;       // CCEO staffId
  authorName:     string;
  countryId:      string;
  monthIso:       string;       // "2026-05"
  status:         PlanStatus;
  submittedAt?:   string;
  approvedAt?:    string;
  approvedById?:  string;
  returnedReason?: string;
  totalCostCents: number;       // denormalised cache, recomputed on activity change
  createdAt:      string;
  updatedAt:      string;
};

export type ActivityKind =
  | "CLUSTER_TRAINING"
  | "IN_SCHOOL_COACHING"
  | "SCHOOL_VISIT"
  | "SSA_FOLLOW_UP"
  | "HANDOVER_MEETING"
  | "LESSON_OBSERVATION"
  | "PARTNER_FOLLOW_UP"
  | "TRAINING_FOLLOW_UP"
  | "DATA_COLLECTION"
  | "COURTESY_VISIT";

export type PlannedActivityStatus =
  | "Planned"
  | "Draft"
  | "SubmittedForVerification"
  | "SalesforceIdPending"
  | "Completed"
  | "Verified"
  | "AccountabilityClosed"
  | "Returned"
  | "Cancelled";

export type PlannedActivityRecord = {
  id:               string;
  planId:           string;
  schoolId?:        string;
  kind:             ActivityKind;
  title:            string;
  weekOfMonth:      number;     // 1..5
  scheduledDate?:   string;
  assigneeId?:      string;
  estCostCents:     number;
  status:           PlannedActivityStatus;
  interventionArea?: string;
  /** The exact Salesforce Activity ID the staff entered on completion (SVE-/TS-).
   *  Single source of truth for the verification queue — the IA copies THIS into
   *  Salesforce to confirm. */
  salesforceId?:    string;
  /** The exact NetSuite Expense ID the accountant entered to close accountability. */
  netsuiteExpenseId?: string;
  createdAt:        string;
  updatedAt:        string;
};

// ─── CostSetting (W4) ──────────────────────────────────────────────

export type CostSettingStatus = "Draft" | "Active" | "Superseded";

export type CostSettingRecord = {
  id:               string;
  countryId:        string;
  activityKind:     ActivityKind;
  effectiveFyIso:   string;     // "2026-FY"
  costPerUnitCents: number;
  status:           CostSettingStatus;
  proposedById:     string;
  approvedById?:    string;
  approvedAt?:      string;
  supersededAt?:    string;
  createdAt:        string;
  updatedAt:        string;
};

// ─── Weekly Fund pipeline (W5) ─────────────────────────────────────
//
// The engine in src/lib/funds/weekly-fund-engine.ts already operates
// over its own `WeeklyFundRequest` / `DisbursementRecord` /
// `ReimbursementClaim` / `BalanceReturn` types. The store re-exports
// those engine types so the action layer doesn't translate shapes
// between the engine and Prisma.

export type {
  WeeklyFundRequest,
  WeeklyFundRequestStatus,
  DisbursementRecord,
  FundsReceivedRecord,
  ReimbursementClaim,
  ReimbursementStatus,
  BalanceReturn,
  Money,
} from "@/lib/funds/weekly-fund-types";

import type {
  WeeklyFundRequest,
  DisbursementRecord,
  FundsReceivedRecord,
  ReimbursementClaim,
  BalanceReturn,
} from "@/lib/funds/weekly-fund-types";

// ─── SchoolVisit (W6) ──────────────────────────────────────────────

export type SchoolVisitRecord = {
  id:                    string;
  userId:                string;
  schoolId:              string;
  kind:                  ActivityKind;
  date:                  string;
  completed:             boolean;
  matchState?:           "SMART_MATCH" | "POSSIBLE_MATCH" | "NO_MATCH" | "VERIFIED";
  salesforceActivityId?: string;
  createdAt:             string;
};

// ─── Donor evidence + verification (W6 + W8 + W11) ─────────────────

export type DonorParticipantType =
  | "Teacher"
  | "SchoolLeader"
  | "Parent"
  | "Student"
  | "DistrictOfficial"
  | "PartnerStaff"
  | "Other";

export type DonorEvidenceStatus =
  | "None"
  | "Captured"
  | "Uploaded"
  | "CceoConfirmed"
  | "MeVerified"
  | "Rejected";

export type DonorCountStatus =
  | "included_verified"
  | "included_confirmed"
  | "pending_evidence"
  | "pending_verification"
  | "excluded_duplicate"
  | "excluded_missing_data"
  | "excluded_out_of_period"
  | "excluded_not_eligible";

export type TrainingParticipantRecord = {
  id:                  string;
  activityId:          string;
  participantType:     DonorParticipantType;
  participantName:    string;
  gender?:             "M" | "F" | "X";
  phone?:              string;
  email?:              string;
  externalId?:         string;
  /** Canonical dedup hash. Computed at write time from preferred id source. */
  identityKey:         string;
  schoolId?:           string;
  schoolRole?:         string;
  evidenceStatus:      DonorEvidenceStatus;
  /** Stub S3 URI — production swap replaces with the real bucket URL. */
  evidenceUri?:        string;
  evidenceNotes?:      string;
  donorCountStatus:    DonorCountStatus;
  cceoConfirmedAt?:    string;
  cceoConfirmedById?:  string;
  meVerifiedAt?:       string;
  meVerifiedById?:     string;
  rejectedReason?:     string;
  createdAt:           string;
  updatedAt:           string;
};

// ─── SsaSnapshot (W7) ──────────────────────────────────────────────

export type InterventionArea =
  | "TeachingAndLearning"
  | "FinancialHealth"
  | "ChristlikeBehaviour"
  | "ExposureToWordOfGod"
  | "GovernmentComplianceAndRequirements"
  | "Leadership"
  | "EducationTechnology"
  | "LearningEnvironment";

export type SsaTrend = "Improved" | "Held" | "Declined" | "Inconclusive";

export type SsaSnapshotRecord = {
  id:               string;
  schoolId:         string;
  interventionArea: InterventionArea;
  score:            number;            // 0..10
  completedAt:      string;
  completed:        boolean;
  trend:            SsaTrend;
  /** previousId set at write time from the latest snapshot in the same area. */
  previousId?:      string;
  conductedById?:   string;
  evidenceStatus:   DonorEvidenceStatus;
  donorCountStatus: DonorCountStatus;
  notes?:           string;
  createdAt:        string;
};

// ─── PartnerActivity (W8) ──────────────────────────────────────────

export type PartnerActivityStatus =
  | "Planned"
  | "Delivered"
  | "CceoConfirmed"
  | "MeVerified"
  | "Rejected"
  | "Cancelled";

export type PartnerActivityRecord = {
  id:                  string;
  partnerId:           string;
  partnerName:         string;
  schoolId:            string;
  interventionArea:    InterventionArea;
  title:               string;
  date:                string;
  status:              PartnerActivityStatus;
  teachersReached?:    number;
  leadersReached?:     number;
  studentsReached?:    number;
  evidenceUri?:        string;
  evidenceNotes?:      string;
  evidenceStatus:      DonorEvidenceStatus;
  donorCountStatus:    DonorCountStatus;
  cceoConfirmedAt?:    string;
  cceoConfirmedById?:  string;
  meVerifiedAt?:       string;
  meVerifiedById?:     string;
  rejectedReason?:     string;
  costUgxCents?:       number;
  /** Set when a payment Disbursement is created against this activity.
   * Enforces integrity rule #6 — only MeVerified activities pay out. */
  paymentDisbursementId?: string;
  createdAt:           string;
  updatedAt:           string;
};

// ─── LeaveRecord (W10) ─────────────────────────────────────────────

export type LeaveKind = "Annual" | "Study" | "Compassionate" | "Sick";
export type LeaveStatus = "Pending" | "Approved" | "Rejected" | "Cancelled";

export type LeaveRecord = {
  id:           string;
  staffId:      string;
  staffName:    string;
  kind:         LeaveKind;
  startDate:    string;
  endDate:      string;
  /** Inclusive day-count, cached so pace-status doesn't recompute. */
  days:         number;
  reason?:      string;
  status:       LeaveStatus;
  approvedAt?:  string;
  approvedById?: string;
  createdAt:    string;
};

// ─── DonorMetricSnapshot (W11) ─────────────────────────────────────
//
// Persisted donor report. The same (filtersHash, roleScope,
// operationalCycle) tuple should re-produce identical numbers — that's
// integrity rule "deterministic donor report" from Phase 11.

export type DonorRoleScope =
  | "CCEO"
  | "ProgramLead"
  | "ImpactAssessment"
  | "CountryDirector"
  | "RVP"
  | "GlobalDonorReport";

export type DonorMetricSnapshotRecord = {
  id:                string;
  roleScope:         DonorRoleScope;
  userId:            string;
  scopeLabel:        string;
  operationalCycle:  string;            // "FY 2025/26 · Q4"
  dateRangeStart:    string;
  dateRangeEnd:      string;
  /** SHA-256-ish hash of canonical filter JSON. Deterministic. */
  filtersHash:       string;
  filtersJson:       Record<string, unknown>;

  teachersTrained?:            number;
  schoolLeadersTrained?:       number;
  studentsImpacted?:           number;
  schoolsReached?:             number;
  districtsCovered?:           number;
  trainingsDelivered?:         number;
  visitsCompleted?:            number;
  ssaCompleted?:               number;
  schoolsImproved?:            number;
  partnerActivitiesConfirmed?: number;
  totalInvestmentUgx?:         number;
  costPerSchoolReachedUgx?:    number;
  costPerTeacherTrainedUgx?:   number;
  costPerStudentImpactedUgx?:  number;

  verifiedCount:            number;
  pendingEvidenceCount:     number;
  pendingVerificationCount: number;
  excludedCount:            number;
  readinessScore:           number;

  generatedAt:     string;
  generatedByName: string;
};

// ─── Store shape + globalThis backing ──────────────────────────────

type EntityStore = {
  plans:              PlanRecord[];
  activities:         PlannedActivityRecord[];
  costSettings:       CostSettingRecord[];
  fundRequests:       WeeklyFundRequest[];
  fundsReceived:      FundsReceivedRecord[];
  disbursements:      DisbursementRecord[];
  reimbursements:     ReimbursementClaim[];
  balanceReturns:     BalanceReturn[];
  schoolVisits:       SchoolVisitRecord[];
  trainingParticipants: TrainingParticipantRecord[];
  ssaSnapshots:       SsaSnapshotRecord[];
  partnerActivities:  PartnerActivityRecord[];
  leaveRecords:       LeaveRecord[];
  donorSnapshots:     DonorMetricSnapshotRecord[];
  // Idempotency keys we've already seen — keeps double-clicks /
  // duplicate-submit bugs from creating duplicate side effects.
  seenIdempotencyKeys: Set<string>;
};

const STORE_KEY = "__edify_entity_store__";
type GlobalWithStore = typeof globalThis & { [STORE_KEY]?: EntityStore };

function getStore(): EntityStore {
  const g = globalThis as GlobalWithStore;
  if (!g[STORE_KEY]) {
    g[STORE_KEY] = {
      plans:              [],
      activities:         [],
      costSettings:       [],
      fundRequests:       [],
      fundsReceived:      [],
      disbursements:      [],
      reimbursements:     [],
      balanceReturns:     [],
      schoolVisits:        [],
      trainingParticipants: [],
      ssaSnapshots:        [],
      partnerActivities:   [],
      leaveRecords:        [],
      donorSnapshots:      [],
      seenIdempotencyKeys: new Set(),
    };
  }
  // Lazy migration: any field added in a later version is back-filled
  // here so an older cached store (held across HMR) doesn't break new
  // callers. Cheap, idempotent. Production: alembic-style migration.
  const s = g[STORE_KEY]!;
  s.plans              ??= [];
  s.activities         ??= [];
  s.costSettings       ??= [];
  s.fundRequests       ??= [];
  s.fundsReceived      ??= [];
  s.disbursements      ??= [];
  s.reimbursements     ??= [];
  s.balanceReturns     ??= [];
  s.schoolVisits       ??= [];
  s.trainingParticipants ??= [];
  s.ssaSnapshots       ??= [];
  s.partnerActivities  ??= [];
  s.leaveRecords       ??= [];
  s.donorSnapshots     ??= [];
  s.seenIdempotencyKeys ??= new Set();
  return s;
}

export function plans()                { return getStore().plans; }
export function activities()           { return getStore().activities; }
export function costSettings()         { return getStore().costSettings; }
export function fundRequests()         { return getStore().fundRequests; }
export function fundsReceived()        { return getStore().fundsReceived; }
export function disbursements()        { return getStore().disbursements; }
export function reimbursements()       { return getStore().reimbursements; }
export function balanceReturns()       { return getStore().balanceReturns; }
export function schoolVisits()         { return getStore().schoolVisits; }
export function trainingParticipants() { return getStore().trainingParticipants; }
export function ssaSnapshots()         { return getStore().ssaSnapshots; }
export function partnerActivities()    { return getStore().partnerActivities; }
export function leaveRecords()         { return getStore().leaveRecords; }
export function donorSnapshots()       { return getStore().donorSnapshots; }

// ─── ID helpers ────────────────────────────────────────────────────

export function newId(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

// ─── Idempotency ───────────────────────────────────────────────────
//
// Pass an opaque key derived from the operation (e.g. a NetSuite
// expense ID or a "{actor}:{planId}:approve" combo). The first call
// records the key and proceeds; subsequent calls with the same key
// short-circuit. Production: this lives in a Prisma table with a
// unique constraint so it's cluster-safe.

export function claimIdempotencyKey(key: string): boolean {
  const seen = getStore().seenIdempotencyKeys;
  if (seen.has(key)) return false;
  seen.add(key);
  return true;
}

// ─── Mutators (find-by-id + update helpers) ────────────────────────
//
// Co-located so the action files don't reach into the array directly.
// When the Prisma swap happens, replace each helper body with the
// corresponding Prisma call — call sites do not change.

export function findPlan(id: string): PlanRecord | undefined {
  return getStore().plans.find((p) => p.id === id);
}

export function updatePlan(id: string, patch: Partial<PlanRecord>): PlanRecord | undefined {
  const store = getStore();
  const idx = store.plans.findIndex((p) => p.id === id);
  if (idx === -1) return undefined;
  store.plans[idx] = { ...store.plans[idx], ...patch, updatedAt: new Date().toISOString() };
  return store.plans[idx];
}

export function findActivity(id: string): PlannedActivityRecord | undefined {
  return getStore().activities.find((a) => a.id === id);
}

export function updateActivity(id: string, patch: Partial<PlannedActivityRecord>): PlannedActivityRecord | undefined {
  const store = getStore();
  const idx = store.activities.findIndex((a) => a.id === id);
  if (idx === -1) return undefined;
  store.activities[idx] = { ...store.activities[idx], ...patch, updatedAt: new Date().toISOString() };
  return store.activities[idx];
}

export function findCostSetting(id: string): CostSettingRecord | undefined {
  return getStore().costSettings.find((c) => c.id === id);
}

export function updateCostSetting(id: string, patch: Partial<CostSettingRecord>): CostSettingRecord | undefined {
  const store = getStore();
  const idx = store.costSettings.findIndex((c) => c.id === id);
  if (idx === -1) return undefined;
  store.costSettings[idx] = { ...store.costSettings[idx], ...patch, updatedAt: new Date().toISOString() };
  return store.costSettings[idx];
}

export function findFundRequest(id: string): WeeklyFundRequest | undefined {
  return getStore().fundRequests.find((r) => r.id === id);
}

export function upsertFundRequest(req: WeeklyFundRequest): WeeklyFundRequest {
  const store = getStore();
  const idx = store.fundRequests.findIndex((r) => r.id === req.id);
  if (idx === -1) store.fundRequests.push(req);
  else store.fundRequests[idx] = req;
  return req;
}

export function findDisbursement(id: string): DisbursementRecord | undefined {
  return getStore().disbursements.find((d) => d.id === id);
}

export function updateDisbursement(id: string, patch: Partial<DisbursementRecord>): DisbursementRecord | undefined {
  const store = getStore();
  const idx = store.disbursements.findIndex((d) => d.id === id);
  if (idx === -1) return undefined;
  store.disbursements[idx] = { ...store.disbursements[idx], ...patch };
  return store.disbursements[idx];
}

// Critical guard: enforces the unique (weeklyFundRequestId, fundsReceivedId)
// constraint flagged by the audit. Prevents double-pay if Accountant
// clicks "Disburse" twice in rapid succession.
export function disbursementExistsFor(weeklyFundRequestId: string, fundsReceivedId: string): boolean {
  return getStore().disbursements.some(
    (d) => d.weeklyFundRequestId === weeklyFundRequestId && d.fundsReceivedId === fundsReceivedId,
  );
}

// ─── W6 / W7 / W8 / W10 / W11 mutators ─────────────────────────────

export function findTrainingParticipant(id: string): TrainingParticipantRecord | undefined {
  return getStore().trainingParticipants.find((p) => p.id === id);
}
export function updateTrainingParticipant(id: string, patch: Partial<TrainingParticipantRecord>): TrainingParticipantRecord | undefined {
  const s = getStore();
  const idx = s.trainingParticipants.findIndex((p) => p.id === id);
  if (idx === -1) return undefined;
  s.trainingParticipants[idx] = { ...s.trainingParticipants[idx], ...patch, updatedAt: new Date().toISOString() };
  return s.trainingParticipants[idx];
}

export function findSsaSnapshot(id: string): SsaSnapshotRecord | undefined {
  return getStore().ssaSnapshots.find((s) => s.id === id);
}

/** Latest snapshot for a given (schoolId, interventionArea) — drives
 * `previousId` + trend computation on the next snapshot write. */
export function latestSsaSnapshotFor(schoolId: string, area: InterventionArea): SsaSnapshotRecord | undefined {
  return getStore().ssaSnapshots
    .filter((s) => s.schoolId === schoolId && s.interventionArea === area)
    .sort((a, b) => b.completedAt.localeCompare(a.completedAt))[0];
}

export function findPartnerActivity(id: string): PartnerActivityRecord | undefined {
  return getStore().partnerActivities.find((p) => p.id === id);
}
export function updatePartnerActivity(id: string, patch: Partial<PartnerActivityRecord>): PartnerActivityRecord | undefined {
  const s = getStore();
  const idx = s.partnerActivities.findIndex((p) => p.id === id);
  if (idx === -1) return undefined;
  s.partnerActivities[idx] = { ...s.partnerActivities[idx], ...patch, updatedAt: new Date().toISOString() };
  return s.partnerActivities[idx];
}

export function findLeaveRecord(id: string): LeaveRecord | undefined {
  return getStore().leaveRecords.find((l) => l.id === id);
}
export function updateLeaveRecord(id: string, patch: Partial<LeaveRecord>): LeaveRecord | undefined {
  const s = getStore();
  const idx = s.leaveRecords.findIndex((l) => l.id === id);
  if (idx === -1) return undefined;
  s.leaveRecords[idx] = { ...s.leaveRecords[idx], ...patch };
  return s.leaveRecords[idx];
}

/** Plan completion percentage = (Verified count / total non-cancelled) × 100.
 * Integrity rule #3: verifying an activity advances its parent plan's %.
 * Centralized so dashboards + plan-detail compute the same number. */
export function planCompletionPercent(planId: string): number {
  const acts = getStore().activities.filter((a) => a.planId === planId && a.status !== "Cancelled");
  if (acts.length === 0) return 0;
  const verified = acts.filter((a) => a.status === "Verified").length;
  return Math.round((verified / acts.length) * 100);
}

// ─── Test reset ────────────────────────────────────────────────────

export function __resetEntityStore() {
  const g = globalThis as GlobalWithStore;
  g[STORE_KEY] = undefined;
}
