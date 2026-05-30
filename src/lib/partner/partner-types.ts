// Partner Operating Layer — shared types.
//
// The spec is explicit: partners do not work outside the system.
// Partners work inside the same execution loop as staff, but with
// controlled permissions, verified evidence, shared planning, and
// clear accountability. Every type below is shaped so partner work
// can be enforced (scope), verified (counted-vs-not), measured
// (health), and integrated (the same ActionItem the rest of the
// 10-Second Command System already consumes).
//
// Layering:
//
//   • Partner          — the organization
//   • PartnerUser      — humans inside that org (3 sub-types)
//   • PartnerScope     — the contract — what the partner is allowed to do
//   • PartnerActivity  — the unit of work the partner executes
//   • PartnerEvidence  — proof artefacts
//   • JointWork        — when Edify staff + partner collaborate
//   • PartnerComment   — collaboration thread (visible vs internal)
//   • PartnerHealth    — single number summarising delivery quality
//
// Server-and-client safe. No `server-only` import. The scope engine,
// verification engine, and health engine all live in sibling files
// and import from here.

// ────────── Partner organization ──────────

export type PartnerCategory =
  | "TrainingProvider"
  | "MaterialsProvider"
  | "AssessmentPartner"
  | "InfrastructurePartner"
  | "AdvocacyPartner"
  | "OtherImplementer";

export type Partner = {
  id: string;
  name: string;
  shortName?: string;
  category: PartnerCategory;
  /// ISO 3166 country code — partners can be country-scoped.
  countryId: string;
  /// Optional logo / brand colour for the partner profile card.
  logoUrl?: string;
  brandColor?: string;
  contractActive: boolean;
  /// Edify focal person — the staff who owns the relationship.
  edifyFocalUserId: string;
  /// Partner focal — the partner-side counterpart.
  partnerFocalUserId: string;
  /// "Excellent" / "Healthy" / "Watch" / "AtRisk" / "Suspended" —
  /// denormalised from PartnerHealth so partner-list views don't
  /// recompute on every render.
  currentHealthBand: PartnerHealthBand;
  createdAt: string;
};

// ────────── Three partner user types ──────────
//
// Distinct permissions per type — the spec is unambiguous about
// what each can do. These are mapped to top-level EdifyRole values in
// auth-public.ts so middleware can gate routes per type.

export type PartnerUserType = "PartnerAdmin" | "PartnerFieldOfficer" | "PartnerViewer";

export type PartnerUser = {
  id: string;
  partnerId: string;
  email: string;
  name: string;
  userType: PartnerUserType;
  /// Which scopes this user is assigned to (a partner may have
  /// multiple contracts).
  scopeIds: string[];
  /// True for the senior partner contact whose name appears on contracts.
  isFocal: boolean;
  /// Whether the user can view their org's finance/contract terms
  /// (only Admin gets this by default).
  canViewFinance: boolean;
};

// ────────── Partner Scope — the enforcement boundary ──────────
//
// The scope engine refuses any activity outside what's defined here.
// This is the load-bearing security primitive of the entire partner
// operating layer.

export type PartnerActivityKind =
  | "TeacherTraining"
  | "InSchoolTraining"
  | "FollowUpVisit"
  | "ClassroomObservation"
  | "CoachingSession"
  | "ResourceDelivery"
  | "SchoolLeadershipCoaching"
  | "DataCollection";

export type InterventionArea =
  | "TeachingAndLearning"
  | "LearningEnvironment"
  | "LeadershipAndGovernance"
  | "ParentAndCommunityEngagement"
  | "StudentWellbeing"
  | "AssessmentAndDataUse";

export type PartnerFundingModel =
  | "NoFinance"          // partner self-funded
  | "Reimbursement"      // partner claims after verified work
  | "Advance"            // Edify advances partner funds
  | "ContractMilestone"  // payment tied to deliverable
  | "CostShare"          // both contribute
  | "DonorFunded";       // a donor budget is the source

