// Partner mock layer.
//
// Two partners with realistic Uganda-shaped scope:
//
//   • Literacy Training Uganda  — strong delivery, healthy band,
//     mid-scale (45 schools, 3 districts), Reimbursement funding.
//   • Numeracy First            — newer partner, "Watch" band, smaller
//     scope (18 schools, 2 districts), No-Finance model.
//
// Plus 6 sample activities spread across both partners so the demo
// dashboard always renders something interesting: a verified one,
// one returned for correction, one with fraud flags, one joint-work,
// one Standard pending M&E, one CDCertification awaiting sign-off.

import type {
  Partner,
  PartnerUser,
  PartnerScope,
  PartnerActivity,
  PartnerHealthInputs,
  PartnerImpactSummary,
  JointWorkAssignment,
} from "./partner-types";
import { computePartnerHealth } from "./partner-health";
import { resolveDistrictId } from "@/lib/geography";

// ────────── Organisations ──────────

export const partners: Partner[] = [
  {
    id: "P-LIT",
    name: "Literacy Training Uganda",
    shortName: "LTU",
    category: "TrainingProvider",
    countryId: "UG",
    contractActive: true,
    edifyFocalUserId: "U-CPL-DM",
    partnerFocalUserId: "U-PA-LTU-SK",
    currentHealthBand: "Healthy",
    createdAt: "2026-01-15T10:00:00Z",
  },
  {
    id: "P-NUM",
    name: "Numeracy First",
    shortName: "NF",
    category: "TrainingProvider",
    countryId: "UG",
    contractActive: true,
    edifyFocalUserId: "U-CPL-DM",
    partnerFocalUserId: "U-PA-NF-JM",
    currentHealthBand: "Watch",
    createdAt: "2026-03-01T10:00:00Z",
  },
];

// ────────── Partner-side users (the three sub-types) ──────────

export const partnerUsers: PartnerUser[] = [
  // LTU
  { id: "U-PA-LTU-SK", partnerId: "P-LIT", email: "sarah.kanyi@ltu.org",  name: "Sarah Kanyi",  userType: "PartnerAdmin",         scopeIds: ["SC-LTU-1"], isFocal: true,  canViewFinance: true  },
  { id: "U-PFO-LTU-1", partnerId: "P-LIT", email: "abel.opio@ltu.org",     name: "Abel Opio",    userType: "PartnerFieldOfficer",  scopeIds: ["SC-LTU-1"], isFocal: false, canViewFinance: false },
  { id: "U-PFO-LTU-2", partnerId: "P-LIT", email: "ruth.amongi@ltu.org",   name: "Ruth Amongi",  userType: "PartnerFieldOfficer",  scopeIds: ["SC-LTU-1"], isFocal: false, canViewFinance: false },
  { id: "U-PV-LTU-1",  partnerId: "P-LIT", email: "donor@ltu-funder.org",  name: "LTU Donor",    userType: "PartnerViewer",        scopeIds: ["SC-LTU-1"], isFocal: false, canViewFinance: false },
  // NF
  { id: "U-PA-NF-JM",  partnerId: "P-NUM", email: "jane.muyobo@nf.org",    name: "Jane Muyobo",  userType: "PartnerAdmin",         scopeIds: ["SC-NF-1"],  isFocal: true,  canViewFinance: false },
  { id: "U-PFO-NF-1",  partnerId: "P-NUM", email: "peter.aine@nf.org",     name: "Peter Aine",   userType: "PartnerFieldOfficer",  scopeIds: ["SC-NF-1"],  isFocal: false, canViewFinance: false },
];

// ────────── Scopes ──────────

