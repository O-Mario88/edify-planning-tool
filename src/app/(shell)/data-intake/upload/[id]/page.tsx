import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, FileSpreadsheet, ChevronRight } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { recentUploads } from "@/lib/impact-mock";
import { cn } from "@/lib/utils";

const STATUS = {
  "Verified":  "bg-emerald-100 text-emerald-700",
  "In Review": "bg-sky-100     text-sky-700",
  "Failed QC": "bg-rose-100    text-rose-700",
} as const;

export default async function DataUploadDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const upload = recentUploads.find((u) => u.key === id);
  if (!upload) return notFound();

  return (
    <StubPage
      title={upload.fileName}
      subtitle={`${upload.program} · ${upload.records.toLocaleString()} records · uploaded by ${upload.uploadedBy}`}
    >
      <Link
        href="/data-intake/upload"
        className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline -mt-2"
      >
        <ArrowLeft size={11} />
        Back to Upload Center
      </Link>

      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Records"     value={upload.records.toLocaleString()} />
        <Stat label="Status"      value={upload.status} pill={STATUS[upload.status]} />
        <Stat label="Uploaded By" value={upload.uploadedBy} />
        <Stat label="Uploaded On" value={upload.uploadedOn} />
      </section>

      <article className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2 inline-flex items-center gap-1.5">
          <FileSpreadsheet size={13} className="text-[var(--color-edify-primary)]" />
          File contents
        </h2>
        <p className="text-[11.5px] muted">
          Schema validation, field coverage, and per-row quality flags appear here.
          Drill into <Link href="/quality-checks" className="text-[var(--color-edify-primary)] font-semibold hover:underline">Quality Checks</Link> for outstanding issues against this upload.
        </p>
      </article>

      <article className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Next steps</h2>
        <ul className="divide-y divide-[var(--color-edify-divider)] -my-1">
          <Step href="/data-verification?status=pending" label="Move to verification queue" />
          <Step href="/quality-checks"                   label="Run a fresh quality check" />
        </ul>
      </article>
    </StubPage>
  );
}

function Stat({ label, value, pill }: { label: string; value: string; pill?: string }) {
  return (
    <div className="card p-3.5">
      <div className="text-caption muted font-bold uppercase tracking-wide">{label}</div>
      {pill ? (
        <span className={cn("inline-flex items-center px-2 py-[2px] rounded-md text-[11px] font-extrabold mt-1.5", pill)}>
          {value}
        </span>
      ) : (
        <div className="text-[16px] font-extrabold tabular leading-none mt-1.5">{value}</div>
      )}
    </div>
  );
}

function Step({ href, label }: { href: string; label: string }) {
  return (
    <li>
      <Link
        href={href}
        className="flex items-center gap-2 py-2.5 -mx-2 px-2 rounded-md hover:bg-[var(--color-edify-soft)]/40 text-[12px] font-semibold"
      >
        <span className="flex-1">{label}</span>
        <ChevronRight size={12} className="text-[var(--color-edify-muted)]" />
      </Link>
    </li>
  );
}