export type PartnerScope = {
  id: string;
  partnerId: string;
  contractName: string;
  contractRef?: string;
  /// Geographic scope — schools must fall inside these districts.
  /// At least one of districtIds or schoolIds must be non-empty.
  regionIds: string[];
  districtIds: string[];
  clusterIds: string[];
  schoolIds: string[];
  /// Activity types the partner can execute. The scope engine
  /// rejects anything not in this list.
  allowedActivityKinds: PartnerActivityKind[];
  /// Intervention areas the partner is contracted to support. Used
  /// for impact attribution + gap-finding.
  interventionAreas: InterventionArea[];
  /// Contract window — activities outside this window are rejected.
  startDate: string;        // ISO date
  endDate: string;          // ISO date
  /// Operational expectations — what success looks like for this
  /// contract. The engine doesn't enforce these directly; they drive
  /// the Health Score's "Expected Output" axis.
  expectedSchoolReach?: number;
  expectedTeacherReach?: number;
  expectedActivitiesPerMonth?: number;
  reportingFrequencyDays: number;
  evidenceRequirements: EvidenceRequirement[];
  /// Default verification level for activities under this scope.
  /// Individual activities can override upward (never downward).
  defaultVerificationLevel: VerificationLevel;
  /// Edify focal person for THIS scope (may differ from the partner's
  /// org-level focal if a different contract has a different lead).
  edifyFocalUserId: string;
  partnerFocalUserId: string;
  /// Funding model — drives whether the Accountant sees this partner.
  fundingModel: PartnerFundingModel;
  status: "Active" | "Paused" | "Completed" | "Terminated";
};

export type EvidenceRequirement = {
  /// The kind of artefact (e.g. "AttendanceSheet", "PrePostAssessment").
  kind: EvidenceKind;
  /// Whether this evidence is mandatory; activities cannot be
  /// verified without it.
  required: boolean;
};

export type EvidenceKind =
  | "AttendanceSheet"
  | "SignedParticipantList"
  | "TrainingAgenda"
  | "FacilitatorNotes"
  | "PrePostAssessment"
  | "Photos"
  | "Videos"
  | "TrainingReport"
  | "TeacherFeedback"
  | "SchoolVisitForm"
  | "ObservationNotes"
  | "CoachingNotes"
  | "AgreedActionPlan"
  | "DeliveryNote"
  | "ReceivingSignature"
  | "QuantityDelivered"
  | "SchoolConfirmation"
  | "PhotoEvidence"
  | "GPSStamp";

// ────────── Verification matrix ──────────

export type VerificationLevel =
  | "Light"              // trusted partner, low-risk → evidence check only
  | "Standard"           // normal → M&E review + evidence
  | "JointConfirmation"  // staff was present → both must confirm
  | "SpotCheck"          // suspicious/high-value → M&E field check
  | "CDCertification";   // strategic → Country Director sign-off

export type ActivityStatus =
  | "Draft"
  | "Submitted"
  | "Approved"
  | "Scheduled"
  | "Completed"
  | "Cancelled";

export type VerificationStatus =
  | "EvidenceMissing"
  | "UnderReview"
  | "ReturnedForCorrection"
  | "Verified"
  | "Counted"           // verified AND counted toward targets
  | "Rejected"
  | "AuditRequired";

// ────────── Partner Activity ──────────
//
// One unit of partner work. Lives separately from the staff
// `PlannedActivity` so partner-specific fields (evidence, verification,
// joint-work, comment thread, fraud flags) don't pollute the staff type.
// Both surfaces converge in the school-profile Support Timeline.

