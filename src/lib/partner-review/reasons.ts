// Controlled reasons for Return / Reject (spec section 8 + 10).
//
// Return = evidence/report problem; activity may be valid.
// Reject = work not done / wrong work; activity must be redone.
//
// Keep these tight — analytics relies on consistent reasons across
// thousands of reviews.

import type { RejectReason, ReturnReason } from "./types";

export const RETURN_REASONS: ReturnReason[] = [
  { key: "evidence.school_stamp_missing",      label: "School stamp missing" },
  { key: "evidence.attendance_missing",        label: "Attendance sheet missing" },
  { key: "evidence.photo_unclear",             label: "Photo unclear" },
  { key: "evidence.report_incomplete",         label: "Report incomplete" },
  { key: "evidence.ssa_area_missing",          label: "SSA area not stated" },
  { key: "evidence.participant_count_missing", label: "Participant count missing" },
  { key: "evidence.debrief_missing",           label: "Debrief missing" },
  { key: "evidence.wrong_attachment",          label: "Wrong attachment uploaded" },
];

export const REJECT_REASONS: RejectReason[] = [
  { key: "reject.not_done",                    label: "Work not done",                                  serious: true },
  { key: "reject.wrong_school",                label: "Wrong school visited",                           serious: true },
  { key: "reject.wrong_activity",              label: "Wrong activity delivered",                       serious: true },
  { key: "reject.out_of_scope",                label: "Activity not within approved scope",             serious: true },
  { key: "reject.evidence_invalid",            label: "Evidence does not prove delivery",               serious: true },
  { key: "reject.school_denies",               label: "School denies activity happened",                serious: true },
  { key: "reject.duplicate_claim",             label: "Duplicate claim",                                serious: true },
  { key: "reject.wrong_date",                  label: "Wrong date" },
  { key: "reject.wrong_participants",          label: "Wrong participants" },
  { key: "reject.no_attendance_evidence",      label: "No attendance evidence" },
  { key: "reject.report_mismatch",             label: "Report does not match activity" },
  { key: "reject.submitted_before_delivery",   label: "Partner submitted before delivery",              serious: true },
  { key: "reject.quality_concern",             label: "Quality concern" },
  { key: "reject.safeguarding_concern",        label: "Safeguarding concern",                           serious: true },
  { key: "reject.fraud_concern",               label: "Fraud concern",                                  serious: true },
  { key: "reject.other",                       label: "Other",                                          requiresNotes: true },
];

export function returnReasonByKey(key: string): ReturnReason | undefined {
  return RETURN_REASONS.find((r) => r.key === key);
}

export function rejectReasonByKey(key: string): RejectReason | undefined {
  return REJECT_REASONS.find((r) => r.key === key);
}
