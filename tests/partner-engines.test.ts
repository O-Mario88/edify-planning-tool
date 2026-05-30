import { describe, it, expect } from "vitest";
import {
  canPartnerAct,
  partnerCoverageGaps,
  partnerVisibleSchoolIds,
  mergedAllowedActivityKinds,
} from "@/lib/partner/partner-scope";
import {
  computeVerificationStatus,
  missingRequiredEvidence,
  shouldCountTowardTargets,
  verificationLevelRequired,
} from "@/lib/partner/partner-verification";
import {
  bandForScore,
  computePartnerHealth,
} from "@/lib/partner/partner-health";
import { detectFraudFlags } from "@/lib/partner/partner-fraud";
import {
  checklistProgress,
  responsibilityOwner,
  validateJointWork,
} from "@/lib/partner/partner-joint-work";
import type {
  PartnerActivity,
  PartnerScope,
  PartnerEvidence,
  JointWorkAssignment,
} from "@/lib/partner/partner-types";

// Partner engines are even more load-bearing than the FWI: they
// enforce both the security boundary (Scope) AND the counting rules
// (Verification). A bug here lets fake partner data flow into national
// targets. Tests below pin every rule.

// ─────────── Fixtures ───────────

function scope(over: Partial<PartnerScope> = {}): PartnerScope {
  return {
    id: "SC-1",
    partnerId: "P-1",
    contractName: "Literacy Training Uganda — 2026",
    regionIds: [],
    districtIds: ["DST-KITGUM", "DST-LAMWO", "DST-GULU"],
    clusterIds: [],
    schoolIds: [],
    allowedActivityKinds: ["TeacherTraining", "InSchoolTraining", "FollowUpVisit", "ClassroomObservation"],
    interventionAreas: ["TeachingAndLearning", "LearningEnvironment"],
    startDate: "2026-01-01",
    endDate:   "2026-12-31",
    expectedSchoolReach: 45,
    expectedTeacherReach: 400,
    expectedActivitiesPerMonth: 12,
    reportingFrequencyDays: 7,
    evidenceRequirements: [
      { kind: "AttendanceSheet", required: true },
      { kind: "Photos",          required: true },
      { kind: "TrainingReport",  required: true },
      { kind: "PrePostAssessment", required: false },
    ],
    defaultVerificationLevel: "Standard",
    edifyFocalUserId: "U-CPL-DM",
    partnerFocalUserId: "U-PA-SK",
    fundingModel: "Reimbursement",
    status: "Active",
    ...over,
  };
}

function activity(over: Partial<PartnerActivity> = {}): PartnerActivity {
  return {
    id: "PA-1",
    partnerId: "P-1",
    scopeId: "SC-1",
    title: "Phonics Training · Grade 3 teachers",
    kind: "TeacherTraining",
    intervention: "TeachingAndLearning",
    schoolId: "SCH-1",
    schoolName: "Hope Primary School",
    districtId: "DST-KITGUM",
    scheduledDate: "2026-05-15",
    status: "Submitted",
    verificationStatus: "EvidenceMissing",
    verificationLevel: "Standard",
    evidence: [],
    fraudFlags: [],
    comments: [],
    createdAt: "2026-05-15T08:00:00Z",
    createdById: "U-PT-1",
    updatedAt: "2026-05-15T08:00:00Z",
    ...over,
  };
}

function evidence(kind: PartnerEvidence["kind"], id: string): PartnerEvidence {
  return {
    id,
    activityId: "PA-1",
    kind,
    url: `/uploads/${id}.png`,
    uploadedByUserId: "U-PT-1",
    uploadedAt: "2026-05-15T09:00:00Z",
    reviewStatus: "Pending",
    replacementHistory: [],
  };
}

// ────────────────── Scope Engine ──────────────────

