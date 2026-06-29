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
import { addIntakeSchool, addSsaUpload, intakeSchools } from "@/lib/intake/intake-mock";
import { isBackendEnabled, backendFetch } from "@/lib/api/backend";

type Status = DataImportBatch["status"];

export type BatchActionResult =
  | { ok: true; batchId: string; newStatus: Status }
  | { ok: false; reason: "FORBIDDEN" | "NOT_FOUND" | "WRONG_STATUS" | "INVALID_INPUT" };

const REVIEW_ROLES = new Set(["ImpactAssessment", "Admin", "CountryDirector", "ProgramAccountant"]);

export function mapBackendStatusToFrontend(status: string): Status {
  switch (status?.toLowerCase()) {
    case "uploaded": return "Uploaded";
    case "validated": return "Validated";
    case "imported": return "Imported";
    case "rejected": return "Rejected";
    case "completed": return "Validated";
    case "completed_with_errors": return "Needs Correction";
    case "failed": return "Needs Correction";
    default: return "Uploaded";
  }
}

import { type SchoolType } from "@/lib/intake/intake-core";

interface PendingSchoolMock {
  schoolId: string;
  schoolName: string;
  region: string;
  district: string;
  schoolType: SchoolType;
  enrollment: number;
  assignedCceo: string;
}

interface PendingSsaMock {
  schoolId: string;
  ssaDate: string;
  fy: string;
  quarter: string;
  scores: Record<string, number>;
  newEnrollment: number;
  uploadedBy: string;
  id: string;
}

// Mock data to merge upon importing specific batches
const PENDING_SCHOOLS_MOCK: Record<string, PendingSchoolMock[]> = {
  "imp-9": [
    {
      schoolId: "70010",
      schoolName: "Greenhill Academy Nakasero",
      region: "Central Region",
      district: "Kampala",
      schoolType: "Client",
      enrollment: 450,
      assignedCceo: "Paul Chinyama",
    },
    {
      schoolId: "70011",
      schoolName: "St. Jude Primary School",
      region: "Central Region",
      district: "Wakiso",
      schoolType: "Client",
      enrollment: 380,
      assignedCceo: "Paul Chinyama",
    },
    {
      schoolId: "70012",
      schoolName: "Victoria Nile School",
      region: "Eastern Region",
      district: "Jinja",
      schoolType: "Core",
      enrollment: 520,
      assignedCceo: "Aisha Dar",
    },
  ],
};

const PENDING_SSA_MOCK: Record<string, PendingSsaMock[]> = {
  "imp-4": [
    {
      schoolId: "32791",
      ssaDate: "2026-06-20",
      fy: "2026",
      quarter: "Q3",
      scores: {
        "Teaching & Learning": 8,
        "Financial Health": 7,
        "Christlike Behaviour": 8,
        "Exposure to the Word of God": 9,
        "Government Requirements & Compliance": 8,
        "Leadership": 8,
        "Education Technology": 7,
        "Learning Environment": 8,
      },
      newEnrollment: 320,
      uploadedBy: "Grace Alimo",
      id: "ssaup-imp4-1",
    },
    {
      schoolId: "52910",
      ssaDate: "2026-06-21",
      fy: "2026",
      quarter: "Q3",
      scores: {
        "Teaching & Learning": 7,
        "Financial Health": 6,
        "Christlike Behaviour": 8,
        "Exposure to the Word of God": 7,
        "Government Requirements & Compliance": 7,
        "Leadership": 8,
        "Education Technology": 6,
        "Learning Environment": 7,
      },
      newEnrollment: 280,
      uploadedBy: "Grace Alimo",
      id: "ssaup-imp4-2",
    },
  ],
};

async function executeBatchHandoff(batchId: string) {
  const idx = dataImportBatches.findIndex((b) => b.id === batchId);
  if (idx === -1) return;
  const batch = dataImportBatches[idx];

  if (batch.dataType === "School Register") {
    const schoolsToMerge = PENDING_SCHOOLS_MOCK[batchId];
    if (schoolsToMerge) {
      for (const s of schoolsToMerge) {
        if (!intakeSchools.some((x) => x.schoolId === s.schoolId)) {
          addIntakeSchool({
            schoolId: s.schoolId,
            schoolName: s.schoolName,
            region: s.region,
            district: s.district,
            schoolType: s.schoolType,
            enrollment: s.enrollment,
            assignedCceo: s.assignedCceo,
            dateAdded: new Date().toISOString().slice(0, 10),
            addedBy: batch.uploadedBy,
          });
        }
      }
    }
  } else if (batch.dataType === "SSA Results") {
    const ssaToMerge = PENDING_SSA_MOCK[batchId];
    if (ssaToMerge) {
      for (const ssa of ssaToMerge) {
        addSsaUpload({
          schoolId: ssa.schoolId,
          ssaDate: ssa.ssaDate,
          fy: ssa.fy,
          quarter: ssa.quarter,
          scores: ssa.scores,
          newEnrollment: ssa.newEnrollment,
          uploadedBy: ssa.uploadedBy,
          id: ssa.id,
        });
      }
    }
  }
}

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

  if (isBackendEnabled()) {
    const actionMap: Record<string, string> = {
      "dataImport.validated": "validate",
      "dataImport.imported": "import",
      "dataImport.rejected": "reject",
    };
    const action = actionMap[auditAction];
    if (!action) return { ok: false, reason: "WRONG_STATUS" };

    const beUser = { email: user.email, role: user.role };
    const res = await backendFetch<{ status: string }>(
      `/uploads/${encodeURIComponent(batchId)}/${action}`,
      beUser,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );

    if (!res.ok) {
      const err = res.error?.toLowerCase() ?? "";
      if (err.includes("forbidden") || err.includes("403")) return { ok: false, reason: "FORBIDDEN" };
      if (err.includes("not found") || err.includes("404")) return { ok: false, reason: "NOT_FOUND" };
      return { ok: false, reason: "WRONG_STATUS" };
    }

    try {
      revalidatePath("/data-intake/queue");
      revalidatePath("/data-intake");
      revalidatePath("/schools");
    } catch {}

    const newFrontendStatus = mapBackendStatusToFrontend(res.data.status);
    return { ok: true, batchId, newStatus: newFrontendStatus };
  }

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
    revalidatePath("/schools");
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
  const res = await transition(
    batchId,
    new Set<Status>(["Ready for Review", "Validated"]),
    "Imported",
    "dataImport.imported",
    {
      reviewedBy: user.name,
      reviewedAt: stamp(),
      importedBy: user.name,
      importedAt: stamp(),
    },
  );
  if (res.ok && !isBackendEnabled()) {
    await executeBatchHandoff(batchId);
  }
  return res;
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
