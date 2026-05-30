"use client";

// Inline plan detail — the body that renders inside an expanded
// FundApprovalQueue row.
//
// Mirrors what FundPlanDetail used to show in the right pane: header
// row (period + status + total), funding breakdown table, plan
// snapshot, then the FundPlanActionRow with Approve / Return / View.
// The difference is the surrounding chrome: no separate `card` border,
// no duplicate avatar/name (the row already carries those), tighter
// padding so it lives inside the queue row without busting the layout.

import {
  Building2,
  Calendar,
  GraduationCap,
  School,
  Users,
} from "lucide-react";
import { activePlanDetail, type FundApprovalItem } from "@/lib/fund-approvals-mock";
import { cn } from "@/lib/utils";
import { FundPlanActionRow } from "./FundPlanActionRow";

function fmt(n: number | "—"): string {
  if (n === "—") return "—";
  return n.toLocaleString();
}

export function FundPlanInlineDetail({
  item,
}: {
  item: FundApprovalItem;
}) {
  // For now the mock only carries the deep breakdown for one plan;
  // every row reuses that snapshot. When real backend lands, swap to a
  // per-plan fetch keyed by `item.id`.
  const d = activePlanDetail;
  return (
    <div className="mt-3 -mx-1 px-1 pt-3 border-t border-dashed border-[var(--color-edify-border)] flex flex-col gap-3">
      {/* Compact header — period + total + status */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="inline-flex items-center gap-1.5 text-[11px] muted font-semibold">
          <Calendar size={10} />
          <span>{d.planPeriod}</span>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className="text-[9.5px] muted font-bold uppercase tracking-wide">Total Requested</div>
            <div className="text-[15px] font-extrabold tabular text-slate-900 num-hero glow-emerald leading-tight">
              {d.totalRequested}
            </div>
          </div>
        </div>
      </div>

      {/* Funding breakdown + snapshot */}
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_220px] gap-3 lg:gap-4">
        <div className="min-w-0">
          <h4 className="text-[12px] font-extrabold tracking-tight mb-1.5">
            Funding Breakdown
          </h4>
          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-[11.5px]">
              <thead>
                <tr className="text-[9.5px] uppercase tracking-wide muted font-bold border-b border-[#eef2f4]">
                  <th className="text-left py-1.5 pl-1 pr-2">Activity Category</th>
                  <th className="text-right py-1.5 px-2">Qty</th>
                  <th className="text-right py-1.5 px-2">Unit Cost</th>
                  <th className="text-right py-1.5 pl-2 pr-1">Total</th>
                </tr>
              </thead>
              <tbody>
                {d.lineItems.map((li) => (
                  <tr key={li.category} className="border-b border-[#eef2f4] last:border-b-0">
                    <td className="py-1 pl-1 pr-2 text-slate-700 font-semibold">{li.category}</td>
                    <td className="py-1 px-2 text-right tabular">{fmt(li.qty)}</td>
                    <td className="py-1 px-2 text-right tabular muted">{fmt(li.unitCost)}</td>
                    <td className="py-1 pl-2 pr-1 text-right tabular font-bold text-slate-900">{fmt(li.total)}</td>
                  </tr>
                ))}
                <tr className="border-t-2 border-slate-200">
                  <td className="py-1.5 pl-1 pr-2 text-[11.5px] font-bold">Subtotal</td>
                  <td colSpan={2} />
                  <td className="py-1.5 pl-2 pr-1 text-right tabular font-extrabold text-slate-900">{fmt(d.subtotal)}</td>
                </tr>
                <tr>
                  <td className="py-1 pl-1 pr-2 muted">Adjustments (Rounding)</td>
                  <td colSpan={2} />
                  <td className="py-1 pl-2 pr-1 text-right tabular text-rose-700 font-semibold">{fmt(d.adjustments)}</td>
                </tr>
                <tr className="border-t-2 border-slate-200 bg-emerald-50/40">
                  <td className="py-1.5 pl-1 pr-2 text-[12px] font-extrabold text-emerald-800">Total Requested</td>
                  <td colSpan={2} />
                  <td className="py-1.5 pl-2 pr-1 text-right tabular text-body-lg font-extrabold text-emerald-800 num-hero glow-emerald">
                    UGX {fmt(d.totalAmount)}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <aside
          className={cn(
            // On xl the snapshot is a 220 px right rail — vertical
            // stack reads naturally there. Below xl it spans the full
            // card width, so the previous vertical stack left a tall
            // column of dead space. Flip to a 2-col mobile / 4-col
            // tablet grid so the four metrics fill the row.
            "rounded-xl p-3 self-start",
            "grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-1 gap-2",
          )}
        >
          <h4 className="text-[11.5px] font-extrabold tracking-tight col-span-2 sm:col-span-4 xl:col-span-1 mb-1">
            Plan Snapshot
          </h4>
          <SnapshotItem icon={School}        value={d.snapshot.schoolsPlannedByStaff}   label="Planned schools by staff" />
          <SnapshotItem icon={Building2}     value="By partners"                        label="Planned school visits" />
          <SnapshotItem icon={Users}         value={d.snapshot.clusterMeetingsPlanned}  label="Cluster meetings planned" />
          <SnapshotItem icon={GraduationCap} value={d.snapshot.trainingsPlanned}        label="Trainings planned" sublabel="Cluster + In-School" />
        </aside>
      </div>

      {/* Actions */}
      <FundPlanActionRow planId={item.id} currentStatus={item.status} />
    </div>
  );
}

function SnapshotItem({
  icon: Icon,
  value,
  label,
  sublabel,
}: {
  icon: typeof Building2;
  value: number | string;
  label: string;
  sublabel?: string;
}) {
  return (
    <div className="flex items-start gap-2 rounded-lg bg-white px-2.5 py-1.5">
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