describe("canPartnerAct — happy path", () => {
  it("allows an in-scope district + allowed kind inside the contract window", () => {
    const r = canPartnerAct({
      scope: scope(),
      schoolId: "SCH-1",
      schoolDistrictId: "DST-KITGUM",
      activityKind: "TeacherTraining",
      intervention: "TeachingAndLearning",
      scheduledDate: "2026-06-01",
    });
    expect(r.ok).toBe(true);
  });
});

describe("canPartnerAct — security boundary rules", () => {
  it("rejects when scope is Paused", () => {
    const r = canPartnerAct({
      scope: scope({ status: "Paused" }),
      schoolId: "SCH-1", schoolDistrictId: "DST-KITGUM",
      activityKind: "TeacherTraining", scheduledDate: "2026-06-01",
    });
    expect(r.ok).toBe(false);
    expect(r.ok === false && r.ruleId).toBe("scope-inactive");
  });

  it("rejects activities before the contract start date", () => {
    const r = canPartnerAct({
      scope: scope(),
      schoolId: "SCH-1", schoolDistrictId: "DST-KITGUM",
      activityKind: "TeacherTraining", scheduledDate: "2025-12-15",
    });
    expect(r.ok).toBe(false);
    expect(r.ok === false && r.ruleId).toBe("before-start");
  });

  it("rejects activities after the contract end date", () => {
    const r = canPartnerAct({
      scope: scope(),
      schoolId: "SCH-1", schoolDistrictId: "DST-KITGUM",
      activityKind: "TeacherTraining", scheduledDate: "2027-01-15",
    });
    expect(r.ok).toBe(false);
    expect(r.ok === false && r.ruleId).toBe("after-end");
  });

  it("rejects districts outside scope when no explicit schoolIds are listed", () => {
    const r = canPartnerAct({
      scope: scope(),
      schoolId: "SCH-9", schoolDistrictId: "DST-MBALE",
      activityKind: "TeacherTraining", scheduledDate: "2026-06-01",
    });
    expect(r.ok).toBe(false);
    expect(r.ok === false && r.ruleId).toBe("district-out-of-scope");
  });

  it("rejects schools not in the explicit schoolIds list when that list is set", () => {
    const r = canPartnerAct({
      scope: scope({ schoolIds: ["SCH-1", "SCH-2"] }),
      schoolId: "SCH-99", schoolDistrictId: "DST-KITGUM",
      activityKind: "TeacherTraining", scheduledDate: "2026-06-01",
    });
    expect(r.ok).toBe(false);
    expect(r.ok === false && r.ruleId).toBe("school-not-assigned");
  });

  it("rejects activity kinds not in the allowed list", () => {
    const r = canPartnerAct({
      scope: scope(),
      schoolId: "SCH-1", schoolDistrictId: "DST-KITGUM",
      activityKind: "ResourceDelivery", scheduledDate: "2026-06-01",
    });
    expect(r.ok).toBe(false);
    expect(r.ok === false && r.ruleId).toBe("activity-not-allowed");
  });

  it("rejects intervention areas outside the scope's focus when specified", () => {
    const r = canPartnerAct({
      scope: scope(),
      schoolId: "SCH-1", schoolDistrictId: "DST-KITGUM",
      activityKind: "TeacherTraining",
      intervention: "AssessmentAndDataUse",
      scheduledDate: "2026-06-01",
    });
    expect(r.ok).toBe(false);
    expect(r.ok === false && r.ruleId).toBe("intervention-out-of-scope");
  });

  it("rejects scopes with no geographic boundaries at all (defensive)", () => {
    const r = canPartnerAct({
      scope: scope({ districtIds: [], clusterIds: [], schoolIds: [] }),
      schoolId: "SCH-1", schoolDistrictId: "DST-KITGUM",
      activityKind: "TeacherTraining", scheduledDate: "2026-06-01",
    });
    expect(r.ok).toBe(false);
  });
});

