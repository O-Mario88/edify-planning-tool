// PartnerTodayBottomSections — three focused sections that surface
// only what needs partner action today:
//
//   • Evidence Required Today    — activities blocked on missing evidence
//   • Corrections Due Today      — returned items with an end-of-day deadline
//   • Payment Blockers Today     — completed activities held up by evidence
//
// Each has an empty-state that reads as calm closure, not a void.

import { Upload, RotateCcw, Wallet, ArrowRight, CheckCircle2, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  partnerTodayTasks,
  todayPaymentBlockers,
} from "@/lib/partner/partner-today-mock";

function fmtUgx(n: number): string {
  if (n >= 1_000_000) return `UGX ${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `UGX ${(n / 1_000).toFixed(0)}K`;
  return `UGX ${n}`;
}

export function PartnerTodayBottomSections() {
  const evidenceRows = partnerTodayTasks.filter(
    (t) => t.taskType !== "correction" && t.missingEvidenceCount > 0,
  );
  const correctionRows = partnerTodayTasks.filter((t) => t.taskType === "correction");

  return (
    <div className="space-y-4">
      <EvidenceRequiredToday rows={evidenceRows} />
      <CorrectionsDueToday rows={correctionRows} />
      <PaymentBlockersToday />
    </div>
  );
}

// ────────── Evidence Required Today ──────────

function EvidenceRequiredToday({ rows }: { rows: typeof partnerTodayTasks }) {
  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">
            <Upload size={14} />
          </span>
          <div>
            <h3 className="text-body-lg font-extrabold tracking-tight">Evidence Required Today</h3>
            <p className="text-[11.5px] muted">
              {rows.length === 0
                ? "All evidence up to date."
                : `${rows.length} ${rows.length === 1 ? "activity needs" : "activities need"} evidence before they can move to CCEO confirmation.`}
            </p>
          </div>
        </div>
        {rows.length > 0 && (
          <span className="text-caption uppercase tracking-wide font-bold text-rose-700">
            {rows.reduce((sum, r) => sum + r.missingEvidenceCount, 0)} items missing
          </span>
        )}
      </header>

      {rows.length === 0 ? (
        <EmptyState
          tone="good"
          message="Nothing missing right now. Keep the streak going."
        />
      ) : (
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {rows.map((r) => (
            <li key={r.id} className="py-2.5 flex items-center gap-3 flex-wrap sm:flex-nowrap">
              <div className="min-w-0 flex-1">
                <div className="text-body font-extrabold tracking-tight">{r.schoolName}</div>
                <div className="text-[11px] muted leading-tight mt-0.5">
                  Missing:{" "}
                  {r.evidenceChecklist
                    .filter((it) => it.status === "missing")
                    .slice(0, 3)
                    .map((it) => it.label)
                    .join(", ")}
                  {r.missingEvidenceCount > 3 ? ` · +${r.missingEvidenceCount - 3} more` : ""}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className={cn(
                  "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-bold whitespace-nowrap",
                  r.criticalMissingCount > 0 ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-700",
                )}>
                  {r.criticalMissingCount > 0
                    ? `${r.criticalMissingCount} critical missing`
                    : `${r.missingEvidenceCount} item${r.missingEvidenceCount === 1 ? "" : "s"} missing`}
                </span>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 h-8 px-3 rounded-md bg-[var(--color-edify-primary)] text-white text-[11.5px] font-extrabold hover:bg-[var(--color-edify-dark)]"
                >
                  Upload <ArrowRight size={11} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ────────── Corrections Due Today ──────────

function CorrectionsDueToday({ rows }: { rows: typeof partnerTodayTasks }) {
  return (
    <section className="card p-3.5">
      <header className="flex items-start gap-2 mb-3">
        <span className="grid place-items-center h-7 w-7 rounded-md bg-amber-100 text-amber-700">
          <RotateCcw size={14} />
        </span>
        <div>
          <h3 className="text-body-lg font-extrabold tracking-tight">Corrections Due Today</h3>
          <p className="text-[11.5px] muted">
            {rows.length === 0
              ? "No corrections waiting."
              : "Returned items that must be re-submitted before end of day."}
          </p>
        </div>
      </header>

      {rows.length === 0 ? (
        <EmptyState tone="good" message="No corrections pending. Your submitted work is clean." />
      ) : (
        <ul className="space-y-2">
          {rows.map((r) => (
            <li key={r.id} className="rounded-xl border border-amber-200 bg-amber-50/40 p-3">
              <div className="flex items-start justify-between gap-3 flex-wrap sm:flex-nowrap">
                <div className="min-w-0 flex-1">
                  <div className="text-body font-extrabold tracking-tight">{r.schoolName}</div>
                  {r.returnReason && (
                    <p className="text-[11.5px] text-amber-900 leading-snug mt-1">
                      <span className="font-bold">Reason:</span> {r.returnReason}
                    </p>
                  )}
                  {r.reviewerComment && (
                    <p className="text-[11px] text-amber-800/90 leading-snug mt-1 italic">
                      "{r.reviewerComment}"
                    </p>
                  )}
                  {r.returnedBy && (
                    <p className="text-caption muted mt-1">Returned by {r.returnedBy} · due today</p>
                  )}
                </div>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 h-8 px-3 rounded-md bg-amber-500 text-white text-[11.5px] font-extrabold hover:bg-amber-600 shrink-0"
                >
                  Correct Submission <ArrowRight size={11} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ────────── Payment Blockers Today ──────────

function PaymentBlockersToday() {
  const blockers = todayPaymentBlockers;
  const total = blockers.reduce((sum, b) => sum + b.amountUgxWaiting, 0);
  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <span className="grid place-items-center h-7 w-7 rounded-md bg-rose-50 text-rose-700">
            <Wallet size={14} />
          </span>
          <div>
            <h3 className="text-body-lg font-extrabold tracking-tight">Payment Blockers</h3>
            <p className="text-[11.5px] muted">
              {blockers.length === 0
                ? "No payment blockers requiring your action."
                : `${blockers.length} completed ${blockers.length === 1 ? "activity cannot" : "activities cannot"} move to payment because evidence is missing.`}
            </p>
          </div>
        </div>
        {blockers.length > 0 && (
          <div className="text-right shrink-0">
            <div className="text-[10px] uppercase tracking-wide font-bold muted">Waiting</div>
            <div className="text-[15px] font-extrabold tabular num-hero text-rose-700 leading-none mt-1">
              {fmtUgx(total)}
            </div>
          </div>
        )}
      </header>

      {blockers.length === 0 ? (
        <EmptyState tone="good" message="Nothing held up by missing evidence right now." />
      ) : (
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {blockers.map((b) => (
            <li key={b.id} className="py-2.5 flex items-center justify-between gap-3 flex-wrap sm:flex-nowrap">
              <div className="min-w-0 flex-1">
                <div className="text-body font-extrabold tracking-tight">{b.activityLabel}</div>
                <div className="text-[11px] muted leading-tight mt-0.5">
                  Missing: {b.missing.join(", ")}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-[12px] font-extrabold tabular text-[var(--color-edify-text)] whitespace-nowrap">
                  {fmtUgx(b.amountUgxWaiting)}
                </span>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 h-8 px-3 rounded-md bg-rose-500 text-white text-[11.5px] font-extrabold hover:bg-rose-600 whitespace-nowrap"
                >
                  Upload Evidence <ArrowRight size={11} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ────────── Empty state ──────────

function EmptyState({
  tone, message,
}: {
  tone: "good" | "muted";
  message: string;
}) {
  const Icon = tone === "good" ? CheckCircle2 : AlertTriangle;
  const cls = tone === "good" ? "text-emerald-600" : "text-[var(--color-edify-muted)]";
  return (
    <div className="rounded-xl border border-dashed border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/40 px-4 py-5 text-center">
      <Icon size={18} className={cn("inline mb-1.5", cls)} />
      <p className="text-[12px] muted">{message}</p>
    </div>
  );
}
