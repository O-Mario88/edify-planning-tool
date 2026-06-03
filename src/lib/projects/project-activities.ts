// Project activities — the execution layer for special projects (spec §11/§21).
//
// A project activity is one delivered (or planned) unit of work tied to a
// project AND a school/cluster: a training, a follow-up visit, a coaching
// visit, an assessment, etc. Activities follow the same evidence → Salesforce
// → IA verification → payment workflow as core SSA activities, but stay
// project-scoped.
//
// Salesforce rules (spec §12): visits use SV-, trainings/cluster sessions use
// TS-. Mutable in-memory store; Year-2 backend swap = project_activities table.

import type { SsaInterventionArea } from "@/lib/planning/planning-gaps-mock";

export type ProjectActivityType =
  | "Project Training"
  | "Project Follow-Up Visit"
  | "Project Coaching Visit"
  | "Project In-School Support"
  | "Project Assessment"
  | "Project Cluster Session"
  | "Project Partner Support"
  | "Project Evidence Review"
  | "Project Closeout Visit";

export type ProjectActivityStatus = "Planned" | "In Progress" | "Completed" | "Cancelled";
export type ProjectEvidenceStatus = "Not Required" | "Pending" | "Submitted" | "Verified" | "Returned";
export type ProjectIaStatus = "Not Submitted" | "Submitted" | "Confirmed" | "Returned";
export type ProjectDeliveryType = "staff" | "partner";
export type SalesforceActivityType = "visit" | "training";

export type ProjectActivity = {
  id: string;
  projectId: string;
  schoolId?: string;
  clusterId?: string;
  activityType: ProjectActivityType;
  interventionId: SsaInterventionArea;
  deliveryType: ProjectDeliveryType;
  staffId?: string;
  staffName?: string;
  partnerId?: string;
  partnerName?: string;
  // Timing — a visit may carry month/week, a training an exact date.
  scheduledDate?: string;
  plannedWeek?: string;
  plannedMonth?: string;
  participantEstimate?: number;
  topic?: string;
  // Attendance breakdown (actuals, captured at completion — not estimates).
  // Used by project reach analytics; never counted for planned activities.
  teachersTrained?: number;
  schoolLeadersTrained?: number;
  attendanceVerified?: boolean;
  status: ProjectActivityStatus;
  evidenceStatus: ProjectEvidenceStatus;
  salesforceActivityId?: string;
  salesforceActivityType?: SalesforceActivityType;
  iaVerificationStatus: ProjectIaStatus;
  paymentRequestId?: string;
  createdAt: string;
  updatedAt: string;
};

// ── Salesforce id rules (spec §12) ──

/** Which Salesforce prefix an activity type requires. Cluster sessions and
 *  trainings are logged as trainings (TS-); everything visit-like is SV-. */
export function salesforceTypeFor(activityType: ProjectActivityType): SalesforceActivityType {
  switch (activityType) {
    case "Project Training":
    case "Project Cluster Session":
      return "training";
    default:
      return "visit";
  }
}

export function salesforcePrefixFor(t: SalesforceActivityType): "TS-" | "SV-" {
  return t === "training" ? "TS-" : "SV-";
}

/** Validate a Salesforce id against the activity's required prefix. */
export function validateSalesforceId(
  id: string,
  activityType: ProjectActivityType,
): { ok: true } | { ok: false; reason: string } {
  const required = salesforcePrefixFor(salesforceTypeFor(activityType));
  if (!id.trim()) return { ok: false, reason: "Salesforce ID is required." };
  if (!id.trim().toUpperCase().startsWith(required)) {
    return { ok: false, reason: `${activityType} must use a ${required} Salesforce ID.` };
  }
  return { ok: true };
}

// ── Store ──

