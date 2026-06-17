// Unified Core School lifecycle — one data model, one schoolId.
//
// Every record here keys on IntakeSchool.schoolId (the School Directory is the
// single source of truth). This replaces the disconnected mocks (ssa-mock
// candidates, core-school-plan-mock plans). Shapes mirror a future Prisma
// schema; the in-memory store (core-store.ts) is the mechanical swap point.
//
// Lifecycle:
//   School Directory → SSA ≥ 7.5 → Candidate → Verification → Onboarding
//   → Core Plan (4 priority interventions) → 8 activity slots (4 visits +
//   4 trainings) → execution (assign → schedule → complete → SF ID → IA →
//   accountant) → Follow-Up SSA → Impact → Champion.

import type { SsaInterventionArea, SchoolType } from "@/lib/intake/intake-core";

export type { SsaInterventionArea, SchoolType };

/** 8-area score map (0–10 each). */
export type CoreSsaScores = Partial<Record<SsaInterventionArea, number>>;

// ─── SSA snapshots (baseline + follow-up, one model) ────────────────

export type CoreSsaKind = "candidate" | "baseline" | "followup";

export type CoreSsaSnapshot = {
  id: string;            // ssaRecordId
  schoolId: string;
  kind: CoreSsaKind;
  fy: string;            // "2026"
  date: string;          // ISO
  scores: CoreSsaScores;
  average: number;
  assessedById?: string;
  /** Set on a candidate snapshot once a verification ID is entered. */
  verificationId?: string;
};

// ─── Candidate (derived from directory + SSA, overlaid with status) ──

export type CoreCandidateStatus =
  | "Candidate"
  | "Verification Pending"
  | "Verification Submitted"
  | "Verified Potential Core"
  | "Rejected Candidate"
  | "Onboarding Pending"
  | "Onboarded as Core";

/** A candidate is a directory school with an FY SSA ≥ 7.5 — derived, then
 *  decorated with the live verification/onboarding status from the store. */
export type CoreCandidate = {
  schoolId: string;
  schoolName: string;
  district: string;
  region: string;
  cluster?: string;
  clusterId?: string;
  accountOwnerName?: string;
  enrollment?: number;
  currentSchoolType: SchoolType;
  ssaRecordId: string;
  fy: string;
  averageScore: number;
  bestInterventions: { area: SsaInterventionArea; score: number }[];
  weakestInterventions: { area: SsaInterventionArea; score: number }[];
  candidateStatus: CoreCandidateStatus;
  verificationId?: string;
  recommendedOnboardingMonth: "October";
  recommendedOnboardingFy: string;
};

export type CoreCandidateVerification = {
  id: string;
  schoolId: string;
  ssaRecordId: string;
  verificationId: string;   // exact entered SSA Verification ID
  verifiedById: string;
  verifiedByName: string;
  verifiedAt: string;
  status: "Verified Potential Core" | "Rejected";
  comments?: string;
};

// ─── Onboarding (Client/Potential Core → Core transition record) ────

export type CoreOnboardingStatus = "Onboarded" | "Returned" | "Rejected" | "Deferred";

export type CoreSchoolOnboarding = {
  id: string;
  schoolId: string;
  fy: string;
  previousSchoolType: SchoolType;
  newSchoolType: "Core";
  baselineSSARecordId: string;
  baselineAverageScore: number;
  onboardedById: string;
  onboardedByName: string;
  onboardedAt: string;
  onboardingReason?: string;
  status: CoreOnboardingStatus;
};

// ─── Core profile + champion ────────────────────────────────────────

export type ChampionStatus =
  | "Not Eligible"
  | "Potential Champion"
  | "Under Review"
  | "IA Verified"
  | "PL Recommended"
  | "CD Approved"
  | "Verified Champion"
  | "Champion Mentor School";

export type CoreSchoolProfile = {
  id: string;
  schoolId: string;
  activeCorePlanId?: string;
  coreStartFy: string;
  championStatus: ChampionStatus;
  status: "Active" | "Closed";
};

// ─── Core plan ──────────────────────────────────────────────────────

export type CorePlanStatus =
  | "Draft"
  | "Active"
  | "In Progress"
  | "Completed Pending Follow-Up SSA"
  | "Follow-Up SSA Scheduled"
  | "Impact Measured"
  | "Champion Candidate"
  | "Champion Verified"
  | "Closed";