const RAW_PARTNER_SCOPES: PartnerScope[] = [
  {
    id: "SC-LTU-1",
    partnerId: "P-LIT",
    contractName: "LTU · Phonics Initiative 2026",
    contractRef: "LTU-2026-001",
    regionIds: [],
    districtIds: ["DST-KITGUM", "DST-LAMWO", "DST-GULU"],
    clusterIds: [],
    schoolIds: [], // any school in the listed districts is in-scope
    allowedActivityKinds: [
      "TeacherTraining",
      "InSchoolTraining",
      "FollowUpVisit",
      "ClassroomObservation",
    ],
    interventionAreas: ["TeachingAndLearning", "LearningEnvironment"],
    startDate: "2026-01-01",
    endDate:   "2026-12-31",
    expectedSchoolReach: 45,
    expectedTeacherReach: 400,
    expectedActivitiesPerMonth: 12,
    reportingFrequencyDays: 7,
    evidenceRequirements: [
      { kind: "AttendanceSheet",   required: true },
      { kind: "Photos",            required: true },
      { kind: "TrainingReport",    required: true },
      { kind: "PrePostAssessment", required: false },
    ],
    defaultVerificationLevel: "Standard",
    edifyFocalUserId: "U-CPL-DM",
    partnerFocalUserId: "U-PA-LTU-SK",
    fundingModel: "Reimbursement",
    status: "Active",
  },
  {
    id: "SC-NF-1",
    partnerId: "P-NUM",
    contractName: "Numeracy First · Mid-Year Pilot",
    contractRef: "NF-2026-Q2",
    regionIds: [],
    districtIds: ["DST-MBALE", "DST-SIRONKO"],
    clusterIds: [],
    schoolIds: [],
    allowedActivityKinds: ["TeacherTraining", "FollowUpVisit", "CoachingSession"],
    interventionAreas: ["TeachingAndLearning", "AssessmentAndDataUse"],
    startDate: "2026-03-01",
    endDate:   "2026-09-30",
    expectedSchoolReach: 18,
    expectedTeacherReach: 150,
    expectedActivitiesPerMonth: 6,
    reportingFrequencyDays: 7,
    evidenceRequirements: [
      { kind: "AttendanceSheet", required: true },
      { kind: "Photos",          required: true },
      { kind: "TrainingReport",  required: true },
    ],
    defaultVerificationLevel: "Standard",
    edifyFocalUserId: "U-CPL-DM",
    partnerFocalUserId: "U-PA-NF-JM",
    fundingModel: "NoFinance",
    status: "Active",
  },
];

// Normalise scope district ids onto the canonical `UG-D-*` scheme. Legacy
// `DST-*` codes resolve via the geography alias table.
export const partnerScopes: PartnerScope[] = RAW_PARTNER_SCOPES.map((s) => ({
  ...s,
  districtIds: s.districtIds.map(resolveDistrictId),
}));

// ────────── Activities ──────────

