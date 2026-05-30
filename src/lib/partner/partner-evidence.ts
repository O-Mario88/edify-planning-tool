// Partner Evidence Assurance — types, engine, and per-activity-type
// requirements.
//
// Five questions every partner activity must answer (from the spec):
//   1. Was the work done?
//   2. Was it done at the correct school?
//   3. Was it the correct activity?
//   4. Was it connected to the school's support need?
//   5. Is the evidence strong enough for confirmation / payment / reporting?
//
// Evidence is the bridge between Delivery → CCEO confirmation → PL
// approval → Accountant payment → M&E verification → school history.
// One submission updates every downstream view.

// ────────── Evidence type catalogue ──────────

export type EvidenceTypeKey =
  | "activity_report"
  | "attendance_sheet"
  | "training_topic"
  | "facilitator_details"
  | "participant_count"
  | "school_list"
  | "school_confirmation"
  | "pre_post_results"
  | "photo"
  | "supporting_document"
  | "partner_debrief"
  | "visit_report"
  | "coaching_report"
  | "observation_form"
  | "observation_score"
  | "delivery_note"
  | "recipient_signature"
  | "ssa_area_link"
  | "next_action"
  | "follow_up_date"
  | "improvement_target"
  | "recommendations"
  | "agreed_action"
  | "lesson_focus"
  | "coaching_feedback"
  | "previous_activity_link"
  | "what_changed";

export type ActivityType =
  | "partner_led_teacher_training"
  | "in_school_training"
  | "follow_up_visit"
  | "coaching_visit"
  | "classroom_observation"
  | "resource_delivery";

// ────────── Weighted scoring buckets ──────────
//
// Spec weights:
//   Activity report ............ 25%
//   Attendance / participant ... 20%
//   School/location confirmation 15%
//   SSA / support-need link .... 15%
//   Debrief / recommendations .. 15%
//   Supporting documents / photos 10%

export type ScoringBucket =
  | "activity_report"
  | "attendance"
  | "school_confirmation"
  | "ssa_link"
  | "debrief"
  | "supporting";

export const BUCKET_WEIGHT: Record<ScoringBucket, number> = {
  activity_report: 25,
  attendance: 20,
  school_confirmation: 15,
  ssa_link: 15,
  debrief: 15,
  supporting: 10,
};

// Map each evidence type to its scoring bucket. Used by the engine to
// roll a per-item submission status up into a weighted completeness %.
const TYPE_TO_BUCKET: Record<EvidenceTypeKey, ScoringBucket> = {
  activity_report:       "activity_report",
  visit_report:          "activity_report",
  coaching_report:       "activity_report",
  observation_form:      "activity_report",
  observation_score:     "activity_report",
  delivery_note:         "activity_report",

  attendance_sheet:      "attendance",
  participant_count:     "attendance",
  recipient_signature:   "attendance",

  school_list:           "school_confirmation",
  school_confirmation:   "school_confirmation",

  ssa_area_link:         "ssa_link",
  previous_activity_link:"ssa_link",
  what_changed:          "ssa_link",
  lesson_focus:          "ssa_link",

  partner_debrief:       "debrief",
  recommendations:       "debrief",
  next_action:           "debrief",
  agreed_action:         "debrief",
  improvement_target:    "debrief",
  follow_up_date:        "debrief",
  coaching_feedback:     "debrief",

  training_topic:        "supporting",
  facilitator_details:   "supporting",
  pre_post_results:      "supporting",
  photo:                 "supporting",
  supporting_document:   "supporting",
};

// ────────── Evidence item shape ──────────

export type EvidenceItemStatus =
  | "missing"
  | "uploaded"
  | "needs_review"
  | "accepted"
  | "returned"
  | "rejected";

export type PartnerEvidenceItem = {
  id: string;
  partnerActivityId: string;
  type: EvidenceTypeKey;
  label: string;
  description: string;
  required: boolean;
  critical: boolean;   // Must be present for CCEO confirmation
  status: EvidenceItemStatus;
  fileUrl?: string;
  textValue?: string;
  uploadedBy?: string;
  uploadedAt?: string;
  reviewedBy?: string;
  reviewedAt?: string;
  returnReason?: StandardReturnReason;
  reviewerComment?: string;
};

// ────────── Per-activity-type requirements ──────────
//
// Each entry: { type, label, description, required, critical }
// "critical" means CCEO cannot confirm without this item.

export type EvidenceRequirement = {
  type: EvidenceTypeKey;
  label: string;
  description: string;
  required: boolean;
  critical: boolean;
};

