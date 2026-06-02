import Link from "next/link";
import { StubPage } from "@/components/shell/StubPage";
import { ActionButton } from "@/components/ui/ActionButton";
import { ApproveImportButton } from "./ApproveImportButton";
import { dataImportBatches, type DataImportBatch } from "@/lib/data-intake-mock";
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

// Status-driven action — shared by the mobile cards and the desktop table.
function batchAction(b: DataImportBatch) {
  if (b.status === "Ready for Review") return <ApproveImportButton batchId={b.id} fileName={b.sourceFileName} />;
  if (b.status === "Needs Correction") return (
    <ActionButton label="View errors →" className="text-[11px] font-semibold text-rose-700 hover:underline"
      toast={{ tone: "warning", title: "Opening error log", body: `${b.errorRows} validation errors across ${b.totalRows} rows.` }} />
  );
  if (b.status === "Uploaded") return (
    <ActionButton label="Validate →" className="text-[11px] font-semibold text-[var(--color-edify-primary)] hover:underline"
      toast={{ tone: "info", title: "Validating rows", body: "Running schema + business rule checks." }} />
  );
  if (b.status === "Validated") return (
    <ActionButton label="Send for review →" className="text-[11px] font-semibold text-[var(--color-edify-primary)] hover:underline"
      oneShot oneShotLabel="Sent" oneShotClassName="!bg-transparent !text-sky-700 !font-bold"
      toast={{ tone: "success", title: "Sent to reviewer", body: `${b.sourceFileName} routed for approval.` }} />
  );
  if (b.status === "Imported") return <Link href="/data-intake/readiness" className="text-[11px] font-semibold text-emerald-700 hover:underline">In planning engine</Link>;
  return null;
}

function StatusBadge({ status }: { status: DataImportBatch["status"] }) {
  return (
    <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", STATUS_TONE[status])}>
      {status}
    </span>
  );
}

function Metric({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <span className="inline-flex items-baseline gap-1">
      <span className={cn("text-[12px] font-extrabold tabular", tone)}>{value}</span>
      <span className="text-[10px] muted">{label}</span>
    </span>
  );
}

export default function DataValidationQueuePage() {
  return (
    <StubPage
      title="Data Validation Queue"
      subtitle="Every uploaded batch with row-level validation results, approval state, and reviewer audit trail."
    >
      {/* Mobile — one card per batch (the table doesn't fit a phone). */}
      <section className="md:hidden flex flex-col gap-2.5">
        {dataImportBatches.map((b) => {
          const action = batchAction(b);
          return (
            <article key={b.id} className="card p-3.5">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-extrabold tracking-tight text-[13px] truncate">{b.sourceFileName}</div>
                  <div className="text-caption muted">{b.dataType}</div>
                </div>
                <StatusBadge status={b.status} />
              </div>
              {b.notes && <p className="text-caption muted mt-1 leading-snug">{b.notes}</p>}
              <div className="flex items-center gap-3 flex-wrap mt-2 pt-2 border-t border-[var(--color-edify-divider)]">
                <Metric label="rows"    value={b.totalRows}   tone="text-[var(--color-edify-text)]" />
                <Metric label="valid"   value={b.validRows}   tone="text-emerald-700" />
                <Metric label="errors"  value={b.errorRows}   tone="text-rose-700" />
                <Metric label="warnings" value={b.warningRows} tone="text-amber-700" />
              </div>
              <div className="flex items-center justify-between gap-2 mt-2">
                <span className="text-caption muted truncate">{b.uploadedBy} · {b.uploadedAt}</span>
                {action && <span className="shrink-0">{action}</span>}
              </div>
              {b.reviewedBy && <div className="text-[10px] muted mt-1">Reviewed by {b.reviewedBy}</div>}
            </article>
          );
        })}
      </section>

      {/* Desktop — the full validation table. */}
      <section className="card p-3.5 hidden md:block">
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                <th scope="col" className="py-2 pr-2">File</th>
                <th scope="col" className="py-2 px-2">Data type</th>
                <th scope="col" className="py-2 px-2 text-right">Rows</th>
                <th scope="col" className="py-2 px-2 text-right">Valid</th>
                <th scope="col" className="py-2 px-2 text-right">Errors</th>
                <th scope="col" className="py-2 px-2 text-right">Warnings</th>
                <th scope="col" className="py-2 px-2">Uploaded by</th>
                <th scope="col" className="py-2 px-2">Status</th>
                <th scope="col" className="py-2 pl-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {dataImportBatches.map((b) => (
                <tr key={b.id} className="hover:bg-[var(--color-edify-soft)]/30 align-top">
                  <td className="py-2.5 pr-2">
                    <div className="font-extrabold tracking-tight">{b.sourceFileName}</div>
                    {b.notes && <div className="text-caption muted mt-0.5 leading-snug max-w-[280px]">{b.notes}</div>}
                  </td>
                  <td className="py-2.5 px-2 muted">{b.dataType}</td>
                  <td className="py-2.5 px-2 text-right tabular">{b.totalRows}</td>
                  <td className="py-2.5 px-2 text-right tabular text-emerald-700 font-extrabold">{b.validRows}</td>
                  <td className="py-2.5 px-2 text-right tabular text-rose-700 font-extrabold">{b.errorRows}</td>
                  <td className="py-2.5 px-2 text-right tabular text-amber-700 font-extrabold">{b.warningRows}</td>
                  <td className="py-2.5 px-2 muted">
                    <div>{b.uploadedBy}</div>
                    <div className="text-caption muted">{b.uploadedAt}</div>
                  </td>
                  <td className="py-2.5 px-2">
                    <StatusBadge status={b.status} />
                    {b.reviewedBy && (
                      <div className="text-[10px] muted mt-0.5">Reviewed by {b.reviewedBy}</div>
                    )}
                  </td>
                  <td className="py-2.5 pl-2 text-right">{batchAction(b)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card p-3.5 text-[11.5px] muted">
        <span className="font-extrabold text-[var(--color-edify-text)]">Validation contract: </span>
        Each batch checks missing required fields, duplicate records, invalid IDs, invalid mappings, scores out
        of range, invalid dates, invalid cost values, missing currency, invalid partner certification, and
        conflicting records. Only Approved batches flow into the planning engine.
      </section>
    </StubPage>
  );
}