describe("partnerVisibleSchoolIds — multi-mode resolution", () => {
  const schools = [
    { id: "S1", districtId: "DST-KITGUM", clusterId: "CL-A" },
    { id: "S2", districtId: "DST-KITGUM", clusterId: "CL-B" },
    { id: "S3", districtId: "DST-LAMWO",  clusterId: "CL-C" },
    { id: "S4", districtId: "DST-MBALE",  clusterId: "CL-D" },
  ];

  it("returns the explicit list when schoolIds are set (fast path)", () => {
    expect(partnerVisibleSchoolIds(scope({ schoolIds: ["S1", "S4"] }), schools)).toEqual(["S1", "S4"]);
  });

  it("filters by cluster when schoolIds is empty + clusterIds is set", () => {
    expect(partnerVisibleSchoolIds(scope({ schoolIds: [], clusterIds: ["CL-A", "CL-C"] }), schools))
      .toEqual(["S1", "S3"]);
  });

  it("falls back to district filtering when only districtIds is set", () => {
    expect(partnerVisibleSchoolIds(scope({ schoolIds: [], clusterIds: [], districtIds: ["DST-KITGUM"] }), schools))
      .toEqual(["S1", "S2"]);
  });

  it("returns empty when no geographic scope is defined (safe default)", () => {
    expect(partnerVisibleSchoolIds(scope({ schoolIds: [], clusterIds: [], districtIds: [] }), schools)).toEqual([]);
  });
});

describe("mergedAllowedActivityKinds", () => {
  it("unions activity kinds across multiple scopes", () => {
    const merged = mergedAllowedActivityKinds([
      scope({ allowedActivityKinds: ["TeacherTraining", "FollowUpVisit"] }),
      scope({ allowedActivityKinds: ["FollowUpVisit", "CoachingSession"] }),
    ]);
    expect(new Set(merged)).toEqual(new Set(["TeacherTraining", "FollowUpVisit", "CoachingSession"]));
  });
});

describe("partnerCoverageGaps", () => {
  it("flags schools with no partner activity in the window", () => {
    const now = Date.now();
    const recent = new Date(now - 5 * 24 * 60 * 60 * 1000).toISOString();
    const old    = new Date(now - 60 * 24 * 60 * 60 * 1000).toISOString();
    const gaps = partnerCoverageGaps({
      scope: scope(),
      schoolsInScope: [
        { id: "S1", name: "Hope PS",     lastPartnerActivityAt: recent },
        { id: "S2", name: "Sunrise PS",  lastPartnerActivityAt: old    },
        { id: "S3", name: "Bright PS",   /* never visited */ },
      ],
    });
    expect(gaps.map((g) => g.schoolId).sort()).toEqual(["S2", "S3"]);
    expect(gaps.find((g) => g.schoolId === "S3")?.daysSinceLastActivity).toBeNull();
  });
});

// ────────────────── Verification Engine ──────────────────

describe("verificationLevelRequired — never downgrade", () => {
  it("defaults to the scope-level value when activity has no overrides", () => {
    expect(
      verificationLevelRequired(
        { verificationLevel: "Standard", fraudFlags: [], jointWorkId: undefined },
        scope(),
      ),
    ).toBe("Standard");
  });

  it("upgrades to JointConfirmation when joint-work record exists", () => {
    expect(
      verificationLevelRequired(
        { verificationLevel: "Standard", fraudFlags: [], jointWorkId: "JW-1" },
        scope(),
      ),
    ).toBe("JointConfirmation");
  });

  it("upgrades to SpotCheck when fraud flags are present", () => {
    expect(
      verificationLevelRequired(
        { verificationLevel: "Standard", fraudFlags: ["DuplicateSchoolDateActivity"], jointWorkId: undefined },
        scope(),
      ),
    ).toBe("SpotCheck");
  });

  it("preserves CDCertification when fraud also fires (higher rank wins)", () => {
    expect(
      verificationLevelRequired(
        { verificationLevel: "CDCertification", fraudFlags: ["GPSMismatch"], jointWorkId: undefined },
        scope(),
      ),
    ).toBe("CDCertification");
  });
});