const RAW_PARTNER_ACTIVITIES: PartnerActivity[] = [
  {
    id: "PA-LTU-001",
    partnerId: "P-LIT", scopeId: "SC-LTU-1",
    title: "Phonics Training · Grade 3 teachers",
    kind: "TeacherTraining", intervention: "TeachingAndLearning",
    schoolId: "SCH-LTU-001", schoolName: "Hope Primary School", districtId: "DST-KITGUM",
    scheduledDate: "2026-05-12", completedDate: "2026-05-12",
    participants: { teachers: 16, learners: 0 },
    status: "Completed",
    verificationStatus: "Counted",
    verificationLevel: "Standard",
    evidence: [
      { id: "EV-1", activityId: "PA-LTU-001", kind: "AttendanceSheet", url: "/uploads/att-001.pdf", uploadedByUserId: "U-PFO-LTU-1", uploadedAt: "2026-05-12T16:30:00Z", reviewStatus: "Accepted", replacementHistory: [] },
      { id: "EV-2", activityId: "PA-LTU-001", kind: "Photos",          url: "/uploads/ph-001.jpg",  uploadedByUserId: "U-PFO-LTU-1", uploadedAt: "2026-05-12T16:32:00Z", reviewStatus: "Accepted", replacementHistory: [] },
      { id: "EV-3", activityId: "PA-LTU-001", kind: "TrainingReport",  url: "/uploads/rep-001.pdf", uploadedByUserId: "U-PFO-LTU-1", uploadedAt: "2026-05-12T17:00:00Z", reviewStatus: "Accepted", replacementHistory: [] },
    ],
    fraudFlags: [],
    salesforceMatchStatus: "SmartMatch",
    followUpRequested: { kind: "CceoFollowUpVisit", reason: "Teachers requested more support on blending words.", byDate: "2026-05-26" },
    comments: [
      { id: "C-1", activityId: "PA-LTU-001", authorUserId: "U-PFO-LTU-1", authorName: "Abel Opio",   authorRole: "Partner Trainer", body: "Attendance sheet uploaded.",                                visibility: "PartnerVisible", createdAt: "2026-05-12T16:32:00Z" },
      { id: "C-2", activityId: "PA-LTU-001", authorUserId: "U-CCEO-PC",   authorName: "Paul Chinyama", authorRole: "CCEO",            body: "I confirm the training happened. Teachers asked for more blending practice.", visibility: "PartnerVisible", createdAt: "2026-05-13T08:14:00Z" },
      { id: "C-3", activityId: "PA-LTU-001", authorUserId: "U-IA-GA",     authorName: "Grace Alimo",   authorRole: "M&E",             body: "Verified and counted.",                                    visibility: "PartnerVisible", createdAt: "2026-05-14T11:30:00Z" },
    ],
    createdAt: "2026-05-10T10:00:00Z", createdById: "U-PA-LTU-SK", updatedAt: "2026-05-14T11:30:00Z",
  },
  {
    id: "PA-LTU-002",
    partnerId: "P-LIT", scopeId: "SC-LTU-1",
    title: "Phonics Training · Bright Future PS",
    kind: "TeacherTraining", intervention: "TeachingAndLearning",
    schoolId: "SCH-LTU-002", schoolName: "Bright Future Primary School", districtId: "DST-KITGUM",
    scheduledDate: "2026-05-16", completedDate: "2026-05-16",
    participants: { teachers: 14 },
    status: "Completed",
    verificationStatus: "ReturnedForCorrection",
    verificationLevel: "Standard",
    evidence: [
      { id: "EV-4", activityId: "PA-LTU-002", kind: "AttendanceSheet", url: "/uploads/att-002.pdf", uploadedByUserId: "U-PFO-LTU-1", uploadedAt: "2026-05-16T17:00:00Z", reviewStatus: "Accepted",            replacementHistory: [] },
      { id: "EV-5", activityId: "PA-LTU-002", kind: "Photos",          url: "/uploads/ph-002.jpg",  uploadedByUserId: "U-PFO-LTU-1", uploadedAt: "2026-05-16T17:02:00Z", reviewStatus: "Accepted",            replacementHistory: [] },
      // TrainingReport missing → ReturnedForCorrection
    ],
    fraudFlags: [],
    salesforceMatchStatus: "PossibleMatch",
    comments: [
      { id: "C-4", activityId: "PA-LTU-002", authorUserId: "U-IA-GA", authorName: "Grace Alimo", authorRole: "M&E", body: "Please upload the training report — it's required for verification.", visibility: "PartnerVisible", createdAt: "2026-05-17T09:00:00Z" },
      { id: "C-5", activityId: "PA-LTU-002", authorUserId: "U-CPL-DM", authorName: "Daniel Mwangi", authorRole: "CPL", body: "LTU has missed the report on 3 of their last 8 activities. Flag for partner-review meeting.", visibility: "InternalOnly", createdAt: "2026-05-17T10:00:00Z" },
    ],
    createdAt: "2026-05-15T10:00:00Z", createdById: "U-PA-LTU-SK", updatedAt: "2026-05-17T09:00:00Z",
  },
  {
    id: "PA-LTU-003",
    partnerId: "P-LIT", scopeId: "SC-LTU-1",
    title: "Follow-Up Visit · Hope Primary",
    kind: "FollowUpVisit", intervention: "TeachingAndLearning",
    schoolId: "SCH-LTU-001", schoolName: "Hope Primary School", districtId: "DST-KITGUM",
    scheduledDate: "2026-05-26",
    status: "Scheduled",
    verificationStatus: "EvidenceMissing",
    verificationLevel: "JointConfirmation",
    evidence: [],
    fraudFlags: [],
    jointWorkId: "JW-LTU-1",
    comments: [],
    createdAt: "2026-05-14T12:00:00Z", createdById: "U-PA-LTU-SK", updatedAt: "2026-05-14T12:00:00Z",
  },
  {
    id: "PA-LTU-004",
    partnerId: "P-LIT", scopeId: "SC-LTU-1",
    title: "In-School Training · Sunrise School",
    kind: "InSchoolTraining", intervention: "TeachingAndLearning",
    schoolId: "SCH-LTU-007", schoolName: "Sunrise School", districtId: "DST-GULU",
    scheduledDate: "2026-05-18", completedDate: "2026-05-18",
    participants: { teachers: 12 },
    status: "Completed",
    verificationStatus: "UnderReview",
    verificationLevel: "SpotCheck",
    evidence: [
      { id: "EV-6", activityId: "PA-LTU-004", kind: "AttendanceSheet", url: "/uploads/att-004.pdf", uploadedByUserId: "U-PFO-LTU-2", uploadedAt: "2026-05-18T16:30:00Z", reviewStatus: "Pending", replacementHistory: [] },
      { id: "EV-7", activityId: "PA-LTU-004", kind: "Photos",          url: "/uploads/ph-004.jpg",  uploadedByUserId: "U-PFO-LTU-2", uploadedAt: "2026-05-18T16:32:00Z", reviewStatus: "Pending", replacementHistory: [] },
      { id: "EV-8", activityId: "PA-LTU-004", kind: "TrainingReport",  url: "/uploads/rep-004.pdf", uploadedByUserId: "U-PFO-LTU-2", uploadedAt: "2026-05-18T17:00:00Z", reviewStatus: "Pending", replacementHistory: [] },
    ],
    // The attendance sheet hash matches a previous activity in the partner-fraud detector — flagged for review.
    fraudFlags: ["DuplicateAttendanceSheet"],
    salesforceMatchStatus: "PossibleMatch",
    comments: [],
    createdAt: "2026-05-17T10:00:00Z", createdById: "U-PA-LTU-SK", updatedAt: "2026-05-18T17:00:00Z",
  },
  {
    id: "PA-NF-001",
    partnerId: "P-NUM", scopeId: "SC-NF-1",
    title: "Number-Sense Training · Mbale Central",
    kind: "TeacherTraining", intervention: "TeachingAndLearning",
    schoolId: "SCH-NF-001", schoolName: "Mbale Central PS", districtId: "DST-MBALE",
    scheduledDate: "2026-05-20",
    status: "Scheduled",
    verificationStatus: "EvidenceMissing",
    verificationLevel: "Standard",
    evidence: [],
    fraudFlags: [],
    comments: [],
    createdAt: "2026-05-13T10:00:00Z", createdById: "U-PA-NF-JM", updatedAt: "2026-05-13T10:00:00Z",
  },
  {
    id: "PA-NF-002",
    partnerId: "P-NUM", scopeId: "SC-NF-1",
    title: "Coaching Session · Mbale Riverside",
    kind: "CoachingSession", intervention: "TeachingAndLearning",
    schoolId: "SCH-NF-002", schoolName: "Mbale Riverside PS", districtId: "DST-MBALE",
    scheduledDate: "2026-05-22",
    status: "Submitted",
    verificationStatus: "UnderReview",
    verificationLevel: "CDCertification",
    evidence: [
      { id: "EV-9",  activityId: "PA-NF-002", kind: "CoachingNotes", url: "/uploads/cn-002.pdf", uploadedByUserId: "U-PFO-NF-1", uploadedAt: "2026-05-22T16:00:00Z", reviewStatus: "Accepted", replacementHistory: [] },
      { id: "EV-10", activityId: "PA-NF-002", kind: "Photos",        url: "/uploads/ph-nf-002.jpg", uploadedByUserId: "U-PFO-NF-1", uploadedAt: "2026-05-22T16:02:00Z", reviewStatus: "Accepted", replacementHistory: [] },
    ],
    fraudFlags: [],
    comments: [
      { id: "C-NF-1", activityId: "PA-NF-002", authorUserId: "U-IA-GA", authorName: "Grace Alimo", authorRole: "M&E", body: "Cleared. Waiting on CD certification.", visibility: "PartnerVisible", createdAt: "2026-05-23T10:00:00Z" },
    ],
    createdAt: "2026-05-21T10:00:00Z", createdById: "U-PA-NF-JM", updatedAt: "2026-05-23T10:00:00Z",
  },
];

