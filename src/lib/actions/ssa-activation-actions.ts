"use server";

// SSA activation server action — records the tracked SSA-activation step
// (SIT / partner / self) for a clustered school, so activation persists and the
// school's workflow state reflects it. IA's SSA upload later clears it + unlocks.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { emitAudit, emitNotificationFanOut } from "./audit";
import { activateSsa, SSA_METHOD_LABEL, type SsaActivationMethod } from "@/lib/school-directory/ssa-activation";
import { intakeSchools } from "@/lib/intake/intake-mock";
import { partnerById } from "@/lib/partner/partner-mock";

const STAFF_ROLES = new Set<string>(["CCEO", "CountryProgramLead", "CountryDirector", "ImpactAssessment", "Admin"]);

export type SsaActivationResult =
  | { ok: true; method: SsaActivationMethod }
  | { ok: false; reason: "FORBIDDEN" | "NOT_FOUND" | "FAILED"; message?: string };

export async function activateSsaAction(
  schoolId: string,
  method: SsaActivationMethod,
  opts: { partnerId?: string; date?: string } = {},
): Promise<SsaActivationResult> {
  const user = await getCurrentUser();
  if (!STAFF_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const school = intakeSchools.find((s) => s.schoolId === schoolId);
  if (!school) return { ok: false, reason: "NOT_FOUND" };
  if (!school.clusterId) return { ok: false, reason: "FAILED", message: "Cluster the school before activating SSA." };

  const partner = opts.partnerId ? partnerById(opts.partnerId) : undefined;
  activateSsa(schoolId, method, { name: user.name, role: user.role }, {
    partnerId: opts.partnerId,
    partnerName: partner?.name,
    date: opts.date,
  });

  emitAudit({
    action: "ssa.activated", subjectKind: "School", subjectId: schoolId,
    actorId: user.staffId, actorRole: user.role, actorName: user.name,
    payload: { method, partnerId: opts.partnerId, date: opts.date },
  });
  emitNotificationFanOut(["IMPACT_ASSESSMENT"], {
    template: "ssa.activated", channel: "Inbox",
    title: "SSA activation started",
    body: `${school.schoolName}: ${SSA_METHOD_LABEL[method]}. Upload the SSA to unlock planning.`,
    href: "/data-intake/upload",
  });
  try {
    revalidatePath("/planning");
    revalidatePath("/schools");
    revalidatePath(`/schools/${schoolId}`);
  } catch { /* outside request */ }
  return { ok: true, method };
}