describe("missingRequiredEvidence", () => {
  it("returns required evidence kinds that aren't attached", () => {
    const missing = missingRequiredEvidence(activity({ evidence: [evidence("AttendanceSheet", "E1")] }), scope());
    expect(missing.map((r) => r.kind).sort()).toEqual(["Photos", "TrainingReport"]);
  });

  it("returns empty when all required kinds are present", () => {
    const missing = missingRequiredEvidence(
      activity({
        evidence: [
          evidence("AttendanceSheet", "E1"),
          evidence("Photos",          "E2"),
          evidence("TrainingReport",  "E3"),
        ],
      }),
      scope(),
    );
    expect(missing).toEqual([]);
  });
});

describe("computeVerificationStatus — verification pipeline", () => {
  const fullEvidence = [
    evidence("AttendanceSheet", "E1"),
    evidence("Photos",          "E2"),
    evidence("TrainingReport",  "E3"),
  ];

  it("EvidenceMissing while status is not yet Completed", () => {
    expect(computeVerificationStatus(
      activity({ status: "Submitted", evidence: fullEvidence }),
      scope(),
      { meReviewComplete: false, meReviewValid: false, staffConfirmed: false, cdCertified: false, auditRequired: false, returnedForCorrection: false },
    )).toBe("EvidenceMissing");
  });

  it("AuditRequired always wins over other states", () => {
    expect(computeVerificationStatus(
      activity({ status: "Completed", evidence: fullEvidence }),
      scope(),
      { meReviewComplete: true, meReviewValid: true, staffConfirmed: true, cdCertified: true, auditRequired: true, returnedForCorrection: false },
    )).toBe("AuditRequired");
  });

  it("ReturnedForCorrection takes precedence over Verified when both possible", () => {
    expect(computeVerificationStatus(
      activity({ status: "Completed", evidence: fullEvidence }),
      scope(),
      { meReviewComplete: true, meReviewValid: false, staffConfirmed: false, cdCertified: false, auditRequired: false, returnedForCorrection: true },
    )).toBe("ReturnedForCorrection");
  });

  it("EvidenceMissing when a required artefact is absent even post-Completed", () => {
    expect(computeVerificationStatus(
      activity({ status: "Completed", evidence: [evidence("Photos", "E2")] }),
      scope(),
      { meReviewComplete: true, meReviewValid: true, staffConfirmed: false, cdCertified: false, auditRequired: false, returnedForCorrection: false },
    )).toBe("EvidenceMissing");
  });

  it("Standard verifies when M&E reviewed-valid", () => {
    expect(computeVerificationStatus(
      activity({ status: "Completed", evidence: fullEvidence }),
      scope(),
      { meReviewComplete: true, meReviewValid: true, staffConfirmed: false, cdCertified: false, auditRequired: false, returnedForCorrection: false },
    )).toBe("Verified");
  });

  it("JointConfirmation requires BOTH M&E + staff confirmation", () => {
    const base = activity({ status: "Completed", evidence: fullEvidence, jointWorkId: "JW-1" });
    expect(computeVerificationStatus(
      base, scope(),
      { meReviewComplete: true, meReviewValid: true, staffConfirmed: false, cdCertified: false, auditRequired: false, returnedForCorrection: false },
    )).toBe("UnderReview");
    expect(computeVerificationStatus(
      base, scope(),
      { meReviewComplete: true, meReviewValid: true, staffConfirmed: true,  cdCertified: false, auditRequired: false, returnedForCorrection: false },
    )).toBe("Verified");
  });

  it("CDCertification holds at UnderReview until the CD signs off", () => {
    const base = activity({ status: "Completed", evidence: fullEvidence, verificationLevel: "CDCertification" });
    expect(computeVerificationStatus(
      base, scope(),
      { meReviewComplete: true, meReviewValid: true, staffConfirmed: true, cdCertified: false, auditRequired: false, returnedForCorrection: false },
    )).toBe("UnderReview");
    expect(computeVerificationStatus(
      base, scope(),
      { meReviewComplete: true, meReviewValid: true, staffConfirmed: true, cdCertified: true,  auditRequired: false, returnedForCorrection: false },
    )).toBe("Verified");
  });
});

