// Partner monitoring — what the CCEO/staff sees about the partner
// work they assigned. Mirrors the workflow state machine in
// partner-workflow.ts. In production these rows would be a SQL view
// joining partner_activities, partner_evidence, payment_requests,
// and the SLA delay-detection job.

import type { PartnerWorkflowStatus } from "./partner-workflow";

export type StaffMonitorTabKey =
  | "assigned"
  | "scheduled"
  | "delayed"
  | "dueThisWeek"
  | "evidenceSubmitted"
  | "needsMyConfirmation"
  | "paymentPending"
  | "completed";

export type StaffMonitorTab = {
  key: StaffMonitorTabKey;
  label: string;
  count: number;
};

export type StaffMonitorRow = {
  id: string;
  school: string;
  district: string;
  partner: string;
  activity: string;
  activitySub: string;
  status: PartnerWorkflowStatus;
  scheduledWeek?: string;
  delayDays?: number;
  amountUgx?: number;
};

export const staffMonitorTabs: StaffMonitorTab[] = [
  { key: "assigned",            label: "Assigned to Partner",   count: 7 },
  { key: "scheduled",           label: "Scheduled by Partner",  count: 5 },
  { key: "delayed",             label: "Delayed",               count: 2 },
  { key: "dueThisWeek",         label: "Due This Week",         count: 4 },
  { key: "evidenceSubmitted",   label: "Evidence Submitted",    count: 6 },
  { key: "needsMyConfirmation", label: "Needs My Confirmation", count: 3 },
  { key: "paymentPending",      label: "Payment Pending",       count: 5 },
  { key: "completed",           label: "Completed",             count: 22 },
];

export const staffMonitorRows: StaffMonitorRow[] = [
  // Needs My Confirmation
  {
    id: "MON-001", school: "Hope Primary School", district: "Mukono",
    partner: "Bright Future Education Partners",
    activity: "Follow-Up coaching visit", activitySub: "Literacy support",
    status: "AwaitingCceoConfirmation",
    amountUgx: 350_000,
  },
  {
    id: "MON-002", school: "Kireka Primary School", district: "Mukono",
    partner: "Bright Future Education Partners",
    activity: "Teacher Training Debrief", activitySub: "P3 Literacy",
    status: "AwaitingCceoConfirmation",
    amountUgx: 280_000,
  },
  {
    id: "MON-003", school: "Namilyango Primary", district: "Mukono",
    partner: "Bright Future Education Partners",
    activity: "Classroom Observation", activitySub: "Numeracy",
    status: "AwaitingCceoConfirmation",
    amountUgx: 220_000,
  },
  // Delayed
  {
    id: "MON-004", school: "Maple Grove Primary", district: "Kayunga",
    partner: "Bright Future Education Partners",
    activity: "Coaching Visit", activitySub: "Literacy follow-up",
    status: "Delayed",
    delayDays: 5,
  },
  {
    id: "MON-005", school: "Sunrise Junior School", district: "Mukono",
    partner: "Literacy Training Uganda",
    activity: "In-School Training", activitySub: "Reading fluency",
    status: "Delayed",
    delayDays: 10,
  },
  // Scheduled
  {
    id: "MON-006", school: "Grace Primary School", district: "Mukono",
    partner: "Bright Future Education Partners",
    activity: "Follow-Up Visit", activitySub: "Math improvement",
    status: "ScheduledByPartner",
    scheduledWeek: "Week 3 · May 16",
  },
  {
    id: "MON-007", school: "St. Mary's Primary", district: "Kayunga",
    partner: "Bright Future Education Partners",
    activity: "Support Visit", activitySub: "School leadership",
    status: "ScheduledByPartner",
    scheduledWeek: "Week 3 · May 17",
  },
  // Evidence Submitted (awaiting CCEO too — overlap by design)
  {
    id: "MON-008", school: "Hilltop Basic School", district: "Mukono",
    partner: "Numeracy First",
    activity: "Resource Delivery", activitySub: "Learning materials",
    status: "EvidenceSubmitted",
    amountUgx: 180_000,
  },
  // Payment pipeline — CCEO confirm → PL approval → IA verification →
  // accountant. One row per stage so the staff can see exactly which
  // approver a partner payment is waiting on.
  {
    id: "MON-009", school: "Riverside Primary", district: "Mukono",
    partner: "Bright Future Education Partners",
    activity: "Follow-Up Visit", activitySub: "Literacy support",
    status: "ConfirmedByCceo",
    amountUgx: 350_000,
  },
  {
    id: "MON-010", school: "St. Andrew's Primary", district: "Kayunga",
    partner: "Bright Future Education Partners",
    activity: "In-School Training", activitySub: "Numeracy fluency",
    status: "AwaitingPlApproval",
    amountUgx: 420_000,
  },
  {
    id: "MON-011", school: "Good Shepherd Primary", district: "Mukono",
    partner: "Literacy Training Uganda",
    activity: "Coaching Visit", activitySub: "Reading support",
    status: "AwaitingIaVerification",
    amountUgx: 310_000,
  },
  {
    id: "MON-012", school: "Trinity Junior School", district: "Kayunga",
    partner: "Bright Future Education Partners",
    activity: "Classroom Observation", activitySub: "P4 Literacy",
    status: "IaVerified",
    amountUgx: 260_000,
  },
  {
    id: "MON-013", school: "Canaan Primary School", district: "Mukono",
    partner: "Numeracy First",
    activity: "Follow-Up Visit", activitySub: "Leadership support",
    status: "SentToAccountant",
    amountUgx: 300_000,
  },
];

// Map a monitor row to its evidence summary so the CCEO sees the
// completeness % and critical-missing count alongside their Confirm
// CTA. Keeps the staff dashboard reading from the same evidence
// engine as the partner dashboard — single source of truth.
export const monitorEvidenceLink: Record<string, string> = {
  "MON-001": "EVA-001", // Hope Primary
  "MON-002": "EVA-003", // Kireka — returned
  "MON-003": "EVA-002", // Namilyango / Grace partial
};

// Delay-detection alerts. Computed server-side from SLA rules in
// production; flat list here for the demo.
export type DelayAlert = {
  id: string;
  message: string;
  recommendedAction: string;
  severity: "warn" | "danger";
};

export const delayAlerts: DelayAlert[] = [
  {
    id: "DLY-1",
    message: "Maple Grove follow-up coaching visit not scheduled after 5 days.",
    recommendedAction: "Send reminder to Bright Future Education Partners or reassign.",
    severity: "warn",
  },
  {
    id: "DLY-2",
    message: "Sunrise Junior in-school training scheduled date passed 10 days ago.",
    recommendedAction: "Contact LTU partner or reassign activity.",
    severity: "danger",
  },
];
