// Partner Today data model + mock.
//
// Answers a single question: what must our partner team do today,
// in what order, for which schools, and what evidence must be
// submitted before the day is complete?
//
// In production this is a server-resolved query joining today's
// scheduled partner activities, the evidence engine, the returns
// queue, and the payment-readiness gates.

export type PartnerTodayTaskType =
  | "training"
  | "in_school_training"
  | "follow_up_visit"
  | "coaching_visit"
  | "classroom_observation"
  | "ssa_support_visit"
  | "resource_delivery"
  | "joint_visit"
  | "reflection_debrief"
  | "evidence_upload"
  | "correction";

export type PartnerTodayUrgency = "critical" | "high" | "medium" | "low";

export type PartnerTodayStatus =
  | "scheduled"
  | "ready_to_start"
  | "in_progress"
  | "report_needed"
  | "evidence_needed"
  | "submitted"
  | "awaiting_cceo_confirmation"
  | "returned_for_correction"
  | "completed_today"
  | "overdue";

export type EvidenceChecklistItem = {
  label: string;
  required: boolean;
  critical: boolean;
  status: "missing" | "uploaded" | "accepted" | "returned";
};

export type PartnerTodayTask = {
  id: string;
  partnerId: string;
  taskType: PartnerTodayTaskType;
  schoolId?: string;
  schoolName?: string;
  district?: string;
  subCounty?: string;
  parish?: string;
  urgency: PartnerTodayUrgency;
  scheduledDate: string;
  scheduledTimeLabel?: string;
  purpose: string;
  ssaAreaAddressed?: string;
  expectedOutcome?: string;
  facilitator?: string;
  staffMonitorName?: string;
  status: PartnerTodayStatus;
  evidenceChecklist: EvidenceChecklistItem[];
  missingEvidenceCount: number;
  criticalMissingCount: number;
  evidenceCompletenessScore: number;
  returnedBy?: string;
  returnReason?: string;
  reviewerComment?: string;
  correctionDueDate?: string;
  paymentBlocker?: boolean;
  paymentBlockerReason?: string;
  primaryActionLabel: string;
  secondaryActionLabel?: string;
  href: string;
};

// ────────── Mock — today's partner work ──────────
//
// 4 activities at different stages + 1 correction + payment blockers
// + a couple of completed items so the Done-for-Today progress reads
// honestly.

const TODAY_ISO = "2026-06-12";

function checklist(items: { label: string; required?: boolean; critical?: boolean; status: EvidenceChecklistItem["status"] }[]): EvidenceChecklistItem[] {
  return items.map((it) => ({
    label: it.label,
    required: it.required ?? true,
    critical: it.critical ?? false,
    status: it.status,
  }));
}

