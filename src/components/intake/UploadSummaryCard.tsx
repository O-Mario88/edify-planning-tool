"use client";

// Truthful upload summary — shown after a school / SSA file upload completes.
//
// Renders exactly what the backend reported: file name + total/created/updated/
// failed/duplicate/skipped, the failed-row table (row #, school id, error), and
// a link to the School Directory. It NEVER claims success unless created+updated
// > 0 (a pure-duplicate or all-failed upload is shown as "Nothing saved").

import Link from "next/link";
import { CheckCircle2, AlertCircle, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { UploadSummary } from "@/lib/intake/upload-client";

const STAT = (label: string, value: number, tone: string) => ({ label, value, tone });

export function UploadSummaryCard({
  summary, fileName, directoryHref = "/schools", directoryLabel = "Open School Directory",
}: {
  summary: UploadSummary;
  fileName?: string | null;
  directoryHref?: string;
  directoryLabel?: string;
}) {
  const saved = summary.created_rows + summary.updated_rows;
  const success = saved > 0;
  const stats = [
    STAT("Total", summary.total_rows, "bg-slate-100 text-slate-700"),
    STAT("Created", summary.created_rows, "bg-emerald-100 text-emerald-700"),
    STAT("Updated", summary.updated_rows, "bg-sky-100 text-sky-700"),
    STAT("Duplicate", summary.duplicate_rows, "bg-amber-100 text-amber-700"),
    STAT("Failed", summary.failed_rows, "bg-rose-100 text-rose-700"),
    STAT("Skipped", summary.skipped_rows, "bg-slate-100 text-slate-500"),
  ];

  return (
    <div className="rounded-lg border border-[var(--color-edify-divider)] overflow-hidden">
      <div className={cn(
        "flex items-start gap-2 px-3 py-2.5",
        success ? "bg-emerald-50" : "bg-rose-50",
      )}>
        {success
          ? <CheckCircle2 size={16} className="text-emerald-600 shrink-0 mt-0.5" />
          : <AlertCircle size={16} className="text-rose-600 shrink-0 mt-0.5" />}
        <div className="min-w-0">
          <div className={cn("text-[12.5px] font-extrabold", success ? "text-emerald-800" : "text-rose-800")}>
            {summary.message}
          </div>
          {fileName && <div className="text-[10.5px] muted truncate">{fileName}</div>}
        </div>
      </div>

      <div className="grid grid-cols-3 sm:grid-cols-6 gap-px bg-[var(--color-edify-divider)]">
        {stats.map((s) => (
          <div key={s.label} className="bg-[var(--color-edify-surface,white)] px-2 py-2 text-center">
            <div className={cn("inline-flex items-center justify-center min-w-7 px-1.5 py-0.5 rounded-md text-[12px] font-extrabold", s.tone)}>
              {s.value}
            </div>
            <div className="text-[9.5px] muted uppercase tracking-wide mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      {summary.errors.length > 0 && (
        <div className="border-t border-[var(--color-edify-divider)]">
          <div className="px-3 py-1.5 text-[10.5px] font-extrabold uppercase tracking-wide text-rose-700 bg-rose-50/50">
            {summary.errors.length} row{summary.errors.length === 1 ? "" : "s"} not saved
          </div>
          <ul className="divide-y divide-[var(--color-edify-divider)] max-h-48 overflow-auto">
            {summary.errors.map((e, i) => (
              <li key={`${e.row}-${i}`} className="px-3 py-1.5 text-[11px] flex gap-2">
                <span className="font-extrabold text-rose-700 shrink-0">Row {e.row}</span>
                <span className="muted shrink-0">{e.school_id || "—"}</span>
                <span className="text-rose-700 min-w-0">{e.error}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {success && (
        <div className="border-t border-[var(--color-edify-divider)] px-3 py-2">
          <Link href={directoryHref}
            className="inline-flex items-center gap-1 text-[11.5px] font-extrabold text-[var(--color-edify-primary)] hover:underline">
            {directoryLabel} <ArrowRight size={13} />
          </Link>
        </div>
      )}
    </div>
  );
}
