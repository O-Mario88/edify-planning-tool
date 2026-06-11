// Mirror Core lifecycle slots into the canonical activities() ledger
// so My Plan, PL Team Plan, Targets, Analytics, and Evidence queues
// see Core work alongside non-Core scheduling. Before this shim, the
// Core lifecycle was a silent parallel store — completing the Core
// 8-slot package never moved the CCEO's pace numbers or showed up on
// the PL's supervised-CCEO row.
//
// Design notes:
//   • idempotent — upserts on (slot.id) so repeated calls are safe
//   • the slot stores the activityId once minted; subsequent updates
//     patch the existing record in-place
//   • status mapping is one-way: a slot moves the activity through the
//     same status union the canonical execution chain uses
//   • partner-delivered slots set deliveryType="partner" so they don't
//     count toward the CCEO's staffSupportLimit (per assignment-policy)

import "server-only";

import {
  activities as activitiesStore,
  type ActivityKind,
  type PlannedActivityRecord,
  type PlannedActivityStatus,
} from "@/lib/actions/store";
import { updateSlot } from "./core-store";
import type { CoreActivitySlot, CoreActivitySlotStatus } from "./core-types";

// Core slot status → canonical activity status. We don't try to mirror
// every nuance (Returned, partner sub-states, etc.) — only the states
// that drive downstream surfaces. Slots in "Not Planned" / unassigned
// owner never enter the activities ledger at all.
const SLOT_STATUS_TO_ACTIVITY: Partial<Record<CoreActivitySlotStatus, PlannedActivityStatus>> = {
  "Planned":                  "Planned",
  "Scheduled":                "Planned",
  "Assigned to Partner":      "Planned",
  "Partner Scheduled":        "Planned",
  "In Progress":              "Planned",
  "Evidence Uploaded":        "SalesforceIdPending",
  "Evidence Accepted":        "SalesforceIdPending",
  "Salesforce ID Required":   "SalesforceIdPending",
  "Awaiting IA Verification": "SubmittedForVerification",
  "IA Verified":              "Verified",
  "Accountant Confirmed":     "AccountabilityClosed",
  "Completed":                "AccountabilityClosed",
  "Returned":                 "Returned",
  "Rejected":                 "Cancelled",
  "Rescheduled":              "Planned",
};

function activityKindFor(slot: CoreActivitySlot): ActivityKind {
  return slot.activityType === "training" ? "CLUSTER_TRAINING" : "SCHOOL_VISIT";
}

function titleFor(slot: CoreActivitySlot, schoolName?: string): string {
  const label = slot.activityType === "training" ? "Core training" : "Core visit";
  const seq = `#${slot.sequenceNumber}`;
  const school = schoolName ?? slot.schoolId;
  return `${label} ${seq} (${slot.intervention}) — ${school}`;
}

/** Mirror a Core slot into the canonical activities() store. Returns
 *  the activityId so the caller can persist it on the slot. Safe to
 *  call repeatedly — the same slot.id always resolves to the same
 *  activity record (creating on first call, patching after). */
export function syncSlotToActivities(
  slot: CoreActivitySlot,
  ctx: { actingStaffId: string; schoolName?: string },
): string {
  const activityStatus = SLOT_STATUS_TO_ACTIVITY[slot.status];
  // Slots that don't carry a meaningful activity state yet (e.g.
  // "Not Planned") shouldn't pollute the activities ledger.
  if (!activityStatus) return slot.activityId ?? "";

  const store = activitiesStore();
  const now = new Date().toISOString();

  // Use the slot's existing activityId, or derive a deterministic one
  // so the upsert is idempotent across server restarts.
  const activityId = slot.activityId ?? `core-${slot.id}`;
  const existing = store.find((a) => a.id === activityId);

  const assigneeId =
    slot.owner === "partner" || slot.owner === "partner_facilitator"
      ? (slot.assignedPartnerId ?? ctx.actingStaffId)
      : (slot.assignedStaffId ?? ctx.actingStaffId);

  const patch: Partial<PlannedActivityRecord> = {
    status:        activityStatus,
    schoolId:      slot.schoolId,
    schoolName:    ctx.schoolName,
    title:         titleFor(slot, ctx.schoolName),
    assigneeId,
    deliveryType:  slot.owner === "partner" || slot.owner === "partner_facilitator" ? "partner" : "staff",
    partnerName:   slot.assignedPartnerName,
    scheduledDate: slot.scheduledMonth, // monthLabel-only scheduling for Core
    weekOfMonth:   slot.scheduledWeek ?? existing?.weekOfMonth ?? 1,
    salesforceId:  slot.salesforceId,
    updatedAt:     now,
  };

  if (existing) {
    Object.assign(existing, patch);
  } else {
    const record: PlannedActivityRecord = {
      id:              activityId,
      planId:          `core-plan-${slot.corePlanId}`,
      schoolId:        slot.schoolId,
      kind:            activityKindFor(slot),
      title:           patch.title!,
      weekOfMonth:     patch.weekOfMonth!,
      scheduledDate:   patch.scheduledDate,
      assigneeId:      assigneeId,
      estCostCents:    0,
      status:          activityStatus,
      schoolName:      ctx.schoolName,
      deliveryType:    patch.deliveryType,
      partnerName:     patch.partnerName,
      salesforceId:    patch.salesforceId,
      rescheduleCount: 0,
      createdAt:       now,
      updatedAt:       now,
    };
    store.push(record);
  }

  // Persist the activityId on the slot once so future updates resolve
  // without recomputing the derived id.
  if (!slot.activityId) {
    updateSlot(slot.id, { activityId });
  }
  return activityId;
}
