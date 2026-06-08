// Partner-monitoring view types + tab config (no fake data — purge migration).
// In production the rows are a SQL view joining partner_activities,
// partner_evidence, payment_requests + the SLA delay-detection job. Until that
// backend lands, the rows/alerts are empty and the UI shows an empty state.

import type { PartnerWorkflowStatus } from "./partner-workflow";

export type StaffMonitorTabKey =
  | "assigned" | "scheduled" | "delayed" | "dueThisWeek"
  | "evidenceSubmitted" | "needsMyConfirmation" | "paymentPending" | "completed";

export type StaffMonitorTab = { key: StaffMonitorTabKey; label: string; count: number };

export type StaffMonitorRow = {
  id: string; school: string; district: string; partner: string;
  activity: string; activitySub: string; status: PartnerWorkflowStatus;
  scheduledWeek?: string; delayDays?: number; amountUgx?: number;
};

export type DelayAlert = { id: string; message: string; recommendedAction: string; severity: "warn" | "danger" };

// Tab labels are stable UI config; counts come from the (currently empty) rows.
export const staffMonitorTabs: StaffMonitorTab[] = [
  { key: "assigned", label: "Assigned to Partner", count: 0 },
  { key: "scheduled", label: "Scheduled by Partner", count: 0 },
  { key: "delayed", label: "Delayed", count: 0 },
  { key: "dueThisWeek", label: "Due This Week", count: 0 },
  { key: "evidenceSubmitted", label: "Evidence Submitted", count: 0 },
  { key: "needsMyConfirmation", label: "Needs My Confirmation", count: 0 },
  { key: "paymentPending", label: "Payment Pending", count: 0 },
  { key: "completed", label: "Completed", count: 0 },
];

// No backend partner-monitoring source yet — empty, never fabricated.
export const staffMonitorRows: StaffMonitorRow[] = [];
export const delayAlerts: DelayAlert[] = [];
export const monitorEvidenceLink: Record<string, string> = {};
