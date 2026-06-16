// PartnerPaymentStatusCard — the partner's payment-pipeline view.
//
// Replaces "what's the status of my payment?" anxiety + WhatsApp
// follow-ups with a single board. Counts roll up across all the
// partner's activities and the 7 lines map 1-to-1 to the workflow
// state machine in partner-workflow.ts, so the numbers can never
// drift from the inbox tab counts.

import { Wallet } from "lucide-react";
import { cn } from "@/lib/utils";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import {
  partnerPaymentLines,
  partnerPaymentTotals,
  type PartnerPaymentLine,
} from "@/lib/partner/partner-dashboard-mock";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

const CELL_TONE: Record<PartnerPaymentLine["tone"], MetricCell["tone"]> = {
  muted:   "default",
  amber:   "default",
  blue:    "default",
  emerald: "good",
  rose:    "alert",
};

function fmtUgx(n: number): string {
  if (n === 0) return "—";
  if (n >= 1_000_000) return `UGX ${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `UGX ${(n / 1_000).toFixed(0)}K`;
  return `UGX ${n}`;
}

export function PartnerPaymentStatusCard() {
  // Payment-pipeline totals are mock (fabricated UGX figures). Never show fake
  // money to a partner in production — withhold until wired to PaymentRequest.
  if (!isMockAllowed()) return <InsufficientData surface="your payment status" />;
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

      <MetricStrip
        bare
        columns="grid-cols-1 sm:grid-cols-2 lg:grid-cols-4"
        metrics={partnerPaymentLines.map((line) => ({
          key: line.key,
          label: line.label,
          value: line.count,
          caption: line.amountUgx > 0 ? fmtUgx(line.amountUgx) : line.description,
          tone: CELL_TONE[line.tone],
        }))}
      />
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
