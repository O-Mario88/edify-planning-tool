// PartnerPaymentStatusCard — the partner's payment-pipeline view.
//
// Replaces "what's the status of my payment?" anxiety + WhatsApp
// follow-ups with a single board. Counts roll up across all the
// partner's activities and the 7 lines map 1-to-1 to the workflow
// state machine in partner-workflow.ts, so the numbers can never
// drift from the inbox tab counts.

import { Wallet, Clock, ShieldCheck, Send, CheckCircle2, AlertTriangle, PauseCircle, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  partnerPaymentLines,
  partnerPaymentTotals,
  type PartnerPaymentLine,
} from "@/lib/partner/partner-dashboard-mock";

const TONE: Record<PartnerPaymentLine["tone"], { dot: string; bg: string; text: string }> = {
  muted:   { dot: "bg-slate-400",   bg: "bg-slate-50",   text: "text-slate-600"   },
  amber:   { dot: "bg-amber-500",   bg: "bg-amber-50",   text: "text-amber-700"   },
  blue:    { dot: "bg-blue-500",    bg: "bg-blue-50",    text: "text-blue-700"    },
  emerald: { dot: "bg-emerald-500", bg: "bg-emerald-50", text: "text-emerald-700" },
  rose:    { dot: "bg-rose-500",    bg: "bg-rose-50",    text: "text-rose-700"    },
};

const ICON: Record<PartnerPaymentLine["key"], LucideIcon> = {
  notEligible:      Clock,
  awaitingCceo:     ShieldCheck,
  awaitingPl:       ShieldCheck,
  sentToAccountant: Send,
  paid:             CheckCircle2,
  returned:         AlertTriangle,
  onHold:           PauseCircle,
};

function fmtUgx(n: number): string {
  if (n === 0) return "—";
  if (n >= 1_000_000) return `UGX ${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `UGX ${(n / 1_000).toFixed(0)}K`;
  return `UGX ${n}`;
}

export function PartnerPaymentStatusCard() {
  const { awaitingTotal, paidThisMonth } = partnerPaymentTotals();
  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">
              <Wallet size={14} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Payment Status</h3>
          </div>
          <p className="text-[12px] muted mt-1">
            Every activity's payment state in one place — no need to chase anyone.
          </p>
        </div>
        <div className="flex items-baseline gap-5 shrink-0">
          <SummaryStat label="In flight" value={fmtUgx(awaitingTotal)} tone="amber" />
          <SummaryStat label="Paid this month" value={fmtUgx(paidThisMonth)} tone="emerald" />
        </div>
      </header>

      <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
        {partnerPaymentLines.map((line) => {
          const tone = TONE[line.tone];
          const Icon = ICON[line.key];
          return (
            <li
              key={line.key}
              className="rounded-xl border border-[var(--color-edify-divider)] bg-white p-3 flex flex-col"
            >
              <div className="flex items-center justify-between gap-2">
                <span className={cn("grid place-items-center h-7 w-7 rounded-md", tone.bg, tone.text)}>
                  <Icon size={13} />
                </span>
                <span className="text-[18px] font-extrabold tabular num-hero text-[var(--color-edify-text)] leading-none">
                  {line.count}
                </span>
              </div>
              <div className="mt-2.5">
                <div className="text-[12px] font-extrabold tracking-tight">{line.label}</div>
                <div className="text-caption muted leading-snug mt-0.5">{line.description}</div>
              </div>
              <div className="mt-2.5 pt-2 border-t border-[var(--color-edify-divider)] flex items-center justify-between">
                <span className={cn("inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide", tone.text)}>
                  <span className={cn("w-1.5 h-1.5 rounded-full", tone.dot)} />
                  {line.amountUgx > 0 ? fmtUgx(line.amountUgx) : "—"}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function SummaryStat({
  label, value, tone,
}: {
  label: string;
  value: string;
  tone: "amber" | "emerald";
}) {
  const cls = tone === "amber" ? "text-amber-700" : "text-emerald-700";
  return (
    <div className="text-right">
      <div className="text-[10px] uppercase tracking-wide font-bold muted">{label}</div>
      <div className={cn("text-[16px] font-extrabold tabular num-hero leading-tight", cls)}>{value}</div>
    </div>
  );
}
