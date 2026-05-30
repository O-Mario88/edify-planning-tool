// Mock evidence summaries — 6 partner activities covering the full
// spread of evidence states so the dashboard renders something
// interesting on every tab and every readiness threshold.

import {
  EVIDENCE_REQUIREMENTS,
  computeEvidenceSummary,
  type PartnerEvidenceItem,
  type PartnerEvidenceSummary,
  type ActivityType,
  type EvidenceTypeKey,
} from "./partner-evidence";
import type { MissionStatusCard } from "@/components/partner/PartnerMissionHero";

// Helper — build an item list from the activity's required spec.
// `presentTypes` are uploaded/accepted; everything else stays missing.
function buildItems(
  activityId: string,
  activityType: ActivityType,
  presentTypes: EvidenceTypeKey[],
  uploadedBy = "Daniel Mwangi (BFEP)",
  uploadedAt = "2026-05-12T11:30:00Z",
): PartnerEvidenceItem[] {
  const reqs = EVIDENCE_REQUIREMENTS[activityType];
  return reqs.map((req, idx) => ({
    id: `${activityId}-${req.type}-${idx}`,
    partnerActivityId: activityId,
    type: req.type,
    label: req.label,
    description: req.description,
    required: req.required,
    critical: req.critical,
    status: presentTypes.includes(req.type) ? "uploaded" : "missing",
    uploadedBy: presentTypes.includes(req.type) ? uploadedBy : undefined,
    uploadedAt: presentTypes.includes(req.type) ? uploadedAt : undefined,
  }));
}

export const evidenceSummaries: PartnerEvidenceSummary[] = [
  // 1. Complete — ready for CCEO confirmation. Hope Primary visit.
  computeEvidenceSummary({
    activityId: "EVA-001",
    partnerId: "P-BFEP",
    schoolId: "SCH-HOPE",
    schoolName: "Hope Primary School",
    activityType: "follow_up_visit",
    activityLabel: "Follow-Up coaching visit",
    items: buildItems("EVA-001", "follow_up_visit", [
      "visit_report", "school_confirmation", "previous_activity_link",
      "what_changed", "ssa_area_link", "recommendations", "agreed_action",
      "follow_up_date", "photo",
    ]),
  }),
  // 2. Partial — Grace Primary training, missing critical attendance
  computeEvidenceSummary({
    activityId: "EVA-002",
    partnerId: "P-BFEP",
    schoolId: "SCH-GRACE",
    schoolName: "Grace Primary School",
    activityType: "in_school_training",
    activityLabel: "In-School numeracy training",
    items: buildItems("EVA-002", "in_school_training", [
      "activity_report", "school_confirmation", "training_topic",
      "ssa_area_link",
    ]),
  }),
  // 3. Returned for correction — Kireka debrief, CCEO returned it
  {
    ...computeEvidenceSummary({
      activityId: "EVA-003",
      partnerId: "P-BFEP",
      schoolId: "SCH-KIREKA",
      schoolName: "Kireka Primary School",
      activityType: "partner_led_teacher_training",
      activityLabel: "P3 Literacy training debrief",
      items: buildItems("EVA-003", "partner_led_teacher_training", [
        "activity_report", "attendance_sheet", "training_topic",
        "facilitator_details", "participant_count", "school_list",
        "ssa_area_link", "partner_debrief",
      ]),
    }),
    status: "returned_for_correction",
    returnReason: "attendance_sheet_unclear",
    reviewerComment: "Attendance sheet missing teacher names. Add names, school, date, and facilitator.",
    returnedAt: "2026-05-11T16:45:00Z",
    returnedBy: "Paul Chinyama (CCEO)",
    dueDateIso: "2026-05-16T17:00:00Z",
  },
  // 4. Missing / not started — Maple Grove coaching just assigned
  computeEvidenceSummary({
    activityId: "EVA-004",
    partnerId: "P-BFEP",
    schoolId: "SCH-MAPLE",
    schoolName: "Maple Grove Primary",
    activityType: "coaching_visit",
    activityLabel: "Literacy follow-up coaching",
    items: buildItems("EVA-004", "coaching_visit", []),
  }),
  // 5. Confirmed by CCEO — St. Mary's, on its way to PL
  {
    ...computeEvidenceSummary({
      activityId: "EVA-005",
      partnerId: "P-BFEP",
      schoolId: "SCH-STMARY",
      schoolName: "St. Mary's Primary School",
      activityType: "follow_up_visit",
      activityLabel: "Leadership support visit",
      items: buildItems("EVA-005", "follow_up_visit", [
        "visit_report", "school_confirmation", "previous_activity_link",
        "what_changed", "ssa_area_link", "recommendations", "agreed_action",
        "follow_up_date",
      ]),
    }),
    status: "confirmed_by_cceo",
  },
  // 6. Verified by M&E — Namilyango resource delivery, fully closed
  {
    ...computeEvidenceSummary({
      activityId: "EVA-006",
      partnerId: "P-BFEP",
      schoolId: "SCH-NAMI",
      schoolName: "Namilyango Primary School",
      activityType: "resource_delivery",
      activityLabel: "Learning materials delivery",
      items: buildItems("EVA-006", "resource_delivery", [
        "delivery_note", "school_confirmation", "participant_count",
        "recipient_signature", "follow_up_date", "ssa_area_link", "photo",
      ]),
    }),
    status: "verified_by_me",
  },
];