describe("shouldCountTowardTargets — the strict gate", () => {
  function complete(over: Partial<PartnerActivity> = {}): PartnerActivity {
    return activity({
      status: "Completed",
      verificationStatus: "Verified",
      salesforceMatchStatus: "Verified",
      ...over,
    });
  }

  it("counts a fully-cleared activity", () => {
    expect(shouldCountTowardTargets(complete())).toBe(true);
  });

  it("does not count incomplete activities even if 'Verified'", () => {
    expect(shouldCountTowardTargets(complete({ status: "Submitted" }))).toBe(false);
  });

  it("does not count when verification is not Verified/Counted", () => {
    expect(shouldCountTowardTargets(complete({ verificationStatus: "UnderReview" }))).toBe(false);
    expect(shouldCountTowardTargets(complete({ verificationStatus: "ReturnedForCorrection" }))).toBe(false);
  });

  it("does not count when fraud flags are present", () => {
    expect(shouldCountTowardTargets(complete({ fraudFlags: ["DuplicateAttendanceSheet"] }))).toBe(false);
  });

  it("does not count when Salesforce match is NoMatch / PossibleMatch", () => {
    expect(shouldCountTowardTargets(complete({ salesforceMatchStatus: "NoMatch" }))).toBe(false);
    expect(shouldCountTowardTargets(complete({ salesforceMatchStatus: "PossibleMatch" }))).toBe(false);
  });
});

// ────────────────── Health Score ──────────────────

describe("partner health — band thresholds", () => {
  it("maps numbers to bands the way leadership reads them", () => {
    expect(bandForScore(95)).toBe("Excellent");
    expect(bandForScore(85)).toBe("Excellent");
    expect(bandForScore(84)).toBe("Healthy");
    expect(bandForScore(70)).toBe("Healthy");
    expect(bandForScore(69)).toBe("Watch");
    expect(bandForScore(50)).toBe("Watch");
    expect(bandForScore(49)).toBe("AtRisk");
    expect(bandForScore(1)).toBe("AtRisk");
    expect(bandForScore(0)).toBe("Suspended");
  });
});

describe("computePartnerHealth", () => {
  it("a strong partner lands in Excellent", () => {
    const r = computePartnerHealth({
      partnerId: "P-1", periodIso: "2026-05",
      verificationPassRatePct: 95, evidenceQualityScore: 90,
      timelinessScore: 90, schoolImprovementScore: 88,
      staffCollaborationScore: 85, reportingAccuracyScore: 92,
      overduePenalty: 0, returnedCorrectionPenalty: 0,
    });
    expect(r.band).toBe("Excellent");
    expect(r.score).toBeGreaterThanOrEqual(85);
  });

  it("penalties pull a strong partner down toward Watch / AtRisk", () => {
    const r = computePartnerHealth({
      partnerId: "P-1", periodIso: "2026-05",
      verificationPassRatePct: 80, evidenceQualityScore: 75,
      timelinessScore: 60, schoolImprovementScore: 70,
      staffCollaborationScore: 60, reportingAccuracyScore: 70,
      overduePenalty: 80, returnedCorrectionPenalty: 70,
    });
    expect(r.band === "Watch" || r.band === "AtRisk").toBe(true);
  });

  it("score floors at 0 (band Suspended is reachable)", () => {
    const r = computePartnerHealth({
      partnerId: "P-1", periodIso: "2026-05",
      verificationPassRatePct: 0, evidenceQualityScore: 0,
      timelinessScore: 0, schoolImprovementScore: 0,
      staffCollaborationScore: 0, reportingAccuracyScore: 0,
      overduePenalty: 100, returnedCorrectionPenalty: 100,
    });
    expect(r.score).toBe(0);
    expect(r.band).toBe("Suspended");
  });

  it("breakdown sums (positive - negative) to the displayed score", () => {
    const r = computePartnerHealth({
      partnerId: "P-1", periodIso: "2026-05",
      verificationPassRatePct: 80, evidenceQualityScore: 70,
      timelinessScore: 70, schoolImprovementScore: 75,
      staffCollaborationScore: 60, reportingAccuracyScore: 80,
      overduePenalty: 20, returnedCorrectionPenalty: 10,
    });
    const b = r.breakdown;
    const expected = Math.round(
      b.verifiedDelivery + b.evidenceQuality + b.timeliness +
      b.schoolImprovement + b.staffCollaboration + b.reportingAccuracy -
      b.overduePenalty - b.returnedCorrectionPenalty,
    );
    expect(Math.abs(expected - r.score)).toBeLessThanOrEqual(1);
  });
});

