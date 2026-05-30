// PartnerEvidenceQualityPanel — small quality-metrics card showing
// the partner's trailing 30-day evidence performance. Encourages
// quality without overwhelming — 5 simple numbers, one tone per row.

import { Sparkles, RotateCcw, Clock, ShieldCheck, XCircle, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { evidenceQualityMetrics } from "@/lib/partner/partner-evidence-mock";

type Row = {
  label: string;
  value: string;
  caption: string;
  Icon: LucideIcon;
  tone: "emerald" | "amber" | "blue" | "rose";
};

export function PartnerEvidenceQualityPanel() {
  const m = evidenceQualityMetrics;
  const rows: Row[] = [
    { label: "Completion rate",   value: `${m.completionRatePct}%`,        caption: "Required items uploaded",     Icon: Sparkles,    tone: "emerald" },
    { label: "Returned rate",     value: `${m.returnedRatePct}%`,          caption: "Of submissions returned",      Icon: RotateCcw,   tone: m.returnedRatePct > 10 ? "rose" : "amber" },
    { label: "Avg correction",    value: `${m.avgCorrectionDays} days`,    caption: "Median fix turnaround",        Icon: Clock,       tone: "amber" },
    { label: "M&E verified",      value: `${m.mneVerificationRatePct}%`,   caption: "Of confirmed → counted",       Icon: ShieldCheck, tone: "blue" },
    { label: "Rejected",          value: String(m.rejectedCount),           caption: "Past 30 days",                 Icon: XCircle,     tone: m.rejectedCount > 0 ? "rose" : "emerald" },
  ];

  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h3 className="text-body-lg font-extrabold tracking-tight">Evidence Quality</h3>
          <p className="text-[11.5px] muted mt-0.5">{m.windowLabel}</p>
        </div>
      </header>
      <ul className="grid grid-cols-2 lg:grid-cols-5 gap-2.5">
        {rows.map((r) => <MetricCard key={r.label} row={r} />)}
      </ul>
    </section>
  );
}

const TONE: Record<Row["tone"], { bg: string; text: string }> = {
  emerald: { bg: "bg-emerald-50", text: "text-emerald-700" },
  amber:   { bg: "bg-amber-50",   text: "text-amber-700"   },
  blue:    { bg: "bg-blue-50",    text: "text-blue-700"    },
  rose:    { bg: "bg-rose-50",    text: "text-rose-700"    },
};

function MetricCard({ row }: { row: Row }) {
  const t = TONE[row.tone];
  return (
    <li className="rounded-xl border border-[var(--color-edify-divider)] bg-white p-3">
      <div className="flex items-center gap-2">
        <span className={cn("grid place-items-center h-7 w-7 rounded-md", t.bg, t.text)}>
          <row.Icon size={13} />
        </span>
        <div className="text-[10px] uppercase tracking-wide font-bold muted">{row.label}</div>
      </div>
      <div className={cn("text-[18px] font-extrabold tabular num-hero mt-1.5 leading-none", t.text)}>
        {row.value}
      </div>
      <div className="text-caption muted mt-1">{row.caption}</div>
    </li>
  );
}
