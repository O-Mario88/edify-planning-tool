// Client helpers for the truthful, backend-persisted file uploads.
//
// These POST the RAW file (multipart) to the Next proxy routes, which forward it
// to the Django backend (the single source of truth). The backend parses,
// validates, and SAVES rows in Postgres and returns the truthful contract below.
// There is NO mock fallback in the success path.

import { csrfHeaders } from "@/lib/csrf-client";

export type UploadRowError = { row: number; school_id: string; error: string };

export type UploadSummary = {
  success: boolean;
  upload_batch_id: string;
  total_rows: number;
  created_rows: number;
  updated_rows: number;
  failed_rows: number;
  duplicate_rows: number;
  skipped_rows: number;
  message: string;
  errors: UploadRowError[];
};

export type UploadOutcome =
  | { ok: true; summary: UploadSummary }
  | { ok: false; error: string };

async function postFile(path: string, file: File, extra?: Record<string, string>): Promise<UploadOutcome> {
  const form = new FormData();
  form.append("file", file, file.name);
  if (extra) for (const [k, v] of Object.entries(extra)) form.append(k, v);
  try {
    const res = await fetch(path, {
      method: "POST",
      headers: { ...csrfHeaders() }, // no Content-Type — the browser sets the multipart boundary
      body: form,
      credentials: "include",
      cache: "no-store",
    });
    let body: unknown = null;
    try { body = await res.json(); } catch { /* non-json */ }
    if (body && typeof body === "object" && "success" in body) {
      return { ok: true, summary: body as UploadSummary };
    }
    const error = (body as { error?: string } | null)?.error ?? `Upload failed (${res.status})`;
    return { ok: false, error };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "Upload error" };
  }
}

export function uploadSchoolFile(file: File, updateExisting: boolean): Promise<UploadOutcome> {
  return postFile("/api/schools/upload", file, updateExisting ? { update_existing: "true" } : undefined);
}

export function uploadSsaFile(file: File): Promise<UploadOutcome> {
  return postFile("/api/ssa/upload", file);
}
