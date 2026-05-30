"use client";

import {
  Building2,
  Calendar,
  CheckCircle2,
  Eye,
  GraduationCap,
  RotateCcw,
  School,
  Users,
  Layers,
  Globe2,
  type LucideIcon,
} from "lucide-react";
import {
  cceoContributionTotal,
  cceoContributions,
  countryActivePlan,
} from "@/lib/country-fund-approvals-mock";
import { cn } from "@/lib/utils";

function fmt(n: number | "—"): string {
  if (n === "—") return "—";
  return n.toLocaleString();
}

// CD plan-detail view. Two distinctions from the PL version:
//   1. Header includes Submitted date alongside Plan Period
//   2. Body adds a CCEO Contribution row below the activity table —
//      4 contributor avatars + their share + a Total CCEO Contribution
//      pill on the right (with % of total plan).
export function CountryFundPlanDetail() {
  const d = countryActivePlan;
  return (
    <article className="card p-4 flex flex-col">
      {/* Header */}
      <header className="flex items-start justify-between gap-3 flex-wrap pb-3 border-b border-[#eef2f4]">
        <div className="min-w-0">
          <h2 className="text-[16px] font-extrabold tracking-tight">
            {d.leadName} — {d.planLabel}
          </h2>
          <div className="text-[11px] muted mt-0.5 inline-flex flex-wrap items-center gap-x-3 gap-y-0.5">
            <span className="inline-flex items-center gap-1.5">
              <Calendar size={10} />
              Plan Period: <span className="font-semibold text-slate-700">{d.planPeriod}</span>
            </span>
            <span className="inline-flex items-center gap-1.5">
              <CheckCircle2 size={10} />
              Submitted: <span className="font-semibold text-slate-700">{d.submitted}</span>
            </span>
          </div>
        </div>
        <div className="text-right shrink-0">
          <span className="inline-flex items-center px-2 py-[2px] rounded-md text-[10px] font-extrabold bg-amber-100 text-amber-700">
            {d.status}
          </span>
          <div className="text-[10px] muted font-bold uppercase tracking-wide mt-1">Total Requested</div>
          <div className="text-[18px] font-extrabold tabular text-slate-900 num-hero glow-emerald">
            UGX {fmt(d.totalRequested)}
          </div>
        </div>
      </header>

      {/* Body — table + snapshot */}
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_240px] gap-4 py-4">
        <div className="min-w-0">
          <h3 className="text-body font-extrabold tracking-tight mb-2">Funding Breakdown from Planned Activities</h3>
          <table className="w-full text-[11.5px]">
            <thead>
              <tr className="text-[9.5px] uppercase tracking-wide muted font-bold border-b border-[#eef2f4]">
                <th className="text-left py-2 pl-1 pr-2">Activity Category</th>
                <th className="text-right py-2 px-2">Planned Qty</th>
                <th className="text-right py-2 px-2">Unit Cost (UGX)</th>
                <th className="text-right py-2 pl-2 pr-1">Total (UGX)</th>
              </tr>
            </thead>
            <tbody>
              {d.lineItems.map((li) => (
                <tr key={li.category} className="border-b border-[#eef2f4] last:border-b-0">
                  <td className="py-1.5 pl-1 pr-2 text-slate-700 font-semibold">{li.category}</td>
                  <td className="py-1.5 px-2 text-right tabular">{fmt(li.qty)}</td>
                  <td className="py-1.5 px-2 text-right tabular muted">{fmt(li.unitCost)}</td>
                  <td className="py-1.5 pl-2 pr-1 text-right tabular font-bold text-slate-900">{fmt(li.total)}</td>
                </tr>
              ))}
              <tr className="border-t-2 border-slate-200">
                <td className="py-1.5 pl-1 pr-2 text-[11.5px] font-bold">Subtotal</td>
                <td colSpan={2} />
                <td className="py-1.5 pl-2 pr-1 text-right tabular font-extrabold text-slate-900">{fmt(d.subtotal)}</td>
              </tr>
              <tr>
                <td className="py-1.5 pl-1 pr-2 muted">Adjustments (Rounding)</td>
                <td colSpan={2} />
                <td className="py-1.5 pl-2 pr-1 text-right tabular text-rose-700 font-semibold">{fmt(d.adjustments)}</td>
              </tr>
              <tr className="border-t-2 border-slate-200 bg-emerald-50/40">
                <td className="py-2 pl-1 pr-2 text-[12px] font-extrabold text-emerald-800">Total Requested</td>
                <td colSpan={2} />
                <td className="py-2 pl-2 pr-1 text-right tabular text-body-lg font-extrabold text-emerald-800 num-hero glow-emerald">
                  UGX {fmt(d.totalAmount)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <aside className="rounded-xl bg-slate-50/60 border border-slate-200/70 p-3 flex flex-col gap-1.5 self-start">
          <h3 className="text-[12px] font-extrabold tracking-tight mb-1">Plan Snapshot</h3>
          <SnapshotItem icon={School}    value={d.snapshot.schoolsByStaff}        label="Planned schools by staff" />
          <SnapshotItem icon={Building2} value="By partners"                       label="Planned school visits" />
          <SnapshotItem icon={Users}     value="Cluster meetings planned"          label="" compact />
          <SnapshotItem icon={GraduationCap} value="Trainings planned"             label={d.snapshot.trainingsPlanned} />
          <SnapshotItem icon={Globe2}    value="Total schools covered"             label={d.snapshot.totalSchoolsCovered} />
          <SnapshotItem icon={Layers}    value="Included CCEO plans"               label={d.snapshot.includedCceoPlans} />
        </aside>
      </div>

      {/* CCEO Contribution strip */}
      <section className="border-t border-[#eef2f4] pt-3 pb-2">
        <div className="flex items-baseline gap-2 mb-2">
          <h3 className="text-body font-extrabold tracking-tight">CCEO Contribution</h3>
          <span className="text-[11px] muted">(Included in Plan)</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 items-stretch">
          {cceoContributions.map((c, i) => (
            <CceoChip key={c.id} c={c} stagger={["stagger-1","stagger-2","stagger-3","stagger-4"][i] ?? ""} />
          ))}
          <div className={cn(
            "rounded-xl border border-emerald-300 bg-gradient-to-br from-emerald-50 to-white p-2.5 flex flex-col justify-center tile-in card-lift cursor-default stagger-5",
          )}>
            <div className="text-[10px] font-bold uppercase tracking-wide text-emerald-700 leading-tight">Total CCEO Contribution</div>
            <div className="text-body-lg font-extrabold tabular text-emerald-800 num-hero glow-emerald mt-0.5">
              {cceoContributionTotal.amount}
            </div>
            <div className="text-[10px] muted font-semibold mt-0.5">
              {cceoContributionTotal.pctOfPlan}% of total plan
            </div>
          </div>
        </div>
      </section>

      {/* Actions */}
      <div className="grid grid-cols-3 gap-2 pt-3 border-t border-[#eef2f4] mt-2">
        <button
          type="button"
          className="inline-flex items-center justify-center gap-1.5 h-10 rounded-xl bg-white border border-[var(--color-edify-border)] text-[12px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors"
        >
          <Eye size={13} />
          View Full Plan
        </button>
        <button
          type="button"
          className="btn btn-primary inline-flex items-center justify-center gap-1.5 h-10 rounded-xl text-body font-extrabold"
        >
          <CheckCircle2 size={13} />
          Approve
        </button>
        <button
          type="button"
          className="inline-flex items-center justify-center gap-1.5 h-10 rounded-xl bg-white border border-rose-200 text-[12px] font-semibold text-rose-700 hover:bg-rose-50 transition-colors"
        >
          <RotateCcw size={13} />
          Return
        </button>
      </div>
    </article>
  );
}

