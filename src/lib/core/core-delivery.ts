// Core delivery + payment projections, role-scoped through coreBoardData.
//  • Accountant surface: core activities tied to payment/accountability (§21).
//  • Partner surface: the partner's own assigned core activities (§21).

import "server-only";
import type { EdifyRole } from "@/lib/auth-public";
import { coreBoardData } from "./core-board";
import type { CoreActivitySlot } from "./core-types";

export type CoreDeliveryRow = {
  slotId: string;
  schoolId: string;
  schoolName: string;
  district: string;
  activity: string;          // "Visit 2" / "Training 1"
  intervention: string;
  partnerName?: string;
  slotStatus: CoreActivitySlot["status"];
  iaStatus: string;          // Verified | Pending | —
  accountantStatus: string;  // Confirmed | Pending
  salesforceId?: string;
  paymentDue: boolean;       // IA-verified partner work not yet accountant-confirmed
};

function rowOf(s: CoreActivitySlot, schoolName: string, district: string): CoreDeliveryRow {
  const ia = s.iaVerificationStatus ?? "—";
  const acc = s.accountantStatus ?? "Pending";
  return {
    slotId: s.id,
    schoolId: s.schoolId,
    schoolName,
    district,
    activity: `${s.activityType === "visit" ? "Visit" : "Training"} ${s.sequenceNumber}`,
    intervention: s.intervention,
    partnerName: s.assignedPartnerName,
    slotStatus: s.status,
    iaStatus: ia,
    accountantStatus: acc,
    salesforceId: s.salesforceId,
    paymentDue: ia === "Verified" && !!s.assignedPartnerId && acc !== "Confirmed",
  };
}

/** Partner-delivered core activities relevant to payment/accountability. */
export function coreDeliveryRows(staffId: string, role: EdifyRole): CoreDeliveryRow[] {
  const cards = coreBoardData(staffId, role);
  const rows: CoreDeliveryRow[] = [];
  for (const c of cards) {
    for (const s of c.slots) {
      if (!s.assignedPartnerId) continue;
      rows.push(rowOf(s, c.schoolName, c.district));
    }
  }
  // Payment-due first, then by school.
  return rows.sort((a, b) => Number(b.paymentDue) - Number(a.paymentDue) || a.schoolName.localeCompare(b.schoolName));
}

export function coreDeliverySummary(rows: CoreDeliveryRow[]) {
  return {
    total: rows.length,
    paymentDue: rows.filter((r) => r.paymentDue).length,
    confirmed: rows.filter((r) => r.accountantStatus === "Confirmed").length,
    awaitingIa: rows.filter((r) => r.iaStatus !== "Verified").length,
  };
}

/** Every partner-assigned core activity (the partner's own work list). */
export function corePartnerRows(staffId: string, role: EdifyRole): CoreDeliveryRow[] {
  const cards = coreBoardData(staffId, role);
  const rows: CoreDeliveryRow[] = [];
  for (const c of cards) {
    for (const s of c.slots) {
      if (s.owner !== "partner" && s.owner !== "partner_facilitator" && !s.assignedPartnerId) continue;
      rows.push(rowOf(s, c.schoolName, c.district));
    }
  }
  return rows.sort((a, b) => a.schoolName.localeCompare(b.schoolName));
}