export type CorePlan = {
  id: string;
  schoolId: string;
  fy: string;
  baselineSSARecordId: string;
  followUpSSARecordId?: string;
  status: CorePlanStatus;
  visitsTarget: number;     // 4
  trainingsTarget: number;  // 4
  visitsCompleted: number;
  trainingsCompleted: number;
  packageCompletionPercent: number;
  /** Follow-Up SSA scheduling (set before IA uploads the follow-up). */
  followUpScheduledFor?: string;
  followUpAssignee?: string; // "myself" | partner org name
  createdById: string;
  createdByName: string;
  createdAt: string;
  updatedAt: string;
};

export type CorePlanIntervention = {
  id: string;
  corePlanId: string;
  intervention: SsaInterventionArea;
  baselineScore: number;
  priorityRank: 1 | 2 | 3 | 4;
  reason?: string;
  selectedById: string;
  selectedAt: string;
};

// ─── Core activity slots (4 visits + 4 trainings) ───────────────────

export type CoreActivityType = "visit" | "training";

export type CoreActivitySlotStatus =
  | "Not Planned"
  | "Planned"
  | "Scheduled"
  | "Assigned to Partner"
  | "Partner Scheduled"
  | "In Progress"
  | "Evidence Uploaded"
  | "Evidence Accepted"
  | "Salesforce ID Required"
  | "Awaiting IA Verification"
  | "IA Verified"
  | "Accountant Confirmed"
  | "Completed"
  | "Returned"
  | "Rejected"
  | "Rescheduled";

export type CoreSlotOwner = "unassigned" | "myself" | "staff" | "partner" | "partner_facilitator";

export type CoreActivitySlot = {
  id: string;
  corePlanId: string;
  schoolId: string;
  intervention: SsaInterventionArea;
  activityType: CoreActivityType;
  sequenceNumber: 1 | 2 | 3 | 4;
  status: CoreActivitySlotStatus;
  owner: CoreSlotOwner;
  assignedStaffId?: string;
  assignedStaffName?: string;
  assignedPartnerId?: string;
  assignedPartnerName?: string;
  activityId?: string;      // FK to the activity ledger record (set on completion)
  /** PL sign-off gate for CCEO field visits (§12): Pending until the PL
   *  verifies, then Verified. Absent for non-CCEO or partner-delivered work. */
  plVerificationStatus?: "Pending" | "Verified";
  scheduledFor?: string;    // display label "May 2026 · Wk 2"
  scheduledMonth?: string;
  scheduledWeek?: number;
  evidenceUri?: string;
  evidenceNotes?: string;
  salesforceId?: string;    // SVE-/TS-
  teachers?: number;
  leaders?: number;
  participants?: number;
  iaVerificationStatus?: "Pending" | "Verified" | "Rejected";
  accountantStatus?: "Pending" | "Confirmed";
  returnedReason?: string;
  completedAt?: string;
  createdAt: string;
  updatedAt: string;
};

// ─── Follow-up SSA + impact ─────────────────────────────────────────

export type CoreFollowUpSsa = {
  id: string;               // = followUpSSARecordId
  corePlanId: string;
  schoolId: string;
  baselineSSARecordId: string;
  fy: string;
  date: string;
  scores: CoreSsaScores;
  average: number;
  uploadedById: string;
  uploadedByName: string;
};

export type ChangeClass = "Improved" | "No Change" | "Declined" | "No Comparison";

export type InterventionChange = {
  intervention: SsaInterventionArea;
  baselineScore: number;
  followUpScore: number;
  change: number;
  classification: ChangeClass;
  priority: boolean;
};

export type CoreImpactStatus = "Improved" | "No Change" | "Declined" | "No Comparison";

export type CoreImpactSnapshot = {
  id: string;
  corePlanId: string;
  schoolId: string;
  baselineSSARecordId: string;
  followUpSSARecordId: string;
  baselineAverage: number;
  followUpAverage: number;
  averageChange: number;
  priorityInterventionChange: InterventionChange[];
  allInterventionChange: InterventionChange[];
  bestImproved?: SsaInterventionArea;
  weakestRemaining?: SsaInterventionArea;
  impactStatus: CoreImpactStatus;
  championCandidate: boolean;
  computedAt: string;
};

// ─── Constants ──────────────────────────────────────────────────────

export const CORE_SSA_THRESHOLD = 7.5;
export const VISITS_TARGET = 4;
export const TRAININGS_TARGET = 4;
export const CHAMPION_SSA_THRESHOLD = 8.0;
