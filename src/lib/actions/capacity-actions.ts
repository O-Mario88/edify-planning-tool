"use server";

// Capacity management actions — only CD / IA (and Admin) can set staff direct-
// support limits (spec §3/§12). Role-gated server-side, audited.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { setStaffLimit } from "@/lib/planning/staff-capacity-store";
import { emitAudit } from "@/lib/actions/audit";

const CAN_SET = new Set(["CountryDirector", "ImpactAssessment", "Admin"]);

export type CapacityActionResult = { ok: true } | { ok: false; reason: "FORBIDDEN" | "INVALID_INPUT" };

export async function setStaffSupportLimit(staffId: string, max: number, notes?: string): Promise<CapacityActionResult> {
  const user = await getCurrentUser();
  if (!CAN_SET.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!staffId || !Number.isFinite(max) || max < 0 || max > 9999) return { ok: false, reason: "INVALID_INPUT" };

  setStaffLimit(staffId, max, user.name, user.role, notes);
  emitAudit({
    action: "capacity.limit.set", subjectKind: "Staff", subjectId: staffId,
    actorId: user.staffId, actorRole: user.role, actorName: user.name,
    payload: { max, notes },
  });
  try { revalidatePath("/capacity"); } catch { /* outside request */ }
  return { ok: true };
}
