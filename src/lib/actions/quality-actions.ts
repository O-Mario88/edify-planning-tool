"use server";

// Quality-check server action. Mirrors the canonical Bucket-C shape
// (fund-plan-actions.ts): resolve actor, gate by role, mutate the store,
// emit one audit row, notify, revalidate, return a discriminated union.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { recordQualityRun, type QualityCheckRun } from "@/lib/quality/quality-checks";
import { emitAudit, emitNotification } from "./audit";

export type RunQualityCheckResult =
  | { ok: true; ranAt: string; totalIssues: number; scannedActivities: number; liveSalesforceGaps: number }
  | { ok: false; reason: "FORBIDDEN" };

// Quality checks are an Impact-Assessment / Admin function (and CD for
// oversight). Defence-in-depth even though the page is already gated.
const RUN_ROLES = new Set(["ImpactAssessment", "CountryDirector", "Admin"]);

export async function runQualityCheck(): Promise<RunQualityCheckResult> {
  const user = await getCurrentUser();
  if (!RUN_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const run: QualityCheckRun = recordQualityRun(user.staffId, user.name);

  emitAudit({
    action: "qualityCheck.ran",
    subjectKind: "QualityCheckRun",
    subjectId: run.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: {
      totalIssues: run.totalIssues,
      scannedActivities: run.scannedActivities,
      liveSalesforceGaps: run.liveSalesforceGaps,
    },
  });

  emitNotification({
    userId: user.staffId,
    template: "qualityCheck.ran",
    channel: "Inbox",
    title: "Quality check complete",
    body: `Scanned ${run.scannedActivities} activities — ${run.totalIssues} open issues (${run.liveSalesforceGaps} missing Salesforce IDs).`,
    href: "/quality-checks",
  });

  try {
    revalidatePath("/quality-checks");
    revalidatePath("/data-intake/quality");
  } catch {
    /* outside request scope — fine */
  }

  return {
    ok: true,
    ranAt: run.ranAt,
    totalIssues: run.totalIssues,
    scannedActivities: run.scannedActivities,
    liveSalesforceGaps: run.liveSalesforceGaps,
  };
}