// ────────────────── Fraud Detection ──────────────────

describe("detectFraudFlags — 10 rules", () => {
  function ctx(over: Parameters<typeof detectFraudFlags>[1] | object = {}): Parameters<typeof detectFraudFlags>[1] {
    return {
      recentPartnerActivities: [],
      scope: scope(),
      schoolDistrictId: "DST-KITGUM",
      partnerAttendanceSheetHashes: [],
      photoHashes: [],
      partnerHistoricalPhotoHashes: [],
      ...over,
    } as Parameters<typeof detectFraudFlags>[1];
  }

  it("OutsideScope when scope check fails", () => {
    expect(detectFraudFlags(activity({ kind: "ResourceDelivery" }), ctx())).toContain("OutsideScope");
  });

  it("MissingSchoolAssignment when schoolId is blank", () => {
    expect(detectFraudFlags(activity({ schoolId: "" }), ctx())).toContain("MissingSchoolAssignment");
  });

  it("AfterContractEnd when scheduled past end date", () => {
    expect(detectFraudFlags(activity({ scheduledDate: "2027-01-15" }), ctx())).toContain("AfterContractEnd");
  });

  it("EditAfterVerified when context flag set", () => {
    expect(detectFraudFlags(activity(), ctx({ isEditingVerifiedRecord: true } as object)))
      .toContain("EditAfterVerified");
  });

  it("DuplicateSchoolDateActivity when another activity matches school+kind+day", () => {
    const dup = activity({ id: "PA-OTHER" });
    expect(detectFraudFlags(activity(), ctx({ recentPartnerActivities: [dup] } as object)))
      .toContain("DuplicateSchoolDateActivity");
  });

  it("DuplicateAttendanceSheet when the sheet hash was used before", () => {
    expect(detectFraudFlags(activity(), ctx({
      attendanceSheetHash: "sha-aaa",
      partnerAttendanceSheetHashes: ["sha-aaa", "sha-bbb"],
    } as object))).toContain("DuplicateAttendanceSheet");
  });

  it("ReusedPhoto when any uploaded photo hash matches history", () => {
    expect(detectFraudFlags(activity(), ctx({
      photoHashes: ["pic-1", "pic-2"],
      partnerHistoricalPhotoHashes: ["pic-2"],
    } as object))).toContain("ReusedPhoto");
  });

  it("GPSMismatch when submission GPS is >2km from school GPS", () => {
    expect(detectFraudFlags(activity(), ctx({
      submittedGpsLat: 0.0, submittedGpsLng: 0.0,
      schoolGpsLat:    3.0, schoolGpsLng:    32.5,
    } as object))).toContain("GPSMismatch");
  });

  it("UnrealisticParticipantCount when teachers > 200", () => {
    expect(detectFraudFlags(activity({ participants: { teachers: 300 } }), ctx()))
      .toContain("UnrealisticParticipantCount");
  });

  it("FollowUpBeforeOriginal when no earlier training exists for the school", () => {
    expect(detectFraudFlags(
      activity({ kind: "FollowUpVisit" }),
      ctx(),
    )).toContain("FollowUpBeforeOriginal");
  });

  it("does not flag a follow-up when there's a prior training on the same school", () => {
    const earlier = activity({ id: "PA-PREV", scheduledDate: "2026-04-01", kind: "TeacherTraining" });
    expect(detectFraudFlags(
      activity({ kind: "FollowUpVisit", scheduledDate: "2026-05-15" }),
      ctx({ recentPartnerActivities: [earlier] } as object),
    )).not.toContain("FollowUpBeforeOriginal");
  });

  it("returns empty when every rule passes (clean partner)", () => {
    expect(detectFraudFlags(activity(), ctx())).toEqual([]);
  });
});

