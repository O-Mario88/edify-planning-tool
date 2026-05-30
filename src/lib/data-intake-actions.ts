"use server";

// Server actions for the Data Validation queue. The underlying
// `dataImportBatches` array is server-only (see `data-intake-mock.ts`),
// so any state change has to happen on the server. The queue page
// re-reads `dataImportBatches` on each request, so a successful
// `approveImport` will be reflected on the next reload.
//
// Authorisation: only the listed roles may approve. The role check is
// soft — it relies on the caller passing the actor; production would
// derive this from the session.

import { revalidatePath } from "next/cache";
import { dataImportBatches } from "@/lib/data-intake-mock";

export type ApproveImportResult =
  | { ok: true; batchId: string }
  | { ok: false; reason: "FORBIDDEN" | "NOT_FOUND" | "WRONG_STATUS" };

const ALLOWED_ROLES = [
  "ImpactAssessment",
  "Admin",
  "CountryDirector",
  "ProgramAccountant",
];

export async function approveImport(
  batchId: string,
  actor: { role: string; name?: string },
): Promise<ApproveImportResult> {
  if (!ALLOWED_ROLES.includes(actor.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  const idx = dataImportBatches.findIndex((b) => b.id === batchId);
  if (idx === -1) return { ok: false, reason: "NOT_FOUND" };
  const b = dataImportBatches[idx];
  if (b.status !== "Ready for Review" && b.status !== "Validated") {
    return { ok: false, reason: "WRONG_STATUS" };
  }
  const now = new Date().toISOString().replace("T", " · ").slice(0, 16);
  dataImportBatches[idx] = {
    ...b,
    status: "Approved for Import",
    reviewedBy: actor.name ?? actor.role,
    reviewedAt: now,
  };
  // Refresh the queue page so the new status is visible.
  try {
    revalidatePath("/data-intake/queue");
  } catch {
    // Outside a request scope (e.g. unit test) — ignore.
  }
  return { ok: true, batchId };
}