export const partnerTodayTasks: PartnerTodayTask[] = [
  // 1. In-School training at Hope Primary — 9-12, evidence partial
  {
    id: "TODO-001",
    partnerId: "P-BFEP",
    taskType: "in_school_training",
    schoolId: "SCH-HOPE",
    schoolName: "Hope Primary School",
    district: "Mukono",
    subCounty: "Ntenjeru",
    parish: "Ntenjeru",
    urgency: "high",
    scheduledDate: TODAY_ISO,
    scheduledTimeLabel: "9:00 AM - 12:00 PM",
    purpose: "Strengthen phonics instruction after low Teaching & Learning SSA score.",
    ssaAreaAddressed: "Teaching & Learning",
    expectedOutcome: "P1-P3 teachers running 2 phonics blocks per week.",
    facilitator: "Daniel Mwangi (BFEP)",
    staffMonitorName: "Sarah Nanyongo (CCEO)",
    status: "ready_to_start",
    evidenceChecklist: checklist([
      { label: "Training report",       critical: true,  status: "missing" },
      { label: "Attendance sheet",      critical: true,  status: "missing" },
      { label: "Topic covered",         status: "missing" },
      { label: "Teachers trained",      critical: true,  status: "missing" },
      { label: "Partner debrief",       status: "missing" },
    ]),
    missingEvidenceCount: 5,
    criticalMissingCount: 3,
    evidenceCompletenessScore: 0,
    primaryActionLabel: "Start Activity",
    secondaryActionLabel: "View School",
    href: "/partner/today/TODO-001",
  },
  // 2. Follow-Up visit at Grace Primary — afternoon, critical
  {
    id: "TODO-002",
    partnerId: "P-BFEP",
    taskType: "follow_up_visit",
    schoolId: "SCH-GRACE",
    schoolName: "Grace Primary School",
    district: "Mukono",
    subCounty: "Nsumba",
    parish: "Nsumba",
    urgency: "critical",
    scheduledDate: TODAY_ISO,
    scheduledTimeLabel: "Afternoon",
    purpose: "Check whether teachers are applying strategies from last month's literacy training.",
    ssaAreaAddressed: "Teaching & Learning",
    facilitator: "Ruth Kabuye (BFEP)",
    staffMonitorName: "Sarah Nanyongo (CCEO)",
    status: "ready_to_start",
    evidenceChecklist: checklist([
      { label: "Visit report",                       critical: true, status: "missing" },
      { label: "Staff met",                          critical: true, status: "missing" },
      { label: "What changed since last support",    status: "missing" },
      { label: "Next action agreed",                 status: "missing" },
      { label: "Follow-Up recommendation",           status: "missing" },
    ]),
    missingEvidenceCount: 5,
    criticalMissingCount: 2,
    evidenceCompletenessScore: 0,
    primaryActionLabel: "Start Visit",
    secondaryActionLabel: "Open Evidence Checklist",
    href: "/partner/today/TODO-002",
  },
  // 3. Coaching visit at Victory Primary — medium, scheduled
  {
    id: "TODO-003",
    partnerId: "P-BFEP",
    taskType: "coaching_visit",
    schoolId: "SCH-VICT",
    schoolName: "Victory Primary School",
    district: "Kayunga",
    subCounty: "Kayunga Central",
    parish: "Kayunga",
    urgency: "medium",
    scheduledDate: TODAY_ISO,
    scheduledTimeLabel: "2:00 PM - 4:00 PM",
    purpose: "Coach school leader on classroom observation routines.",
    ssaAreaAddressed: "Leadership",
    facilitator: "Joseph Nsubuga (BFEP)",
    staffMonitorName: "Sarah Nanyongo (CCEO)",
    status: "scheduled",
    evidenceChecklist: checklist([
      { label: "Coaching report",   critical: true, status: "missing" },
      { label: "Person coached",    critical: true, status: "missing" },
      { label: "Coaching topic",    status: "missing" },
      { label: "Action agreed",     status: "missing" },
      { label: "Follow-Up date",    status: "missing" },
    ]),
    missingEvidenceCount: 5,
    criticalMissingCount: 2,
    evidenceCompletenessScore: 0,
    primaryActionLabel: "Start Coaching",
    secondaryActionLabel: "View Details",
    href: "/partner/today/TODO-003",
  },
  // 4. Resource delivery at Namilyango — happens today, partially done
  {
    id: "TODO-004",
    partnerId: "P-BFEP",
    taskType: "resource_delivery",
    schoolId: "SCH-NAMI",
    schoolName: "Namilyango Primary",
    district: "Mukono",
    subCounty: "Namilyango",
    parish: "Namilyango",
    urgency: "low",
    scheduledDate: TODAY_ISO,
    scheduledTimeLabel: "Drop-off 8:30 AM",
    purpose: "Deliver Grade 4-5 numeracy kits requested after April SSA cycle.",
    ssaAreaAddressed: "Resources",
    facilitator: "Simon Otim (BFEP)",
    staffMonitorName: "Sarah Nanyongo (CCEO)",
    status: "submitted",
    evidenceChecklist: checklist([
      { label: "Delivery note",        critical: true, status: "uploaded" },
      { label: "Recipient signature",  critical: true, status: "uploaded" },
      { label: "Resource quantities",  status: "uploaded" },
      { label: "Photo of delivery",    required: false, status: "uploaded" },
    ]),
    missingEvidenceCount: 0,
    criticalMissingCount: 0,
    evidenceCompletenessScore: 100,
    primaryActionLabel: "View Status",
    href: "/partner/today/TODO-004",
  },
  // 5. Returned correction — must be cleared today
  {
    id: "TODO-005",
    partnerId: "P-BFEP",
    taskType: "correction",
    schoolId: "SCH-KIREKA",
    schoolName: "Kireka Primary School",
    district: "Mukono",
    subCounty: "Kireka",
    parish: "Kireka",
    urgency: "high",
    scheduledDate: TODAY_ISO,
    purpose: "Re-upload attendance sheet showing teacher names, school, date, and facilitator.",
    ssaAreaAddressed: "Teaching & Learning",
    status: "returned_for_correction",
    evidenceChecklist: checklist([
      { label: "Attendance sheet (corrected)", critical: true, status: "missing" },
    ]),
    missingEvidenceCount: 1,
    criticalMissingCount: 1,
    evidenceCompletenessScore: 60,
    returnedBy: "Sarah Nanyongo (CCEO)",
    returnReason: "Attendance sheet is missing teacher names.",
    reviewerComment: "Upload a corrected attendance sheet showing teacher names, school, date, and facilitator.",
    correctionDueDate: TODAY_ISO,
    primaryActionLabel: "Correct Submission",
    href: "/partner/today/TODO-005",
  },
];