// ────────── Aggregate metrics for the Evidence Quality panel ──────────

export type EvidenceQualityMetrics = {
  completionRatePct: number;
  returnedRatePct: number;
  avgCorrectionDays: number;
  mneVerificationRatePct: number;
  rejectedCount: number;
  // 30-day rolling for context
  windowLabel: string;
};

export const evidenceQualityMetrics: EvidenceQualityMetrics = {
  completionRatePct: 91,
  returnedRatePct: 6,
  avgCorrectionDays: 1.4,
  mneVerificationRatePct: 88,
  rejectedCount: 1,
  windowLabel: "Last 30 days",
};

// ────────── School-support impact ──────────

export type SchoolImpactMetrics = {
  schoolsSupported: number;
  schoolsCceoConfirmed: number;
  schoolsMeVerified: number;
  schoolsShowingImprovement: number;
  schoolsMovedBandUp: number;
  windowLabel: string;
};

export const schoolImpactMetrics: SchoolImpactMetrics = {
  schoolsSupported: 18,
  schoolsCceoConfirmed: 11,
  schoolsMeVerified: 7,
  schoolsShowingImprovement: 4,
  schoolsMovedBandUp: 2,
  windowLabel: "This Month",
};

// ────────── Tracker + hero counts ──────────
//
// Same numbers feed both the 6-card hero panel and the 8-step Workflow
// Tracker. Keeping them in one place means a status change in the
// engine automatically flows to every surface.

export const workflowStepCounts = {
  assigned:   7,
  scheduled:  5,
  delivered:  6,
  evidence:   3, // evidence-uploaded but not yet CCEO-confirmed
  cceo:       4, // CCEO confirmed
  plApproval: 3, // PL approved (in accountant queue)
  accountant: 2, // sent to accountant
  paid:       16,
};

export const missionStatusCards: MissionStatusCard[] = [
  { key: "assigned",       label: "Assigned",                count: workflowStepCounts.assigned,   tone: "neutral" },
  { key: "scheduled",      label: "Scheduled",               count: workflowStepCounts.scheduled,  tone: "info"    },
  { key: "evidenceNeeded", label: "Evidence Needed",         count: 14,                            tone: "danger"  },
  { key: "awaitingCceo",   label: "Awaiting CCEO",           count: 5,                             tone: "warn"    },
  { key: "awaitingPl",     label: "Awaiting PL",             count: workflowStepCounts.cceo,       tone: "warn"    },
  { key: "paid",           label: "Paid / Cleared",          count: workflowStepCounts.paid,       tone: "success" },
];

export const bfepMissionOrg = {
  partnerName: "Bright Future Education Partners",
  districts: ["Mukono", "Kayunga"],
  schoolsAssigned: 24,
  activeActivities: 18,
  edifyFocal: "Sarah Nanyongo (CCEO)",
  contractStatus: "Active" as const,
};
