"use client";

import {
  Building2,
  Calendar,
  GraduationCap,
  School,
  Users,
} from "lucide-react";
import { activePlanDetail, type FundApprovalItem } from "@/lib/fund-approvals-mock";
import { cn } from "@/lib/utils";
import { useUrlState } from "@/hooks/use-url-state";
import { FundPlanActionRow } from "./FundPlanActionRow";

// Resolve the currently selected fund-plan id from the URL (?plan=fp-X),
// falling back to whichever queue row is marked active. Keeps
// FundApprovalQueue + FundPlanDetail in lockstep via the URL without
// prop-drilling state through the page.
function useSelectedPlanId(queue: FundApprovalItem[]): string {
  const queueIds = queue.map((q) => q.id);
  const fallback = queue.find((q) => q.isActive)?.id ?? queue[0]?.id ?? "";
  const [planId] = useUrlState<string>({
    key: "plan",
    defaultValue: fallback,
    allowed: queueIds,
  });
  return planId;
}

function fmt(n: number | "—"): string {
  if (n === "—") return "—";
  return n.toLocaleString();
}

// Middle column — the full fund plan for the currently selected CCEO.
// Header with name + period + total + status pill · funding breakdown
// table · plan snapshot · primary action row (View Full Plan · Approve
// · Return).
export function FundPlanDetail({ queue }: { queue: FundApprovalItem[] }) {
  const d = activePlanDetail;
  const selectedPlanId = useSelectedPlanId(queue);
  // Source of truth for the live status is the queue (which gets
  // updated by the server action + Prisma swap-ready). `activePlanDetail`
  // is the deep-detail mock that doesn't change row-by-row yet.
  const selectedItem = queue.find((q) => q.id === selectedPlanId) ?? queue[0];
  if (!selectedItem) {
    return (
      <article className="card p-6 text-center">
        <p className="text-[12px] muted leading-snug">
          No fund request selected. Once a CCEO submits a weekly slip, it
          will appear in the queue and the plan detail opens here.
        </p>
      </article>
    );
  }
  return (
    <article className="card p-4 flex flex-col">
      {/* Header */}
      <header className="flex items-start justify-between gap-3 flex-wrap pb-3 border-b border-[#eef2f4]">
        <div className="min-w-0">
          <h2 className="text-[16px] font-extrabold tracking-tight">
            {d.cceoName} — {d.planLabel}
          </h2>
          <div className="text-[11px] muted mt-0.5 inline-flex items-center gap-1.5">
            <Building2 size={10} />
            <span>{d.district} · {d.region}</span>
          </div>
        </div>
        <div className="flex items-center gap-4 shrink-0">
          <div className="text-right">
            <div className="text-[10px] muted font-bold uppercase tracking-wide inline-flex items-center gap-1">
              <Calendar size={9} />
              Plan Period
            </div>
            <div className="text-[11.5px] font-semibold text-slate-700 mt-0.5">{d.planPeriod}</div>
          </div>
          <div className="text-right">
            <span className={cn(
              "inline-flex items-center px-2 py-[2px] rounded-md text-[10px] font-extrabold",
              selectedItem.status === "Ready"             && "bg-emerald-100 text-emerald-700",
              selectedItem.status === "Returned"          && "bg-rose-100 text-rose-700",
              selectedItem.status === "Awaiting Approval" && "bg-amber-100 text-amber-700",
              selectedItem.status === "Awaiting Review"   && "bg-amber-100 text-amber-700",
              selectedItem.status === "Needs Review"      && "bg-sky-100 text-sky-700",
            )}>
              {selectedItem.status}
            </span>
            <div className="text-[10px] muted font-bold uppercase tracking-wide mt-1">Total Requested</div>
            <div className="text-[18px] font-extrabold tabular text-slate-900 num-hero glow-emerald">
              {d.totalRequested}
            </div>
          </div>
        </div>
      </header>

      {/* Body — funding table stacked above the plan snapshot. The
          earlier `1fr 220px` xl split put the snapshot in an awkward
          right rail that left dead vertical space when the table was
          short; stacking matches the mobile reading order and lets
          the snapshot fill the card width as a clean metric strip. */}
      <div className="flex flex-col gap-4 py-4">
        {/* Funding Breakdown table */}
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

        {/* Plan Snapshot — full-width metric strip below the funding
            table. Horizontal grid so the 4 metrics fill the row
            instead of stacking down a narrow right rail. */}
        <aside className="rounded-xl p-3 grid grid-cols-2 sm:grid-cols-4 gap-2">
          <h3 className="text-[12px] font-extrabold tracking-tight col-span-2 sm:col-span-4 mb-1">
            Plan Snapshot
          </h3>
          <SnapshotItem
            icon={School}
            value={d.snapshot.schoolsPlannedByStaff}
            label="Planned schools by staff"
          />
          <SnapshotItem
            icon={Building2}
            value="By partners"
            label="Planned school visits"
          />
          <SnapshotItem
            icon={Users}
            value={d.snapshot.clusterMeetingsPlanned}
            label="Cluster meetings planned"
          />
          <SnapshotItem
            icon={GraduationCap}
            value={d.snapshot.trainingsPlanned}
            label="Trainings planned"
            sublabel="Cluster + In-School"
          />
        </aside>
      </div>

      {/* Actions — wired to fund-plan server actions. */}
      <FundPlanActionRow
        planId={selectedItem.id}
        currentStatus={selectedItem.status}
      />
    </article>
  );
}

function SnapshotItem({
  icon: Icon,
  value,
  label,
  sublabel,
  compact,
}: {
  icon: typeof Building2;
  value: number | string;
  label: string;
  sublabel?: string;
  compact?: boolean;
}) {
  return (
    <div className={cn("flex items-start gap-2 rounded-lg bg-white px-2.5 py-2", compact && "py-1.5")}>
      <span className="w-6 h-6 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center shrink-0">
        <Icon size={12} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[11px] font-extrabold tabular leading-tight text-slate-900 num-hero">
          {value}
        </div>
        <div className="text-[9.5px] muted font-semibold leading-tight mt-0.5 truncate">{label}</div>
        {sublabel && (
          <div className="text-[9px] muted leading-tight truncate">{sublabel}</div>
        )}
      </div>
    </div>
  );
}
