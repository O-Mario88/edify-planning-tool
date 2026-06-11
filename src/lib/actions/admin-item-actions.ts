"use server";

// CD admin-item CRUD for the Monthly Fund Request. Persists to the
// server-side admin-item overlay so additions/removals survive reload and
// flow into the budget rollup + grand total (effectiveAdminItems() feeds
// generateMonthlyFundRequest). Canonical Bucket-C shape.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import {
  addAdminItemRecord,
  updateAdminItemRecord,
  removeAdminItemRecord,
  type SeedAdminItem,
} from "@/lib/funds/monthly-fund-request-mock";
import type { AdminBudgetCategory, MfrAdminItem } from "@/lib/funds/monthly-fund-request-types";
import { emitAudit, emitNotificationFanOut } from "./audit";
import { findFundRequest } from "@/lib/actions/store";

// Notify the affected CCEO + PL when CD touches an admin item — the
// change re-prices their weekly slip and they should know. Best-effort:
// silently skips when the request can't be resolved (e.g. the admin
// item is part of a country envelope not yet bound to a CCEO request).
function notifyAdminItemChange(
  fundRequestId: string,
  action: "added" | "updated" | "removed",
  name: string,
): void {
  const req = findFundRequest(fundRequestId);
  if (!req) return;
  const recipients: string[] = [];
  if (req.staffId) recipients.push(req.staffId);
  if (req.programLeadId) recipients.push(req.programLeadId);
  if (recipients.length === 0) return;
  emitNotificationFanOut(recipients, {
    template: `mfrAdminItem.${action}`,
    channel: "Inbox",
    title:
      action === "added"   ? `CD added admin item: ${name}` :
      action === "updated" ? `CD updated admin item: ${name}` :
                             `CD removed admin item: ${name}`,
    body: "Your monthly fund request envelope was re-priced — open the request to review the new totals.",
    href: `/fund-requests/${fundRequestId}`,
  });
}

export type AdminItemInput = {
  category: AdminBudgetCategory;
  itemName: string;
  quantity: number;
  unitCost: number;
  week: MfrAdminItem["week"];
  justification?: string;
};

export type AddAdminItemResult =
  | { ok: true; item: MfrAdminItem }
  | { ok: false; reason: "FORBIDDEN" | "INVALID_INPUT" };

export type AdminItemMutationResult =
  | { ok: true; id: string }
  | { ok: false; reason: "FORBIDDEN" | "NOT_FOUND" | "INVALID_INPUT" };

// Only the Country Director (and Admin) augments the request with admin items.
const CD_ROLES = new Set(["CountryDirector", "Admin"]);

function toMfrItem(rec: SeedAdminItem, fundRequestId: string, cdId: string, cdName: string): MfrAdminItem {
  return {
    id: rec.id,
    fundRequestId,
    category: rec.category,
    itemName: rec.name,
    quantity: rec.quantity,
    unitCost: rec.unitCost,
    totalCost: rec.quantity * rec.unitCost,
    week: rec.week,
    justification: rec.justification,
    addedByCdId: cdId,
    addedByCdName: cdName,
    createdAt: new Date().toISOString(),
  };
}

export async function addAdminItem(fundRequestId: string, input: AdminItemInput): Promise<AddAdminItemResult> {
  const user = await getCurrentUser();
  if (!CD_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!input.itemName?.trim() || input.unitCost <= 0 || input.quantity < 1) {
    return { ok: false, reason: "INVALID_INPUT" };
  }

  const rec = addAdminItemRecord({
    category: input.category,
    name: input.itemName.trim(),
    quantity: Math.round(input.quantity),
    unitCost: Math.round(input.unitCost),
    week: input.week,
    justification: input.justification?.trim() || undefined,
  });

  emitAudit({
    action: "mfrAdminItem.added",
    subjectKind: "MfrAdminItem",
    subjectId: rec.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { fundRequestId, name: rec.name, totalCost: rec.quantity * rec.unitCost },
  });
  notifyAdminItemChange(fundRequestId, "added", rec.name);

  try { revalidatePath("/monthly-fund-request"); revalidatePath("/budget"); } catch { /* noop */ }
  return { ok: true, item: toMfrItem(rec, fundRequestId, user.staffId, user.name) };
}

export async function updateAdminItem(id: string, patch: Partial<AdminItemInput>): Promise<AdminItemMutationResult> {
  const user = await getCurrentUser();
  if (!CD_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (patch.unitCost != null && patch.unitCost < 0) return { ok: false, reason: "INVALID_INPUT" };
  if (patch.quantity != null && patch.quantity < 1) return { ok: false, reason: "INVALID_INPUT" };

  const rec = updateAdminItemRecord(id, {
    category: patch.category,
    name: patch.itemName?.trim(),
    quantity: patch.quantity != null ? Math.round(patch.quantity) : undefined,
    unitCost: patch.unitCost != null ? Math.round(patch.unitCost) : undefined,
    week: patch.week,
    justification: patch.justification?.trim(),
  });
  if (!rec) return { ok: false, reason: "NOT_FOUND" };

  emitAudit({
    action: "mfrAdminItem.updated",
    subjectKind: "MfrAdminItem",
    subjectId: id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { patch },
  });
  // No fundRequestId on the record — best-effort, no notification.

  try { revalidatePath("/monthly-fund-request"); revalidatePath("/budget"); } catch { /* noop */ }
  return { ok: true, id };
}

export async function removeAdminItem(id: string): Promise<AdminItemMutationResult> {
  const user = await getCurrentUser();
  if (!CD_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const ok = removeAdminItemRecord(id);
  if (!ok) return { ok: false, reason: "NOT_FOUND" };

  emitAudit({
    action: "mfrAdminItem.removed",
    subjectKind: "MfrAdminItem",
    subjectId: id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
  });

  try { revalidatePath("/monthly-fund-request"); revalidatePath("/budget"); } catch { /* noop */ }
  return { ok: true, id };
}