export type PartnerActivity = {
  id: string;
  partnerId: string;
  scopeId: string;
  /// Free text — "Phonics Training · Grade 3 teachers".
  title: string;
  kind: PartnerActivityKind;
  intervention: InterventionArea;
  schoolId: string;
  schoolName: string;
  /// Always populated — the engine inserts the partner's primary
  /// district at write time so cross-district reports work.
  districtId: string;
  /// When the activity is/was/will be executed.
  scheduledDate: string;
  /// Set when completed; null while pending.
  completedDate?: string;
  /// Aggregated participation count (teachers / learners / schools).
  participants?: { teachers?: number; learners?: number; schools?: number };
  status: ActivityStatus;
  /// Verification status — independent of activity status. The spec
  /// is explicit: an activity can be Completed but not Verified.
  verificationStatus: VerificationStatus;
  /// Required verification level. Default comes from scope; engine
  /// upgrades for spot-check / suspicious flags.
  verificationLevel: VerificationLevel;
  /// Evidence attached. The verification engine refuses to mark
  /// Verified when required artefacts are missing.
  evidence: PartnerEvidence[];
  /// Optional joint-work record when staff was also involved.
  jointWorkId?: string;
  /// Fraud flags raised by the detection engine. Non-empty triggers
  /// a Needs Review classification — never an auto-reject (the spec
  /// is explicit on this).
  fraudFlags: FraudFlag[];
  /// Whether the partner is requesting follow-up after the activity.
  followUpRequested?: FollowUpRequest;
  /// Comment thread (visible + internal mixed; UI filters by reader).
  comments: PartnerComment[];
  /// Audit trail.
  createdAt: string;
  createdById: string;
  updatedAt: string;
  /// Salesforce/M&E match status — partner activities still flow
  /// through the same data-intake pipeline as staff activities.
  salesforceMatchStatus?: "SmartMatch" | "PossibleMatch" | "NoMatch" | "Verified";
};

// ────────── Evidence locker ──────────

export type PartnerEvidence = {
  id: string;
  activityId: string;
  kind: EvidenceKind;
  /// Cloud storage URL or relative path. Mock today.
  url: string;
  uploadedByUserId: string;
  uploadedAt: string;
  /// File metadata for the UI thumbnail / size badge.
  fileSize?: number;
  mimeType?: string;
  /// Latest verification action on this specific artefact.
  reviewStatus: "Pending" | "Accepted" | "Rejected" | "ReplacementRequested";
  reviewerNote?: string;
  /// History of replacements — the spec wants an audit trail when
  /// evidence is re-uploaded.
  replacementHistory: Array<{ url: string; replacedAt: string; replacedById: string }>;
};

// ────────── Joint Work Mode ──────────
//
// When an activity involves both staff and partner, the JointWork
// record nails down ownership and stops the "who did what" arguments.

export type JointWorkLead = "Edify" | "Partner" | "Joint";

export type JointWorkRole =
  | "Lead"
  | "CoFacilitator"
  | "Observer"
  | "Verifier"
  | "DataCapture";

export type JointWorkAssignment = {
  id: string;
  activityId: string;
  lead: JointWorkLead;
  /// Staff side.
  edifyAssignments: Array<{ userId: string; userName: string; role: JointWorkRole }>;
  /// Partner side.
  partnerAssignments: Array<{ userId: string; userName: string; role: JointWorkRole }>;
  /// Single owner of the activity record (the person responsible for
  /// closing it out). Always resolvable to a single user.
  responsibilityOwnerUserId: string;
  /// Single owner of the next action (may differ from responsibility).
  nextActionOwnerUserId: string;
  /// Shared evidence folder + checklist for the joint activity.
  sharedChecklist: Array<{ id: string; label: string; done: boolean; doneByUserId?: string }>;
};

// ────────── Comments — visible vs internal ──────────

export type PartnerComment = {
  id: string;
  activityId: string;
  authorUserId: string;
  authorName: string;
  authorRole: string;
  body: string;
  /// Visibility: PartnerVisible = the partner sees it. InternalOnly
  /// = only Edify staff see it (CPL flags, behind-the-scenes notes).
  visibility: "PartnerVisible" | "InternalOnly";
  createdAt: string;
};

// ────────── Follow-Up handoff ──────────

