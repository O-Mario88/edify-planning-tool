"use client";

// Cell drilldown drawer — bottom-aligned slide-up panel.
//
// Opens when the user clicks any non-zero numeric cell in the matrix.
// Shows the activities behind the number: who, where, when, district,
// amount, cost category. Implements the "no number is opaque" rule.

import { Calendar, ExternalLink, MapPin, UserCircle, X } from "lucide-react";
import {
  CATEGORY_HEADER_LABEL,
  type MfrSourceRecord,
} from "@/lib/funds/monthly-fund-request-types";
import type { MfrCellTarget } from "./MonthlyFundRequestMatrix";
import { cn } from "@/lib/utils";

export function CellDrilldownDrawer({
  open,
  target,
  sources,
  onClose,
}: {
  open: boolean;
  target: MfrCellTarget | null;
  sources: MfrSourceRecord[];
  onClose: () => void;
}) {
  if (!open || !target) return null;

  // Filter sources to those that produced the clicked cell. lineId is
  // optional — when omitted (Activity × Week summary view) we aggregate
  // across every staff/partner line and let the drawer surface the
  // full list of source records for that category × week.
  const matching = sources.filter((s) =>
    (target.lineId == null || s.lineId === target.lineId) &&
    s.costCategory === target.category &&
    (target.week == null || s.plannedWeek === target.week),
  );
  const total = matching.reduce((s, m) => s + m.amount, 0);
  const categoryLabel = CATEGORY_HEADER_LABEL[target.category];
  const subtitle = target.week ? ` · Week ${target.week}` : "";

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-end justify-center"
    >
      <button
        type="button"
        aria-label="Close drilldown"
        onClick={onClose}
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
      />
      <article className="card relative w-full max-w-3xl mb-3 mx-3 p-4 max-h-[78vh] overflow-y-auto">
        <header className="flex items-start justify-between gap-3 mb-3">
          <div>
            <div className="text-[10.5px] muted font-bold uppercase tracking-wide">
              Source records
            </div>
            <h2 className="text-[16px] font-extrabold tracking-tight">
              {categoryLabel}{subtitle}
            </h2>
            <div className="text-[11.5px] muted mt-0.5">
              {matching.length} source {matching.length === 1 ? "record" : "records"} ·
              UGX <span className="font-extrabold text-slate-800 tabular">{total.toLocaleString()}</span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-8 h-8 grid place-items-center rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-slate-600"
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </header>

        {matching.length === 0 ? (
          <div className="py-8 text-center text-[12px] muted italic">
            No source records match this cell.
          </div>
        ) : (
          <ul className="flex flex-col gap-2">
            {matching.map((s) => (
              <li
                key={s.id}
                className="rounded-xl border border-[var(--color-edify-border)] bg-white px-3 py-2.5 flex items-start gap-3"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-[12.5px] font-extrabold text-slate-900 truncate">
                    {s.description}
                  </div>
                  <div className="text-[10.5px] muted leading-tight mt-0.5 flex items-center flex-wrap gap-x-2 gap-y-0.5">
                    <span className={cn(
                      "inline-flex items-center px-1.5 py-[1px] rounded-md text-[9.5px] font-extrabold",
                      "bg-emerald-100 text-emerald-700",
                    )}>
                      {s.sourceType.replace(/([A-Z])/g, " $1").trim()}
                    </span>
                    {s.staffName && (
                      <span className="inline-flex items-center gap-1">
                        <UserCircle size={10} /> {s.staffName}
                      </span>
                    )}
                    {s.partnerName && !s.staffName && (
                      <span className="inline-flex items-center gap-1">
                        <UserCircle size={10} /> {s.partnerName}
                      </span>
                    )}
                    {s.district && (
                      <span className="inline-flex items-center gap-1">
                        <MapPin size={10} /> {s.district}
                      </span>
                    )}
                    {s.activityDate && (
                      <span className="inline-flex items-center gap-1">
                        <Calendar size={10} /> {s.activityDate}
                      </span>
                    )}
                    {s.plannedWeek && !s.activityDate && (
                      <span className="inline-flex items-center gap-1">
                        <Calendar size={10} /> Week {s.plannedWeek}
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[13.5px] font-extrabold tabular text-slate-900">
                    UGX {s.amount.toLocaleString()}
                  </div>
                  <button
                    type="button"
                    className="mt-1 inline-flex items-center gap-1 text-[10.5px] font-semibold text-[var(--color-edify-primary)] hover:underline"
                  >
                    Open source <ExternalLink size={9} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </article>
    </div>
  );
}
