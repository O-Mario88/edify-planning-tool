// PartnerEvidenceRequired — the most operational card in the Partner
// Delivery Command Center. Each activity row shows its evidence
// completeness % and exactly which items are missing, so the partner
// knows what to upload before the activity can move to CCEO
// confirmation. Critical missing items get a red badge so the
// partner can tell "must-have" from "nice-to-have".

import { Upload, AlertTriangle, CheckCircle2, ArrowRight, Building2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { evidenceSummaries } from "@/lib/partner/partner-evidence-mock";
import type { PartnerEvidenceSummary } from "@/lib/partner/partner-evidence";

export function PartnerEvidenceRequired() {
  // Surface activities that still need partner action — partial,
  // missing, or not-started. Returned-for-correction lives in its own
  // card (see PartnerReturnedCorrections).
  const open = evidenceSummaries.filter((s) =>
    s.status === "partial" || s.status === "missing" || s.status === "not_started",
  );

  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">
              <Upload size={14} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Evidence Required</h3>
          </div>
          <p className="text-[12px] muted mt-1">
            Upload these so each activity can move to CCEO confirmation. Critical items are required.
          </p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[10px] uppercase tracking-wide font-bold muted">Open</div>
          <div className="text-[18px] font-extrabold tabular num-hero text-rose-700 leading-none mt-1">
            {open.length}
          </div>
        </div>
      </header>

      {open.length === 0 ? (
        <div className="text-center py-6 text-[12px] muted italic">
          All evidence up to date. No partner action needed right now.
        </div>
      ) : (
        <ul className="space-y-2">
          {open.map((s) => (
            <EvidenceRow key={s.activityId} summary={s} />
          ))}
        </ul>
      )}
    </section>
  );
}

function EvidenceRow({ summary: s }: { summary: PartnerEvidenceSummary }) {
  // Top 3 missing items by criticality so the row stays compact even
  // for activities with many gaps.
  const missing = s.items
    .filter((it) => it.required && (it.status === "missing" || it.status === "returned" || it.status === "rejected"))
    .sort((a, b) => Number(b.critical) - Number(a.critical))
    .slice(0, 3);

  const completeness = s.completenessScore;
  const meterTone =
    completeness >= 80 ? "bg-emerald-500" :
    completeness >= 50 ? "bg-amber-500" :
    "bg-rose-500";

  return (
    <li className="rounded-xl border border-[var(--color-edify-divider)] bg-white p-3.5">
      <div className="flex items-start gap-3">
        <span className="grid place-items-center h-9 w-9 rounded-lg bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
          <Building2 size={14} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h4 className="text-[13px] font-extrabold tracking-tight truncate">
                {s.schoolName} — {s.activityLabel}
              </h4>
              <p className="text-[11px] muted leading-tight mt-0.5">
                {s.uploadedCount} of {s.requiredCount} required items uploaded
                {s.criticalMissingCount > 0 ? ` · ${s.criticalMissingCount} critical missing` : ""}
              </p>
            </div>
            <span className={cn(
              "inline-flex items-center px-2 py-[3px] rounded-md text-caption font-bold whitespace-nowrap",
              completeness >= 80 ? "bg-emerald-50 text-emerald-700" :
              completeness >= 50 ? "bg-amber-50 text-amber-700" :
              "bg-rose-50 text-rose-700",
            )}>
              {completeness}% complete
            </span>
          </div>

          {/* Completeness meter */}
          <div className="mt-2 h-1.5 w-full rounded-full bg-[var(--color-edify-soft)] overflow-hidden">
            <div
              className={cn("h-full transition-all", meterTone)}
              style={{ width: `${Math.max(2, completeness)}%` }}
              aria-hidden
            />
          </div>

          {/* Missing list */}
          {missing.length > 0 && (
            <ul className="mt-2.5 flex flex-wrap gap-1.5">
              {missing.map((m) => (
                <li key={m.id}>
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-caption font-bold",
                      m.critical
                        ? "bg-rose-50 text-rose-700 border border-rose-200"
                        : "bg-amber-50 text-amber-700 border border-amber-200",
                    )}
                    title={m.description}
                  >
                    {m.critical ? <AlertTriangle size={10} /> : <CheckCircle2 size={10} />}
                    {m.label}
                    {m.critical && <span className="text-[8.5px] font-extrabold opacity-80 ml-0.5">CRITICAL</span>}
                  </span>
                </li>
              ))}
            </ul>
          )}

          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              className="inline-flex items-center gap-1 h-8 px-3 rounded-md bg-[var(--color-edify-primary)] text-white text-[11.5px] font-extrabold hover:bg-[var(--color-edify-dark)]"
            >
              Upload Evidence <ArrowRight size={11} />
            </button>
            <span className="text-caption muted">
              Payment readiness: <span className={cn(
                "font-bold",
                s.isReadyForCceoConfirmation ? "text-emerald-700" : "text-rose-700",
              )}>{s.isReadyForCceoConfirmation ? "Ready for CCEO" : "Not ready"}</span>
            </span>
          </div>
        </div>
      </div>
    </li>
  );
}