export type FollowUpKind =
  | "None"
  | "CceoFollowUpVisit"
  | "PartnerFollowUpVisit"
  | "JointFollowUp"
  | "MEVerificationVisit"
  | "SchoolLeadershipCoaching";

export type FollowUpRequest = {
  kind: FollowUpKind;
  /// Plain-English reason — surfaced to the receiving staff.
  reason: string;
  /// When the follow-up should happen by (engine generates the task
  /// for the appropriate role with this due date).
  byDate: string;
  /// Optional assignee suggestion (defaults to "any CCEO with this
  /// school in their portfolio").
  suggestedUserId?: string;
};

// ────────── Fraud + duplication flags ──────────

export type FraudFlag =
  | "DuplicateSchoolDateActivity"
  | "DuplicateAttendanceSheet"
  | "OutsideScope"
  | "MissingSchoolAssignment"
  | "FollowUpBeforeOriginal"
  | "ReusedPhoto"
  | "GPSMismatch"
  | "UnrealisticParticipantCount"
  | "AfterContractEnd"
  | "EditAfterVerified";

export const FRAUD_FLAG_LABEL: Record<FraudFlag, string> = {
  DuplicateSchoolDateActivity: "Possible duplicate (same school + date + kind)",
  DuplicateAttendanceSheet:    "Attendance sheet reused from earlier activity",
  OutsideScope:                "Activity outside the partner's approved scope",
  MissingSchoolAssignment:     "School not assigned to this partner",
  FollowUpBeforeOriginal:      "Follow-Up reported before the original training",
  ReusedPhoto:                 "Photo previously uploaded on another activity",
  GPSMismatch:                 "GPS location does not match the school location",
  UnrealisticParticipantCount: "Participant count outside the normal range",
  AfterContractEnd:            "Activity date is past the contract end date",
  EditAfterVerified:           "Attempted edit after the record was verified",
};

// ────────── Health Score ──────────

export type PartnerHealthBand = "Excellent" | "Healthy" | "Watch" | "AtRisk" | "Suspended";

export type PartnerHealthInputs = {
  partnerId: string;
  periodIso: string;
  /// 0-100, % of submitted activities that passed verification.
  verificationPassRatePct: number;
  /// 0-100, average quality score of submitted evidence.
  evidenceQualityScore: number;
  /// 0-100, % of activities reported within 48 hours.
  timelinessScore: number;
  /// 0-100, % of partner-supported schools that improved on SSA.
  schoolImprovementScore: number;
  /// 0-100, how reliably partner collaborates with staff (joint-work
  /// completion, comment-response time).
  staffCollaborationScore: number;
  /// 0-100, accuracy of partner-reported counts vs. M&E verified.
  reportingAccuracyScore: number;
  /// Penalties — each is a 0-100 magnitude. Larger = worse.
  overduePenalty: number;
  returnedCorrectionPenalty: number;
};

export type PartnerHealthResult = {
  partnerId: string;
  periodIso: string;
  score: number;           // 0-100
  band: PartnerHealthBand;
  /// By-factor breakdown so the UI can render "this is why".
  breakdown: {
    verifiedDelivery: number;
    evidenceQuality: number;
    timeliness: number;
    schoolImprovement: number;
    staffCollaboration: number;
    reportingAccuracy: number;
    overduePenalty: number;
    returnedCorrectionPenalty: number;
  };
};

// ────────── Impact attribution ──────────

export type PartnerImpactSummary = {
  partnerId: string;
  periodIso: string;
  schoolsSupported: number;
  verifiedActivities: number;
  teachersTrained: number;
  followUpsCompleted: number;
  /// Mean SSA score change in partner-supported schools.
  meanSsaDelta: number;
  /// Schools that crossed band thresholds during the period.
  schoolsImprovedFromCriticalToAtRisk: number;
  schoolsImprovedFromAtRiskToOnTrack: number;
  /// Optional cost-per-improved-school for partners with funding models.
  costPerImprovedSchoolUgx?: number;
};