export const EVIDENCE_REQUIREMENTS: Record<ActivityType, EvidenceRequirement[]> = {
  partner_led_teacher_training: [
    { type: "activity_report",     label: "Training report",            description: "What was delivered.",                          required: true, critical: true  },
    { type: "attendance_sheet",    label: "Attendance sheet",           description: "Signed list of teachers who attended.",        required: true, critical: true  },
    { type: "training_topic",      label: "Training topic",             description: "Confirms relevance to the school need.",       required: true, critical: false },
    { type: "facilitator_details", label: "Facilitator name",           description: "Who delivered the training.",                  required: true, critical: false },
    { type: "participant_count",   label: "Number of teachers trained", description: "Counts reach for reporting.",                  required: true, critical: true  },
    { type: "school_list",         label: "Schools represented",        description: "Which schools sent teachers.",                 required: true, critical: true  },
    { type: "ssa_area_link",       label: "SSA area addressed",         description: "Links the training to a school weakness.",     required: true, critical: true  },
    { type: "partner_debrief",     label: "Partner debrief",            description: "Lessons learned + next steps.",                required: true, critical: false },
    { type: "pre_post_results",    label: "Pre/post test results",      description: "If applicable — measures learning shift.",     required: false, critical: false },
    { type: "photo",               label: "Photos / supporting docs",   description: "Where allowed by policy.",                     required: false, critical: false },
  ],
  in_school_training: [
    { type: "activity_report",     label: "Training notes / materials", description: "What was delivered in-school.",                required: true, critical: true  },
    { type: "school_confirmation", label: "School name and location",   description: "Confirms the visit happened.",                 required: true, critical: true  },
    { type: "training_topic",      label: "Training topic",             description: "Subject of the in-school session.",            required: true, critical: false },
    { type: "participant_count",   label: "Teachers trained / coached", description: "Who participated.",                            required: true, critical: true  },
    { type: "attendance_sheet",    label: "Attendance sheet",           description: "Signed list of participants.",                 required: true, critical: true  },
    { type: "ssa_area_link",       label: "SSA area addressed",         description: "Which weakness the training targets.",         required: true, critical: true  },
    { type: "agreed_action",       label: "Agreed next action",         description: "What the school will do next.",                required: true, critical: false },
    { type: "recommendations",     label: "Follow-Up recommendation",   description: "What the partner recommends.",                 required: true, critical: false },
    { type: "photo",               label: "Photos / supporting docs",   description: "Where allowed by policy.",                     required: false, critical: false },
  ],
  follow_up_visit: [
    { type: "visit_report",        label: "Visit report",               description: "Narrative of the follow-up.",                  required: true, critical: true  },
    { type: "school_confirmation", label: "School visited",             description: "Confirms the correct school.",                 required: true, critical: true  },
    { type: "previous_activity_link", label: "Previous activity link",  description: "Which activity is being followed up.",         required: true, critical: true  },
    { type: "what_changed",        label: "What changed since support", description: "Evidence of impact.",                          required: true, critical: false },
    { type: "ssa_area_link",       label: "SSA area addressed",         description: "Which weakness the visit targets.",            required: true, critical: true  },
    { type: "recommendations",     label: "Recommendations",            description: "What the partner recommends next.",            required: true, critical: false },
    { type: "agreed_action",       label: "Next action agreed",         description: "What the school agreed to do.",                required: true, critical: false },
    { type: "follow_up_date",      label: "Next follow-up date",        description: "When this thread continues.",                  required: false, critical: false },
    { type: "photo",               label: "Supporting photo/document",  description: "Where allowed by policy.",                     required: false, critical: false },
  ],
  coaching_visit: [
    { type: "coaching_report",     label: "Coaching report",            description: "Narrative of the coaching session.",           required: true, critical: true  },
    { type: "participant_count",   label: "Teacher / leader coached",   description: "Who was coached.",                             required: true, critical: true  },
    { type: "training_topic",      label: "Coaching topic",             description: "Subject of the coaching.",                     required: true, critical: false },
    { type: "observation_form",    label: "Observation notes",          description: "What the coach observed.",                     required: true, critical: false },
    { type: "agreed_action",       label: "Action agreed",              description: "What the teacher will do next.",               required: true, critical: false },
    { type: "improvement_target", label: "Improvement target",         description: "Measurable goal for the next session.",        required: true, critical: false },
    { type: "follow_up_date",      label: "Follow-Up date",             description: "Next coaching touchpoint.",                    required: true, critical: false },
    { type: "ssa_area_link",       label: "SSA area addressed",         description: "Links the coaching to a school weakness.",     required: true, critical: true  },
  ],
  classroom_observation: [
    { type: "observation_form",    label: "Observation form",           description: "Standardised observation rubric.",             required: true, critical: true  },
    { type: "participant_count",   label: "Teacher observed",           description: "Who was observed.",                            required: true, critical: true  },
    { type: "lesson_focus",        label: "Subject / class observed",   description: "Class + lesson focus.",                        required: true, critical: true  },
    { type: "observation_score",   label: "Observation score / rubric", description: "Numeric / rubric outcome.",                    required: true, critical: false },
    { type: "coaching_feedback",   label: "Coaching feedback",          description: "What feedback was given.",                     required: true, critical: false },
    { type: "agreed_action",       label: "Next improvement action",    description: "What the teacher will work on.",               required: true, critical: false },
    { type: "follow_up_date",      label: "Follow-Up needed",           description: "Date and type of next touchpoint.",            required: true, critical: false },
  ],
  resource_delivery: [
    { type: "delivery_note",       label: "Delivery note",              description: "Itemised list of resources delivered.",        required: true, critical: true  },
    { type: "school_confirmation", label: "School receiving",           description: "Confirms the correct school.",                 required: true, critical: true  },
    { type: "participant_count",   label: "Resource type and quantity", description: "What and how many.",                           required: true, critical: true  },
    { type: "recipient_signature", label: "Recipient signature",        description: "Who received on behalf of the school.",        required: true, critical: true  },
    { type: "follow_up_date",      label: "Date received",              description: "When the school took possession.",             required: true, critical: false },
    { type: "ssa_area_link",       label: "Link to school need",        description: "Why this resource was sent.",                  required: true, critical: false },
    { type: "photo",               label: "Photo of delivery",          description: "Where allowed by policy.",                     required: false, critical: false },
  ],
};

