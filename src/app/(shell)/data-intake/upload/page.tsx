import Link from "next/link";
import { Upload, Download, ChevronRight, FileSpreadsheet } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { ActionButton } from "@/components/ui/ActionButton";
import { dataTemplates, dataImportBatches } from "@/lib/data-intake-mock";
import { cn } from "@/lib/utils";

const STATUS_TONE = {
  "Uploaded":            "bg-slate-100   text-slate-700",
  "Validated":           "bg-violet-100  text-violet-700",
  "Needs Correction":    "bg-rose-100    text-rose-700",
  "Ready for Review":    "bg-sky-100     text-sky-700",
  "Approved for Import": "bg-emerald-100 text-emerald-700",
  "Imported":            "bg-emerald-100 text-emerald-700",
  "Rejected":            "bg-rose-100    text-rose-700",
} as const;

export default function UploadCenterPage() {
  return (
    <StubPage
      title="Upload Center"
      subtitle="Download the correct template, populate it, upload, preview validation, fix errors, submit for review. Raw uploads cannot overwrite production data."
    >
      {/* Step 1: pick a template */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-3">
          <div>
            <h2 className="text-body-lg font-extrabold tracking-tight">Step 1 — Choose a template</h2>
            <p className="text-[11.5px] muted">Templates are system-generated. Don&apos;t invent your own column structure.</p>
          </div>
          <Link href="/data-intake/templates" className="text-[11.5px] font-semibold text-[var(--color-edify-primary)]">
            All templates →
          </Link>
        </header>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
          {dataTemplates.slice(0, 9).map((t) => (
            <Link
              key={t.id}
              href={`/data-intake/templates/${t.id}`}
              className="rounded-xl border border-[var(--color-edify-border)] p-3 flex items-start gap-2 hover:bg-[var(--color-edify-soft)]/40"
            >
              <span className="h-8 w-8 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                <FileSpreadsheet size={13} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-[12px] font-extrabold tracking-tight truncate">{t.name}</div>
                <div className="text-caption muted truncate">{t.requiredColumns.length} required cols</div>
              </div>
              <a
                href={`/api/templates/${t.id}/csv`}
                className="h-7 w-7 rounded-md border border-[var(--color-edify-border)] grid place-items-center hover:bg-white shrink-0"
                aria-label={`Download ${t.name}`}
                onClick={(e) => e.stopPropagation()}
              >
                <Download size={11} className="text-[var(--color-edify-muted)]" />
              </a>
            </Link>
          ))}
        </div>
      </section>

      {/* Step 2: upload (mock) */}
      <section className="card rounded-2xl p-6 border-dashed border-2 border-[var(--color-edify-border)] text-center">
        <div className="mx-auto w-12 h-12 rounded-full bg-[var(--color-edify-soft)]/60 grid place-items-center text-[var(--color-edify-primary)] mb-3">
          <Upload size={20} />
        </div>
        <h2 className="text-body-lg font-extrabold tracking-tight">Step 2 — Upload your file</h2>
        <p className="text-[11.5px] muted max-w-[420px] mx-auto mt-1">
          Drag &amp; drop an .xlsx, .csv, or .json file generated from a template. We&apos;ll match it to the
          template, run every validation rule, and surface errors before anything reaches the queue.
        </p>
        <ActionButton
          Icon={Upload}
          label="Choose file"
          className="mt-3 h-9 px-4 rounded-xl bg-[var(--color-edify-primary)] text-white text-body font-semibold hover:brightness-110"
          toast={{
            tone: "info",
            title: "File picker opened",
            body: "Drop in an approved Edify template (.csv / .xlsx). Validation runs automatically.",
          }}
        />
      </section>

      {/* Step 3: validation queue */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-2">
          <div>
            <h2 className="text-body-lg font-extrabold tracking-tight">Step 3 — Validation queue</h2>
            <p className="text-[11.5px] muted">Validation results, errors, and warnings.</p>
          </div>
          <Link href="/data-intake/queue" className="text-[11.5px] font-semibold text-[var(--color-edify-primary)]">
            Open Queue →
          </Link>
        </header>
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {dataImportBatches.slice(0, 5).map((b) => (
            <li key={b.id} className="py-2.5 flex items-center gap-3">
              <span className="h-9 w-9 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                <FileSpreadsheet size={14} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-body font-extrabold tracking-tight truncate">{b.sourceFileName}</div>
                <div className="text-caption muted truncate">
                  {b.dataType} · {b.totalRows} rows · {b.errorRows} errors · {b.warningRows} warnings
                </div>
              </div>
              <span className={cn(
                "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap shrink-0",
                STATUS_TONE[b.status],
              )}>{b.status}</span>
              <ChevronRight size={12} className="text-[var(--color-edify-muted)] shrink-0" />
            </li>
          ))}
        </ul>
      </section>
    </StubPage>
  );
}