// Normalise activity district ids onto the canonical `UG-D-*` scheme.
export const partnerActivities: PartnerActivity[] = RAW_PARTNER_ACTIVITIES.map((a) => ({
  ...a,
  districtId: a.districtId ? resolveDistrictId(a.districtId) : a.districtId,
}));

// ────────── Joint work assignment ──────────

export const jointWorks: JointWorkAssignment[] = [
  {
    id: "JW-LTU-1",
    activityId: "PA-LTU-003",
    lead: "Partner",
    edifyAssignments: [{ userId: "U-CCEO-PC", userName: "Paul Chinyama", role: "Observer" }],
    partnerAssignments: [{ userId: "U-PFO-LTU-1", userName: "Abel Opio",  role: "Lead" }],
    responsibilityOwnerUserId: "U-PFO-LTU-1",
    nextActionOwnerUserId:     "U-CCEO-PC",
    sharedChecklist: [
      { id: "ck-1", label: "Confirm school received prep brief", done: true,  doneByUserId: "U-PFO-LTU-1" },
      { id: "ck-2", label: "Observe phonics lesson on the day", done: false },
      { id: "ck-3", label: "Submit joint debrief",              done: false },
    ],
  },
];

// ────────── Health snapshots (current period) ──────────

const HEALTH_INPUTS: PartnerHealthInputs[] = [
  {
    partnerId: "P-LIT", periodIso: "2026-05",
    verificationPassRatePct: 78, evidenceQualityScore: 80,
    timelinessScore: 70, schoolImprovementScore: 75,
    staffCollaborationScore: 78, reportingAccuracyScore: 80,
    overduePenalty: 12, returnedCorrectionPenalty: 10,
  },
  {
    partnerId: "P-NUM", periodIso: "2026-05",
    verificationPassRatePct: 55, evidenceQualityScore: 60,
    timelinessScore: 50, schoolImprovementScore: 45,
    staffCollaborationScore: 55, reportingAccuracyScore: 60,
    overduePenalty: 30, returnedCorrectionPenalty: 20,
  },
];