// ────────── Standardised return reasons ──────────

export type StandardReturnReason =
  | "attendance_sheet_missing"
  | "attendance_sheet_unclear"
  | "wrong_school"
  | "wrong_date"
  | "wrong_activity_type"
  | "missing_debrief"
  | "missing_ssa_link"
  | "missing_participant_count"
  | "duplicate_submission"
  | "poor_quality_image"
  | "unsupported_document_type"
  | "outside_partner_scope"
  | "report_does_not_match"
  | "evidence_does_not_prove_delivery";

export const RETURN_REASON_LABEL: Record<StandardReturnReason, string> = {
  attendance_sheet_missing:        "Attendance sheet missing",
  attendance_sheet_unclear:        "Attendance sheet unclear",
  wrong_school:                    "Wrong school",
  wrong_date:                      "Wrong date",
  wrong_activity_type:             "Wrong activity type",
  missing_debrief:                 "Missing debrief",
  missing_ssa_link:                "Missing SSA link",
  missing_participant_count:       "Missing participant count",
  duplicate_submission:            "Duplicate submission",
  poor_quality_image:              "Poor quality image",
  unsupported_document_type:       "Unsupported document type",
  outside_partner_scope:           "Outside partner scope",
  report_does_not_match:           "Report does not match activity",
  evidence_does_not_prove_delivery:"Evidence does not prove delivery",
};

// ────────── Summary / readiness ──────────

export type EvidenceQualityLevel = "strong" | "acceptable" | "weak" | "invalid";

export type PartnerEvidenceSummaryStatus =
  | "not_started"
  | "missing"
  | "partial"
  | "submitted"
  | "needs_review"
  | "complete"
  | "returned_for_correction"
  | "confirmed_by_cceo"
  | "verified_by_me"
  | "locked";

export type PartnerEvidenceSummary = {
  activityId: string;
  partnerId: string;
  schoolId: string;
  schoolName: string;
  activityType: ActivityType;
  activityLabel: string;
  status: PartnerEvidenceSummaryStatus;
  completenessScore: number;       // 0-100, weighted by bucket
  qualityLevel: EvidenceQualityLevel;
  criticalMissingCount: number;
  requiredMissingCount: number;
  uploadedCount: number;
  requiredCount: number;
  items: PartnerEvidenceItem[];
  returnReason?: StandardReturnReason;
  reviewerComment?: string;
  returnedAt?: string;
  returnedBy?: string;
  dueDateIso?: string;
  isReadyForCceoConfirmation: boolean;
  isReadyForPaymentApproval: boolean;
  isReadyForMEVerification: boolean;
};

// ────────── Engine ──────────
//
// Computes a weighted completeness score, quality level, and the
// three readiness flags from a raw item list. Pure function — call
// from any layer (server, client, test) and get the same answer.

const ACCEPTED: ReadonlyArray<EvidenceItemStatus> = ["uploaded", "accepted"];

