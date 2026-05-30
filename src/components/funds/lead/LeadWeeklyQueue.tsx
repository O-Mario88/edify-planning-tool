"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  RotateCcw,
  ChevronDown,
} from "lucide-react";
import { weeklyFundRequests } from "@/lib/funds/weekly-fund-mock";
import {
  computeRiskFlags,
  formatMoney,
  priorWeekClosedFor,
} from "@/lib/funds/weekly-fund-engine";
import { StatusChip } from "@/components/funds/StatusChip";
import { RISK_LABEL } from "@/lib/funds/weekly-fund-types";
import type { WeeklyFundRequest } from "@/lib/funds/weekly-fund-types";
import { cn } from "@/lib/utils";
import { LeadRequestDetail } from "./LeadRequestDetail";

type QueueTab = "submitted" | "accountability" | "all";

// Vertical scroll cap removed — with inline-expanding rows the queue
// grows naturally with content and the parent page is the scroll
// container. The old 560px max-height worked well for collapsed-only
// rows but would clip a fully-opened request detail.

// Lead-side queue. Three sub-tabs (Pending Approval · Pending
// Accountability · All Active) + scrollable list so a long backlog
// remains contained inside the card without pager controls.
export function LeadWeeklyQueue({
  selectedId,
  onSelect,
}: {
  selectedId?: string;
  onSelect?: (id: string) => void;
}) {
  const [tab, setTab] = useState<QueueTab>("submitted");
  const leadId = "STF-DM-014";

  const filters: Record<QueueTab, (r: WeeklyFundRequest) => boolean> = {
    submitted: (r) => r.status === "SUBMITTED",
    accountability: (r) => r.status === "ACCOUNTABILITY_SUBMITTED",
    all: (r) =>
      !["CLOSED", "CANCELLED", "ARCHIVED", "AUTO_GENERATED"].includes(r.status),
  };

  const rows = useMemo(
    () =>
      weeklyFundRequests
        .filter((r) => r.programLeadId === leadId)
        .filter(filters[tab]),
    // filters is a static map keyed by tab; the lint dep array can
    // safely depend only on `tab` here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tab],
  );

  const pageRows = rows;

  const tabs: { key: QueueTab; label: string; count: number }[] = [
    {
      key: "submitted",
      label: "Pending Approval",
      count: weeklyFundRequests.filter(
        (r) => r.programLeadId === leadId && r.status === "SUBMITTED",
      ).length,
    },
    {
      key: "accountability",
      label: "Accountability",
      count: weeklyFundRequests.filter(
        (r) =>
          r.programLeadId === leadId && r.status === "ACCOUNTABILITY_SUBMITTED",
      ).length,
    },
    {
      key: "all",
      label: "All Active",
      count: weeklyFundRequests.filter(
        (r) => r.programLeadId === leadId && filters.all(r),
      ).length,
    },
  ];

  return (
    <article className="card p-3.5 flex flex-col">
      <header className="flex items-center gap-1 mb-2.5 flex-wrap">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={cn(
              "h-8 px-2.5 rounded-lg text-[11.5px] font-extrabold transition-colors inline-flex items-center gap-1.5",
              tab === t.key
                ? "bg-slate-900 text-white"
                : "bg-white text-slate-600 border border-[var(--color-edify-border)] hover:bg-slate-50",
            )}
          >
            {t.label}
            <span
              className={cn(
                "inline-flex items-center justify-center min-w-[18px] h-[16px] px-1 rounded-md text-[9.5px] font-extrabold",
                tab === t.key
                  ? "bg-white/15 text-white"
                  : "bg-slate-100 text-slate-700",
              )}
            >
              {t.count}
            </span>
          </button>
        ))}
      </header>

      <ul className="flex flex-col gap-1.5 -mx-1 px-1 rounded-md">
        {rows.length === 0 && (
          <li className="text-[12px] muted italic py-6 text-center">
            Inbox zero — nothing waiting in this queue.
          </li>
        )}
        {pageRows.map((r, i) => {
          const stagger = `stagger-${(i % 6) + 1}`;
          const selected = selectedId === r.id;
          const priorClosed = priorWeekClosedFor(r, weeklyFundRequests);
          const risks = computeRiskFlags(r, {
            priorWeekClosed: priorClosed,
            priorWeekMissingReceipts: r.flags.includes("MISSING_RECEIPTS"),
            priorWeekMissingSalesforceIds: false,
            staffOnLeave: false,
          });
          const panelId = `lead-req-${r.id}-detail`;
          return (
            <li key={r.id}>
              <div
                className={cn(
                  "rounded-xl border bg-white tile-in transition-colors overflow-hidden",
                  selected
                    ? "row-active-glow border-transparent"
                    : "border-[var(--color-edify-border)] hover:border-slate-300",
                  stagger,
                )}
              >
                <button
                  type="button"
                  onClick={() => onSelect?.(r.id)}
                  aria-expanded={selected}
                  aria-controls={panelId}
                  className="w-full text-left p-2.5 cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-edify-primary)] rounded-lg min-h-[88px]"
                >
                  <div className="flex items-center gap-2.5">
                    <span className="w-8 h-8 rounded-full grid place-items-center text-caption font-extrabold text-white shrink-0 bg-gradient-to-br from-[var(--color-edify-primary)] to-[#344f5f]">
                      {r.staffName.split(" ").map((p) => p[0]).join("").slice(0, 2)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[12px] font-extrabold text-slate-900 truncate">
                        {r.staffName}
                      </div>
                      <div className="text-[10px] muted font-semibold truncate">
                        {r.district} · Week {r.period.weekOfMonth} · {r.activities.length} act.
                      </div>
                      {r.weeklyPlanId && (
                        <div className="text-[9.5px] muted font-semibold truncate mt-0.5">
                          <span className="inline-flex items-center gap-1 text-emerald-700">
                            <CheckCircle2 size={9} />
                            Auto-extracted from {r.weeklyPlanId}
                          </span>
                        </div>
                      )}
                    </div>
                    <div className="text-right shrink-0">
                      <div className="text-body font-extrabold tabular num-hero text-slate-900 leading-none">
                        {formatMoney(r.requestedAmount)}
                      </div>
                      <div className="text-[9.5px] muted font-semibold mt-0.5">requested</div>
                    </div>
                    <ChevronDown
                      size={14}
                      aria-hidden
                      className={cn(
                        "text-slate-400 shrink-0 transition-transform",
                        selected && "rotate-180",
                      )}
                    />
                  </div>
                  <div className="mt-1.5 flex items-center justify-between gap-2">
                    <StatusChip status={r.status} size="xs" />
                    <div className="flex items-center gap-1 flex-wrap justify-end max-w-[60%]">
                      {risks.slice(0, 2).map((rk) => (
                        <span
                          key={rk}
                          className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold bg-amber-100 text-amber-700 border border-amber-200 whitespace-nowrap"
                        >
                          <AlertTriangle size={9} />
                          {RISK_LABEL[rk]}
                        </span>
                      ))}
                      {risks.length > 2 && (
                        <span className="inline-flex items-center px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold bg-slate-100 text-slate-700 border border-slate-200">
                          +{risks.length - 2}
                        </span>
                      )}
                      {r.adjustments.length > 0 && (
                        <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold bg-violet-100 text-violet-700 border border-violet-200 whitespace-nowrap">
                          <RotateCcw size={9} /> {r.adjustments.length} adj.
                        </span>
                      )}
                    </div>
                  </div>
                </button>

                {selected && (
                  <div id={panelId} className="px-2.5 pb-2.5">
                    {/* Inline detail — full LeadRequestDetail. The component
                        already renders inside its own `card` chrome; we
                        suppress that here with `card-flat-inline` so we
                        don't get a double-bordered look inside the row. */}
                    <div className="rounded-xl border border-[var(--color-edify-border)] bg-slate-50/40">
                      <LeadRequestDetail request={r} />
                    </div>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {/* Footer — auto-lock reassurance + count. Pagination removed
          in favour of in-card vertical scroll above. */}
      <footer className="flex items-center justify-between gap-2 mt-3 pt-2.5 border-t border-dashed border-[#eef2f4] text-caption muted font-semibold">
        <span className="inline-flex items-center gap-1 truncate">
          <CheckCircle2 size={11} className="text-emerald-600 shrink-0" />
          <span className="truncate">Auto-locked: must match the approved plan.</span>
        </span>
        <span className="shrink-0 text-caption muted font-semibold">
          {rows.length} item{rows.length === 1 ? "" : "s"}
        </span>
      </footer>
    </article>
  );
}
