"use server";

// Server actions for the Data Validation queue. The underlying
// `dataImportBatches` array is server-only (see `data-intake-mock.ts`),
// so any state change happens on the server; the queue page re-reads the
// array each request so a successful transition shows on the next render.
//
// Canonical Bucket-C shape: resolve the actor via getCurrentUser (never
// trust a client-passed actor), gate by role, validate the source status,
// mutate, emit one audit row, revalidate, return a discriminated union.
//
// Batch lifecycle:
//   Uploaded → Validated → Ready for Review → Approved for Import → Imported
//        ↘ Needs Correction          ↘ Rejected (terminal, with reason)

import { revalidatePath } from "next/cache";
import { dataImportBatches, type DataImportBatch } from "@/lib/data-intake-mock";
import { getCurrentUser } from "@/lib/auth";
import { emitAudit } from "./actions/audit";

type Status = DataImportBatch["status"];

export type BatchActionResult =
  | { ok: true; batchId: string; newStatus: Status }
  | { ok: false; reason: "FORBIDDEN" | "NOT_FOUND" | "WRONG_STATUS" | "INVALID_INPUT" };

const REVIEW_ROLES = new Set(["ImpactAssessment", "Admin", "CountryDirector", "ProgramAccountant"]);

function stamp(): string {
  return new Date().toISOString().replace("T", " · ").slice(0, 16);
}

async function transition(
  batchId: string,
  from: ReadonlySet<Status>,
  to: Status,
  auditAction: string,
  extra: Partial<DataImportBatch> = {},
  payload: Record<string, unknown> = {},
): Promise<BatchActionResult> {
  const user = await getCurrentUser();
  if (!REVIEW_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const idx = dataImportBatches.findIndex((b) => b.id === batchId);
  if (idx === -1) return { ok: false, reason: "NOT_FOUND" };
  const b = dataImportBatches[idx];
  if (!from.has(b.status)) return { ok: false, reason: "WRONG_STATUS" };

  dataImportBatches[idx] = { ...b, status: to, ...extra };

  emitAudit({
    action: auditAction,
    subjectKind: "DataImportBatch",
    subjectId: batchId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { from: b.status, to, file: b.sourceFileName, ...payload },
  });

  try {
    revalidatePath("/data-intake/queue");
    revalidatePath("/data-intake");
  } catch {
    /* outside request scope — fine */
  }
  return { ok: true, batchId, newStatus: to };
}

export async function validateBatch(batchId: string): Promise<BatchActionResult> {
  return transition(batchId, new Set<Status>(["Uploaded"]), "Validated", "dataImport.validated");
}

export async function sendBatchForReview(batchId: string): Promise<BatchActionResult> {
  return transition(batchId, new Set<Status>(["Validated"]), "Ready for Review", "dataImport.sentForReview");
}

export async function approveImport(batchId: string): Promise<BatchActionResult> {
  const user = await getCurrentUser();
  return transition(
    batchId,
    new Set<Status>(["Ready for Review", "Validated"]),
    "Approved for Import",
    "dataImport.approved",
    { reviewedBy: user.name, reviewedAt: stamp() },
  );
}

export async function rejectImport(batchId: string, reason: string): Promise<BatchActionResult> {
  const trimmed = reason?.trim() ?? "";
  if (trimmed.length < 5) return { ok: false, reason: "INVALID_INPUT" };
  const user = await getCurrentUser();
  return transition(
    batchId,
    new Set<Status>(["Uploaded", "Validated", "Ready for Review", "Needs Correction"]),
    "Rejected",
    "dataImport.rejected",
    { reviewedBy: user.name, reviewedAt: stamp(), notes: trimmed },
    { reason: trimmed },
  );
}