function SnapshotItem({
  icon: Icon,
  value,
  label,
  compact,
}: {
  icon: LucideIcon;
  value: number | string;
  label: string;
  compact?: boolean;
}) {
  return (
    <div className={cn("flex items-start gap-2 rounded-lg bg-white border border-slate-200/70 px-2.5", compact ? "py-1.5" : "py-2")}>
      <span className="w-6 h-6 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center shrink-0">
        <Icon size={12} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[11px] font-extrabold leading-tight text-slate-900 num-hero">{value}</div>
        {label && <div className="text-[9.5px] muted font-semibold leading-tight mt-0.5 truncate">{label}</div>}
      </div>
    </div>
  );
}

function CceoChip({ c, stagger }: { c: typeof cceoContributions[number]; stagger: string }) {
  return (
    <div className={cn("rounded-xl border border-[var(--color-edify-border)] bg-white p-2.5 flex items-center gap-2 card-lift cursor-default tile-in", stagger)}>
      <span className="w-8 h-8 rounded-full grid place-items-center bg-gradient-to-br from-[var(--color-edify-primary)] to-[#344f5f] text-white text-[10px] font-extrabold shadow-sm shrink-0">
        {c.initials}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[11.5px] font-extrabold text-slate-900 truncate">{c.name}</div>
        <div className="text-[11.5px] font-extrabold tabular text-slate-800 leading-tight num-hero">{c.amount}</div>
        <div className="text-[9.5px] muted font-semibold leading-tight">{c.role}</div>
      </div>
    </div>
  );
}
