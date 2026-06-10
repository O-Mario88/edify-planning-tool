"use client";

// CceoPartnerWorkSection — the CCEO-only monitor section on /partners
// (spec §15). Renders the six partner-work buckets from the shared
// engine (src/lib/cceo/partner-work.ts) as filterable lists, plus the
// payment-stage summary when the Payment Pipeline bucket is active.
//
// Deep-linkable: the dashboard card's strip cells land here with
// ?bucket=<key>, which the page passes down as `initialBucket`.

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, Building2, Handshake } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  buildPartnerWork,
  fmtUgx,
  type PartnerWorkBucketKey,
  type PartnerWorkUser,
} from "@/lib/cceo/partner-work";
import { STATUS_LABEL, STATUS_TONE } from "@/lib/partner/partner-workflow";

// Same chip vocabulary as StaffPartnerMonitoring so the CCEO sees the
// same activity at the same status the same way everywhere.
const TONE_CLS: Record<string, string> = {
  neutral: "bg-slate-100 text-slate-700",
  info:    "bg-blue-50 text-blue-700",
  warn:    "bg-amber-50 text-amber-700",
  danger:  "bg-rose-50 text-rose-700",
  success: "bg-emerald-50 text-emerald-700",
  muted:   "bg-slate-50 text-slate-600",
};

export function CceoPartnerWorkSection({
  user,
  initialBucket,
}: {
  user: PartnerWorkUser;
  initialBucket?: string;
}) {
  const work = buildPartnerWork(user);
  const validInitial = work.buckets.some((b) => b.key === initialBucket)
    ? (initialBucket as PartnerWorkBucketKey)
    : "awaitingMyReview";
  const [active, setActive] = useState<PartnerWorkBucketKey>(validInitial);

  const bucket = work.buckets.find((b) => b.key === active)!;

  return (
    <section className="card rounded-2xl overflow-hidden">
      <header className="px-4 sm:px-5 py-3.5 border-b border-[var(--color-edify-divider)] flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-body font-extrabold tracking-tight flex items-center gap-2">
            <span className="grid place-items-center h-6 w-6 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
              <Handshake size={13} />
            </span>
            My Partner Work
          </h3>
          <p className="text-[11.5px] muted mt-0.5">
            {work.totalOpen} open activities you assigned to partners — schedule → evidence → payment.
          </p>
        </div>
        <Link
          href="/my-targets"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap shrink-0"
        >
          Review queue
          <ArrowRight size={11} />
        </Link>
      </header>

      {/* Bucket filter pills — the six monitor buckets. */}
      <div className="flex items-center gap-1 overflow-x-auto scrollbar px-3 sm:px-4 py-2 border-b border-[var(--color-edify-divider)]">
        {work.buckets.map((b) => {
          const isActive = active === b.key;
          return (
            <button
              key={b.key}
              type="button"
              onClick={() => setActive(b.key)}
              title={b.description}
              className={cn(
                "inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-[11.5px] font-semibold whitespace-nowrap transition-colors",
                isActive
                  ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] border border-[var(--color-edify-border)]"
                  : "text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/50",
              )}
            >
              {b.label}
              <span
                className={cn(
                  "inline-flex items-center justify-center min-w-[18px] h-[16px] px-1 rounded-md text-[9.5px] font-extrabold",
                  isActive
                    ? "bg-[var(--color-edify-primary)] text-white"
                    : b.tone === "alert"
                      ? "bg-rose-100 text-rose-700"
                      : "bg-slate-100 text-slate-700",
                )}
              >
                {b.count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Payment-stage summary band — only for the payment bucket. */}
      {active === "paymentPipeline" && work.payment.count > 0 && (
        <div className="px-4 sm:px-5 py-2.5 border-b border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/30 flex items-center gap-x-4 gap-y-1 flex-wrap text-[11px]">
          <span className="font-extrabold tabular">
            {work.payment.count} payments · {fmtUgx(work.payment.totalUgx)}
          </span>
          {work.payment.stages.map((s) => (
            <span key={s.status} className="muted whitespace-nowrap">
              <span className="font-bold text-[var(--color-edify-text)] tabular">{s.count}</span>{" "}
              {s.label.toLowerCase()} ({fmtUgx(s.amountUgx)})
            </span>
          ))}
        </div>
      )}

      {/* Rows for the active bucket. */}
      {bucket.rows.length === 0 ? (
        <div className="text-center py-8 text-[12px] muted italic">
          Nothing in this bucket right now.
        </div>
      ) : (
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {bucket.rows.map((r) => (
            <li key={r.id} className="px-4 sm:px-5 py-3 flex items-center gap-3 hover:bg-[var(--color-edify-soft)]/40 transition-colors">
              <span className="grid place-items-center h-8 w-8 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
                <Building2 size={13} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2 min-w-0">
                  <span className="text-[12.5px] font-extrabold tracking-tight truncate">{r.school}</span>
                  <span className="text-[10.5px] muted shrink-0">{r.district}</span>
                </div>
                <div className="text-[11px] muted truncate mt-0.5">
                  {r.partner} · {r.activity} — {r.activitySub}
                </div>
              </div>
              <div className="hidden sm:flex flex-col items-end gap-1 shrink-0">
                <span className={cn(
                  "inline-flex items-center px-2 py-[3px] rounded-md text-caption font-bold whitespace-nowrap",
                  TONE_CLS[STATUS_TONE[r.status]],
                )}>
                  {STATUS_LABEL[r.status]}
                </span>
                <span className="text-[10.5px] muted tabular whitespace-nowrap">
                  {r.delayDays != null
                    ? `${r.delayDays} days delayed`
                    : r.scheduledWeek ?? (r.amountUgx ? fmtUgx(r.amountUgx) : "")}
                </span>
              </div>
              <Link
                href={bucket.actionHref}
                className="inline-flex items-center justify-center h-7 px-2.5 rounded-md text-[11px] font-extrabold whitespace-nowrap shrink-0 border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/60"
              >
                {bucket.actionLabel}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
