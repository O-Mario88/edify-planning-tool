// Core package delivery split — the 2-staff / 2-partner rule (spec §11).
//
// A core package is 4 visits + 4 trainings, and the delivery MUST split evenly:
// 2 visits by staff + 2 by partner, 2 trainings by staff + 2 by partner. This
// pure helper derives the split from the activity slots so the detail page, the
// board, and analytics all read one truth. Pure (no server-only) so client
// components can render it from slot data passed as props.

import type { CoreActivitySlot } from "./core-types";

export const STAFF_VISITS_TARGET = 2;
export const PARTNER_VISITS_TARGET = 2;
export const STAFF_TRAININGS_TARGET = 2;
export const PARTNER_TRAININGS_TARGET = 2;

export type DeliveryClass = "staff" | "partner" | "unassigned";

/** Classify a slot's delivery owner. "myself"/"staff" → staff; partner* → partner. */
export function deliveryClassOf(slot: CoreActivitySlot): DeliveryClass {
  if (slot.owner === "partner" || slot.owner === "partner_facilitator" || slot.assignedPartnerId) return "partner";
  if (slot.owner === "myself" || slot.owner === "staff" || slot.assignedStaffId) return "staff";
  return "unassigned";
}

export type SplitCell = {
  /** Slots assigned to this delivery class (owner decided). */
  assigned: number;
  /** Assigned slots that are fully Completed. */
  completed: number;
  /** Required count (2). */
  target: number;
};

export type CoreDeliverySplit = {
  staffVisits: SplitCell;
  partnerVisits: SplitCell;
  staffTrainings: SplitCell;
  partnerTrainings: SplitCell;
  totalVisits: { completed: number; target: number };
  totalTrainings: { completed: number; target: number };
  /** True when assignment matches the 2/2 split exactly on both visit + training. */
  balanced: boolean;
  /** Human-readable split problems (over-assigned / under-assigned a class). */
  warnings: string[];
};

const DONE = "Completed";

function cell(slots: CoreActivitySlot[], type: "visit" | "training", cls: DeliveryClass, target: number): SplitCell {
  const of = slots.filter((s) => s.activityType === type && deliveryClassOf(s) === cls);
  return { assigned: of.length, completed: of.filter((s) => s.status === DONE).length, target };
}

export function coreDeliverySplit(slots: CoreActivitySlot[]): CoreDeliverySplit {
  const staffVisits = cell(slots, "visit", "staff", STAFF_VISITS_TARGET);
  const partnerVisits = cell(slots, "visit", "partner", PARTNER_VISITS_TARGET);
  const staffTrainings = cell(slots, "training", "staff", STAFF_TRAININGS_TARGET);
  const partnerTrainings = cell(slots, "training", "partner", PARTNER_TRAININGS_TARGET);

  const visitsCompleted = slots.filter((s) => s.activityType === "visit" && s.status === DONE).length;
  const trainingsCompleted = slots.filter((s) => s.activityType === "training" && s.status === DONE).length;

  const warnings: string[] = [];
  const check = (c: SplitCell, label: string) => {
    if (c.assigned > c.target) warnings.push(`${c.assigned} ${label} assigned — only ${c.target} allowed.`);
  };
  check(staffVisits, "staff visits");
  check(partnerVisits, "partner visits");
  check(staffTrainings, "staff trainings");
  check(partnerTrainings, "partner trainings");

  const balanced =
    staffVisits.assigned === STAFF_VISITS_TARGET &&
    partnerVisits.assigned === PARTNER_VISITS_TARGET &&
    staffTrainings.assigned === STAFF_TRAININGS_TARGET &&
    partnerTrainings.assigned === PARTNER_TRAININGS_TARGET;

  return {
    staffVisits,
    partnerVisits,
    staffTrainings,
    partnerTrainings,
    totalVisits: { completed: visitsCompleted, target: STAFF_VISITS_TARGET + PARTNER_VISITS_TARGET },
    totalTrainings: { completed: trainingsCompleted, target: STAFF_TRAININGS_TARGET + PARTNER_TRAININGS_TARGET },
    balanced,
    warnings,
  };
}