// ────────────────── Joint Work ──────────────────

describe("validateJointWork", () => {
  function jw(over: Partial<JointWorkAssignment> = {}): JointWorkAssignment {
    return {
      id: "JW-1",
      activityId: "PA-1",
      lead: "Partner",
      edifyAssignments: [{ userId: "U-CC-1", userName: "Paul",  role: "Observer" }],
      partnerAssignments: [{ userId: "U-PT-1", userName: "Sarah", role: "Lead"     }],
      responsibilityOwnerUserId: "U-PT-1",
      nextActionOwnerUserId:     "U-CC-1",
      sharedChecklist: [
        { id: "ck-1", label: "Deliver training",     done: false },
        { id: "ck-2", label: "Upload attendance",    done: false },
        { id: "ck-3", label: "Submit training report", done: false },
      ],
      ...over,
    };
  }

  it("returns null for a valid assignment", () => {
    expect(validateJointWork(jw())).toBeNull();
  });

  it("fails when no assignees on either side", () => {
    expect(validateJointWork(jw({ edifyAssignments: [], partnerAssignments: [] })))
      .toMatch(/at least one/i);
  });

  it("fails when responsibility owner is not in either list", () => {
    expect(validateJointWork(jw({ responsibilityOwnerUserId: "U-UNKNOWN" })))
      .toMatch(/responsibility/i);
  });

  it("fails when lead side has no Lead-role assignee", () => {
    expect(validateJointWork(jw({
      lead: "Edify",
      edifyAssignments: [{ userId: "U-CC-1", userName: "Paul", role: "Observer" }],
    }))).toMatch(/Lead/);
  });
});

describe("responsibilityOwner + checklistProgress", () => {
  it("resolves the responsibility owner and reports their side", () => {
    const owner = responsibilityOwner({
      id: "JW-1", activityId: "PA-1", lead: "Partner",
      edifyAssignments:   [{ userId: "U-CC-1", userName: "Paul",  role: "Observer" }],
      partnerAssignments: [{ userId: "U-PT-1", userName: "Sarah", role: "Lead"     }],
      responsibilityOwnerUserId: "U-PT-1",
      nextActionOwnerUserId:     "U-CC-1",
      sharedChecklist: [],
    });
    expect(owner).toEqual({ userId: "U-PT-1", userName: "Sarah", side: "Partner" });
  });

  it("returns checklist progress as done/total/pct", () => {
    const p = checklistProgress({
      id: "JW-1", activityId: "PA-1", lead: "Partner",
      edifyAssignments: [], partnerAssignments: [],
      responsibilityOwnerUserId: "U-PT-1", nextActionOwnerUserId: "U-PT-1",
      sharedChecklist: [
        { id: "a", label: "x", done: true },
        { id: "b", label: "y", done: true },
        { id: "c", label: "z", done: false },
        { id: "d", label: "w", done: false },
      ],
    });
    expect(p).toEqual({ done: 2, total: 4, pct: 50 });
  });
});
