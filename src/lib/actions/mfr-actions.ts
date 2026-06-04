"use server";

// Monthly Fund Request approval-chain transitions (PL → CD → RVP → Accountant).
// Canonical Bucket-C shape: resolve actor, gate by role + current status,
// validate the requested target is a legal transition, persist, emit one audit
// row + notify the next role, revalidate, return a discriminated union.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import {
  PL_ACTION_STATUSES,
  CD_ACTION_STATUSES,
  RVP_ACTION_STATUSES,
  MFR_STATUS_LABEL,
  type MonthlyFundRequestStatus,
} from "@/lib/funds/monthly-fund-request-types";
import { mfrStatus, setMfrStatus } from "@/lib/funds/mfr-status-store";
import { emitAudit, emitNotificationFanOut } from "./audit";

export type MfrTransitionResult =
  | { ok: true; fundRequestId: string; newStatus: MonthlyFundRequestStatus }
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "INVALID_STATE"; current: MonthlyFundRequestStatus }
  | { ok: false; reason: "INVALID_TRANSITION" };

// Which current statuses each role may act from (mirrors the header gating).
const ROLE_CURRENT: Record<string, ReadonlySet<MonthlyFundRequestStatus>> = {
  CountryProgramLead: PL_ACTION_STATUSES,
  CountryDirector:    CD_ACTION_STATUSES,
  RVP:                RVP_ACTION_STATUSES,
  Admin: new Set<MonthlyFundRequestStatus>([
    ...PL_ACTION_STATUSES, ...CD_ACTION_STATUSES, ...RVP_ACTION_STATUSES,
  ]),
};

// Legal targets from each current status (the state machine).
const ALLOWED_TARGETS: Partial<Record<MonthlyFundRequestStatus, ReadonlySet<MonthlyFundRequestStatus>>> = {
  AUTO_GENERATED:   new Set(["SUBMITTED_TO_CD", "AUTO_GENERATED"]),
  UNDER_PL_REVIEW:  new Set(["SUBMITTED_TO_CD", "AUTO_GENERATED"]),
  RETURNED_TO_PL:   new Set(["SUBMITTED_TO_CD", "AUTO_GENERATED"]),
  SUBMITTED_TO_CD:  new Set(["SUBMITTED_TO_RVP", "RETURNED_TO_PL"]),
  RETURNED_TO_CD:   new Set(["SUBMITTED_TO_RVP", "RETURNED_TO_PL"]),
  SUBMITTED_TO_RVP: new Set(["RVP_APPROVED", "RETURNED_TO_CD", "ON_HOLD"]),
  ON_HOLD:          new Set(["RVP_APPROVED", "RETURNED_TO_CD"]),
};

// Who to notify when a transition lands on a given target status.
const NOTIFY: Partial<Record<MonthlyFundRequestStatus, string[]>> = {
  SUBMITTED_TO_CD:  ["COUNTRY_DIRECTOR"],
  SUBMITTED_TO_RVP: ["RVP"],
  RVP_APPROVED:     ["PROGRAM_ACCOUNTANT"],
  RETURNED_TO_PL:   ["PROGRAM_LEAD"],
  RETURNED_TO_CD:   ["COUNTRY_DIRECTOR"],
  AUTO_GENERATED:   ["PROGRAM_LEAD"],
  ON_HOLD:          ["COUNTRY_DIRECTOR", "PROGRAM_LEAD"],
};

// Default chain head when the artifact has never been acted on this session.
const DEFAULT_STATUS: MonthlyFundRequestStatus = "UNDER_PL_REVIEW";

export async function transitionMonthlyFundRequest(
  fundRequestId: string,
  target: MonthlyFundRequestStatus,
  note?: string,
): Promise<MfrTransitionResult> {
  const user = await getCurrentUser();
  const allowedFrom = ROLE_CURRENT[user.role];
  if (!allowedFrom) return { ok: false, reason: "FORBIDDEN" };

  const current = mfrStatus(fundRequestId) ?? DEFAULT_STATUS;
  if (!allowedFrom.has(current)) return { ok: false, reason: "INVALID_STATE", current };

  const legal = ALLOWED_TARGETS[current];
  if (!legal || !legal.has(target)) return { ok: false, reason: "INVALID_TRANSITION" };

  setMfrStatus(fundRequestId, target, { id: user.staffId, name: user.name }, note?.trim() || undefined);

  emitAudit({
    action: "monthlyFundRequest.transitioned",
    subjectKind: "MonthlyFundRequest",
    subjectId: fundRequestId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { from: current, to: target, note: note?.trim() || undefined },
  });

  const recipients = NOTIFY[target];
  if (recipients?.length) {
    emitNotificationFanOut(recipients, {
      template: "monthlyFundRequest.transitioned",
      channel: "Inbox",
      title: `Monthly Fund Request: ${MFR_STATUS_LABEL[target]}`,
      body: `${user.name} moved the country monthly fund request to "${MFR_STATUS_LABEL[target]}".`,
      href: "/monthly-fund-request",
    });
  }

  try {
    revalidatePath("/monthly-fund-request");
    revalidatePath("/approvals");
    revalidatePath("/disbursements");
    revalidatePath("/notifications");
  } catch {
    /* outside request scope — fine */
  }

  return { ok: true, fundRequestId, newStatus: target };
}