export const projectActivities: ProjectActivity[] = [
  {
    id: "PAC-0001", projectId: "SP-EDTECH", schoolId: "40118",
    activityType: "Project Training", interventionId: "Education Technology",
    deliveryType: "partner", partnerId: "PRT-WV", partnerName: "World Vision",
    scheduledDate: "2025-06-18", participantEstimate: 22, topic: "Classroom tablet integration",
    teachersTrained: 18, schoolLeadersTrained: 3, attendanceVerified: true,
    status: "Completed", evidenceStatus: "Verified",
    salesforceActivityId: "TS-2025-04471", salesforceActivityType: "training",
    iaVerificationStatus: "Confirmed", createdAt: "2025-06-01", updatedAt: "2025-06-20",
  },
  {
    id: "PAC-0002", projectId: "SP-EDTECH", schoolId: "40118",
    activityType: "Project Follow-Up Visit", interventionId: "Education Technology",
    deliveryType: "partner", partnerId: "PRT-WV", partnerName: "World Vision",
    plannedMonth: "2026-05", topic: "Post-training usage check",
    status: "Completed", evidenceStatus: "Submitted",
    salesforceActivityId: "SV-2026-01180", salesforceActivityType: "visit",
    iaVerificationStatus: "Submitted", createdAt: "2026-04-20", updatedAt: "2026-05-21",
  },
  {
    id: "PAC-0003", projectId: "SP-CCSEL", schoolId: "32791",
    activityType: "Project Training", interventionId: "Christlike Behaviour",
    deliveryType: "partner", partnerId: "PRT-CI", partnerName: "Compassion Int.",
    scheduledDate: "2025-07-09", participantEstimate: 18, topic: "Christ-centred SEL facilitation",
    teachersTrained: 14, schoolLeadersTrained: 2, attendanceVerified: true,
    status: "Completed", evidenceStatus: "Verified",
    salesforceActivityId: "TS-2025-04822", salesforceActivityType: "training",
    iaVerificationStatus: "Confirmed", createdAt: "2025-06-25", updatedAt: "2025-07-12",
  },
  {
    id: "PAC-0004", projectId: "SP-CCSEL", schoolId: "32791",
    activityType: "Project Follow-Up Visit", interventionId: "Christlike Behaviour",
    deliveryType: "staff", staffId: "STF-PC-001", staffName: "Paul Chinyama",
    plannedMonth: "2026-05",
    status: "Planned", evidenceStatus: "Pending",
    iaVerificationStatus: "Not Submitted", createdAt: "2026-04-30", updatedAt: "2026-04-30",
  },
];

let activitySeq = projectActivities.length;

export type CreateProjectActivityInput = {
  projectId: string;
  schoolId?: string;
  clusterId?: string;
  activityType: ProjectActivityType;
  interventionId: SsaInterventionArea;
  deliveryType: ProjectDeliveryType;
  staffId?: string;
  staffName?: string;
  partnerId?: string;
  partnerName?: string;
  scheduledDate?: string;
  plannedWeek?: string;
  plannedMonth?: string;
  participantEstimate?: number;
  topic?: string;
  teachersTrained?: number;
  schoolLeadersTrained?: number;
  salesforceActivityId?: string;
  now?: string;
};

export function createProjectActivity(
  input: CreateProjectActivityInput,
): { ok: true; activity: ProjectActivity } | { ok: false; reason: string } {
  if (!input.scheduledDate && !input.plannedWeek && !input.plannedMonth) {
    return { ok: false, reason: "Give the activity a date, week, or month." };
  }
  const sfType = salesforceTypeFor(input.activityType);
  if (input.salesforceActivityId) {
    const v = validateSalesforceId(input.salesforceActivityId, input.activityType);
    if (!v.ok) return { ok: false, reason: v.reason };
  }
  activitySeq += 1;
  const now = input.now ?? "2026-06-03";
  const activity: ProjectActivity = {
    id: `PAC-${String(activitySeq).padStart(4, "0")}`,
    projectId: input.projectId,
    schoolId: input.schoolId,
    clusterId: input.clusterId,
    activityType: input.activityType,
    interventionId: input.interventionId,
    deliveryType: input.deliveryType,
    staffId: input.staffId,
    staffName: input.staffName,
    partnerId: input.partnerId,
    partnerName: input.partnerName,
    scheduledDate: input.scheduledDate,
    plannedWeek: input.plannedWeek,
    plannedMonth: input.plannedMonth,
    participantEstimate: input.participantEstimate,
    topic: input.topic,
    teachersTrained: input.teachersTrained,
    schoolLeadersTrained: input.schoolLeadersTrained,
    status: "Planned",
    evidenceStatus: "Pending",
    salesforceActivityId: input.salesforceActivityId,
    salesforceActivityType: input.salesforceActivityId ? sfType : undefined,
    iaVerificationStatus: input.salesforceActivityId ? "Submitted" : "Not Submitted",
    createdAt: now,
    updatedAt: now,
  };
  projectActivities.unshift(activity);
  return { ok: true, activity };
}

export function activitiesForProject(projectId: string): ProjectActivity[] {
  return projectActivities.filter((a) => a.projectId === projectId);
}

export function activitiesForSchool(schoolId: string): ProjectActivity[] {
  return projectActivities.filter((a) => a.schoolId === schoolId);
}

export function activitiesForProjectSchool(projectId: string, schoolId: string): ProjectActivity[] {
  return projectActivities.filter((a) => a.projectId === projectId && a.schoolId === schoolId);
}