export function computeEvidenceSummary(input: {
  activityId: string;
  partnerId: string;
  schoolId: string;
  schoolName: string;
  activityType: ActivityType;
  activityLabel: string;
  items: PartnerEvidenceItem[];
  status?: PartnerEvidenceSummaryStatus;
  returnReason?: StandardReturnReason;
  reviewerComment?: string;
  returnedAt?: string;
  returnedBy?: string;
  dueDateIso?: string;
}): PartnerEvidenceSummary {
  const reqs = EVIDENCE_REQUIREMENTS[input.activityType];

  // Bucket-weighted completeness. Each bucket contributes its weight
  // proportional to the share of its REQUIRED items that are present.
  const bucketTotals: Record<ScoringBucket, { required: number; uploaded: number }> = {
    activity_report:     { required: 0, uploaded: 0 },
    attendance:          { required: 0, uploaded: 0 },
    school_confirmation: { required: 0, uploaded: 0 },
    ssa_link:            { required: 0, uploaded: 0 },
    debrief:             { required: 0, uploaded: 0 },
    supporting:          { required: 0, uploaded: 0 },
  };

  let requiredCount = 0;
  let uploadedRequired = 0;
  let criticalMissing = 0;
  let requiredMissing = 0;
  let invalidCount = 0;

  for (const req of reqs) {
    const bucket = TYPE_TO_BUCKET[req.type];
    const match = input.items.find((it) => it.type === req.type);
    const present = !!match && ACCEPTED.includes(match.status);

    if (req.required) {
      requiredCount++;
      bucketTotals[bucket].required++;
      if (present) {
        uploadedRequired++;
        bucketTotals[bucket].uploaded++;
      } else {
        requiredMissing++;
        if (req.critical) criticalMissing++;
      }
    }
    if (match?.status === "rejected" || match?.status === "returned") {
      invalidCount++;
    }
  }

  // Score: sum of (bucket weight × bucket fill ratio), where buckets
  // with 0 required items get reweighted across the others.
  let totalWeight = 0;
  let weightedSum = 0;
  for (const bucket of Object.keys(bucketTotals) as ScoringBucket[]) {
    const w = BUCKET_WEIGHT[bucket];
    const { required, uploaded } = bucketTotals[bucket];
    if (required === 0) continue;
    totalWeight += w;
    weightedSum += w * (uploaded / required);
  }
  const completenessScore = totalWeight === 0
    ? 0
    : Math.round((weightedSum / totalWeight) * 100);

  // Quality level
  const quality: EvidenceQualityLevel = invalidCount > 0
    ? "invalid"
    : criticalMissing > 0
      ? "weak"
      : completenessScore >= 90
        ? "strong"
        : completenessScore >= 80
          ? "acceptable"
          : "weak";

  // Readiness flags — gates defined in the spec.
  // CCEO confirmation: ≥ 80% completeness AND no critical missing.
  const isReadyForCceoConfirmation = completenessScore >= 80 && criticalMissing === 0;
  // Payment approval requires CCEO confirmation upstream — this flag
  // tracks the evidence side of the gate only.
  const isReadyForPaymentApproval = isReadyForCceoConfirmation && completenessScore >= 80;
  // M&E verification — stricter quality bar.
  const isReadyForMEVerification = quality === "strong" || quality === "acceptable";

  // Derive a summary status when not explicitly set.
  const derivedStatus: PartnerEvidenceSummaryStatus = input.status
    ?? (uploadedRequired === 0
      ? "not_started"
      : requiredMissing === 0
        ? "complete"
        : "partial");

  return {
    activityId: input.activityId,
    partnerId: input.partnerId,
    schoolId: input.schoolId,
    schoolName: input.schoolName,
    activityType: input.activityType,
    activityLabel: input.activityLabel,
    status: derivedStatus,
    completenessScore,
    qualityLevel: quality,
    criticalMissingCount: criticalMissing,
    requiredMissingCount: requiredMissing,
    uploadedCount: uploadedRequired,
    requiredCount,
    items: input.items,
    returnReason: input.returnReason,
    reviewerComment: input.reviewerComment,
    returnedAt: input.returnedAt,
    returnedBy: input.returnedBy,
    dueDateIso: input.dueDateIso,
    isReadyForCceoConfirmation,
    isReadyForPaymentApproval,
    isReadyForMEVerification,
  };
}

// ────────── Locking ──────────

export const LOCK_BY_STAGE: Record<PartnerEvidenceSummaryStatus, boolean> = {
  not_started:             false,
  missing:                 false,
  partial:                 false,
  submitted:               false,
  needs_review:            false,
  complete:                false,
  returned_for_correction: false,
  confirmed_by_cceo:       true,
  verified_by_me:          true,
  locked:                  true,
};

// ────────── Helper: build an item record from required spec ──────────

export function emptyItemFor(
  activityId: string,
  req: EvidenceRequirement,
  idx: number,
): PartnerEvidenceItem {
  return {
    id: `${activityId}-${req.type}-${idx}`,
    partnerActivityId: activityId,
    type: req.type,
    label: req.label,
    description: req.description,
    required: req.required,
    critical: req.critical,
    status: "missing",
  };
}