// ────────── Payment blockers ──────────
//
// Surfaced separately so the partner sees what's blocking payment
// even when the activity already happened.

export type TodayPaymentBlocker = {
  id: string;
  activityLabel: string;
  schoolName: string;
  missing: string[];
  amountUgxWaiting: number;
};

export const todayPaymentBlockers: TodayPaymentBlocker[] = [
  {
    id: "PB-1",
    activityLabel: "Hope Primary training",
    schoolName: "Hope Primary School",
    missing: ["Attendance sheet", "Partner debrief"],
    amountUgxWaiting: 380_000,
  },
  {
    id: "PB-2",
    activityLabel: "Grace Primary follow-up",
    schoolName: "Grace Primary School",
    missing: ["Visit report", "Follow-Up recommendation"],
    amountUgxWaiting: 350_000,
  },
];

// ────────── Done for today checklist ──────────

export const doneForTodayPartner = [
  { id: "dft-1", label: "All scheduled activities completed", done: false },
  { id: "dft-2", label: "All reports submitted",              done: false },
  { id: "dft-3", label: "Required evidence uploaded",         done: false },
  { id: "dft-4", label: "Corrections due today cleared",      done: false },
  { id: "dft-5", label: "Tomorrow's schedule reviewed",       done: true  },
];

// ────────── Helpers ──────────

export function todaySummary() {
  const activitiesToday = partnerTodayTasks.filter((t) => t.taskType !== "correction").length;
  const evidenceRequired = partnerTodayTasks.filter(
    (t) => t.taskType !== "correction" && t.missingEvidenceCount > 0,
  ).length;
  const correctionsDue = partnerTodayTasks.filter(
    (t) => t.taskType === "correction" && t.correctionDueDate === TODAY_ISO,
  ).length;
  const awaitingConfirmation = partnerTodayTasks.filter(
    (t) => t.status === "submitted" || t.status === "awaiting_cceo_confirmation",
  ).length;
  const overdue = partnerTodayTasks.filter((t) => t.status === "overdue").length;
  return { activitiesToday, evidenceRequired, correctionsDue, awaitingConfirmation, overdue };
}

// Priority sort: overdue → critical → earliest time today → payment-blocker → corrections-due-today → normal.
// Returns a new array so callers don't mutate the source.
export function sortTodayTasks(tasks: PartnerTodayTask[]): PartnerTodayTask[] {
  const urgencyRank: Record<PartnerTodayUrgency, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  const statusRank = (s: PartnerTodayStatus): number => {
    if (s === "overdue") return 0;
    if (s === "returned_for_correction") return 1;
    if (s === "ready_to_start" || s === "in_progress") return 2;
    if (s === "report_needed" || s === "evidence_needed") return 3;
    if (s === "scheduled") return 4;
    if (s === "submitted" || s === "awaiting_cceo_confirmation") return 5;
    if (s === "completed_today") return 6;
    return 7;
  };
  return [...tasks].sort((a, b) => {
    const sa = statusRank(a.status);
    const sb = statusRank(b.status);
    if (sa !== sb) return sa - sb;
    if (urgencyRank[a.urgency] !== urgencyRank[b.urgency]) {
      return urgencyRank[a.urgency] - urgencyRank[b.urgency];
    }
    return (a.scheduledTimeLabel ?? "").localeCompare(b.scheduledTimeLabel ?? "");
  });
}

export const TASK_TYPE_LABEL: Record<PartnerTodayTaskType, string> = {
  training:              "Teacher Training",
  in_school_training:    "In-School Training",
  follow_up_visit:       "Follow-Up Visit",
  coaching_visit:        "Coaching Visit",
  classroom_observation: "Classroom Observation",
  ssa_support_visit:     "SSA Support Visit",
  resource_delivery:     "Resource Delivery",
  joint_visit:           "Joint Visit (with CCEO)",
  reflection_debrief:    "Reflection / Debrief",
  evidence_upload:       "Evidence Upload",
  correction:            "Correction",
};

export const STATUS_LABEL: Record<PartnerTodayStatus, string> = {
  scheduled:                  "Scheduled",
  ready_to_start:             "Ready to start",
  in_progress:                "In progress",
  report_needed:              "Report needed",
  evidence_needed:            "Evidence needed",
  submitted:                  "Submitted",
  awaiting_cceo_confirmation: "Awaiting CCEO confirmation",
  returned_for_correction:    "Returned for correction",
  completed_today:            "Completed today",
  overdue:                    "Overdue",
};