export const partnerHealthSnapshots = HEALTH_INPUTS.map((i) => computePartnerHealth(i));

// ────────── Impact summaries ──────────

export const partnerImpacts: PartnerImpactSummary[] = [
  {
    partnerId: "P-LIT", periodIso: "2026-05",
    schoolsSupported: 38, verifiedActivities: 24, teachersTrained: 312,
    followUpsCompleted: 17, meanSsaDelta: 0.6,
    schoolsImprovedFromCriticalToAtRisk: 6,
    schoolsImprovedFromAtRiskToOnTrack:  3,
    costPerImprovedSchoolUgx: 1_450_000,
  },
  {
    partnerId: "P-NUM", periodIso: "2026-05",
    schoolsSupported: 14, verifiedActivities: 9, teachersTrained: 96,
    followUpsCompleted: 4, meanSsaDelta: 0.2,
    schoolsImprovedFromCriticalToAtRisk: 1,
    schoolsImprovedFromAtRiskToOnTrack:  0,
  },
];

// ────────── Convenience lookups ──────────

export function partnerById(partnerId: string): Partner | undefined {
  return partners.find((p) => p.id === partnerId);
}

export function scopesForPartner(partnerId: string): PartnerScope[] {
  return partnerScopes.filter((s) => s.partnerId === partnerId);
}

export function activitiesForPartner(partnerId: string): PartnerActivity[] {
  return partnerActivities.filter((a) => a.partnerId === partnerId);
}

export function activitiesAtSchool(schoolId: string): PartnerActivity[] {
  return partnerActivities.filter((a) => a.schoolId === schoolId);
}

export function partnerUserByEmail(email: string): PartnerUser | undefined {
  return partnerUsers.find((u) => u.email.toLowerCase() === email.toLowerCase());
}

export function partnerHealthFor(partnerId: string) {
  return partnerHealthSnapshots.find((h) => h.partnerId === partnerId);
}

export function partnerImpactFor(partnerId: string) {
  return partnerImpacts.find((i) => i.partnerId === partnerId);
}
