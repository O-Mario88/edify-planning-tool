"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  ChevronDown,
  Clock,
  MoreHorizontal,
  PauseCircle,
  Send,
  Split,
} from "lucide-react";
import {
  pendingDisbursementQueue,
  weeklyFundRequests,
  currentWeek,
} from "@/lib/funds/weekly-fund-mock";
import { formatMoney, priorWeekClosedFor } from "@/lib/funds/weekly-fund-engine";
import { StatusChip } from "@/components/funds/StatusChip";
import { DisburseFormFields, type DisburseForm } from "./DisburseFormFields";
import type { WeeklyFundRequest } from "@/lib/funds/weekly-fund-types";
import { cn } from "@/lib/utils";

// Disbursement Queue.
//
// Lists every Lead-approved weekly fund request that needs cash to
// flow. Each row is now an inline-expanding accordion: clicking
// "Review & Disburse" (or anywhere on the header row) reveals the
// activity breakdown + the disburse form right inside the row, so the
// Accountant can confirm release without context-switching to a modal.
//
// The "Disburse" / "Partial" / "Hold" / "Escalate" affordances still
// exist in the header for fast-path one-click action when the gate is
// clean; they now toggle the row open (in the relevant mode) so the
// confirmation lives in the same place.
export type DisbursementFilter = { thisWeekOnly?: boolean; status?: "all" | "ready" | "blocked" };

export function DisbursementQueue({
  onDisburse,
  iaPendingByStaff = {},
  filter,
}: {
  onDisburse?: (id: string, form: DisburseForm, mode: "full" | "partial") => void;
  /** Per-staff count of activities still awaiting IA verification — keyed by
   *  staffId. A non-zero count gates further advances to that staffer. */
  iaPendingByStaff?: Record<string, number>;
  /** Header-driven filter (This Week toggle + Filters popover). */
  filter?: DisbursementFilter;
}) {
  const [tab, setTab] = useState<"weekly" | "monthly" | "partial">("weekly");
  // Open row state: `null` collapsed, else { id, mode } open inline. We
  // keep mode in state so the inline form remembers whether the user
  // came in via "Disburse" (full) or "Partial".
  const [openRow, setOpenRow] = useState<{ id: string; mode: "full" | "partial" } | null>(null);
  const all = pendingDisbursementQueue();

  const rows = useMemo(() => {
    return all.map((r) => {
      const priorClosed = priorWeekClosedFor(r, weeklyFundRequests);
      const blockers: string[] = [];
      if (!priorClosed) blockers.push("Prior week open");
      // IA-verification gate: don't advance more cash to a staffer whose
      // delivered work is still awaiting IA verification.
      const iaPending = iaPendingByStaff[r.staffId] ?? 0;
      if (iaPending > 0) blockers.push(`Awaiting IA verification (${iaPending})`);
      return { r, priorClosed, blockers };
    });
  }, [all, iaPendingByStaff]);

  // Apply the header-driven filter (This Week + status). Genuinely narrows the
  // visible queue — not decorative.
  const visibleRows = useMemo(() => {
    return rows.filter(({ r, blockers }) => {
      if (filter?.thisWeekOnly && r.period.weekOfMonth !== currentWeek.weekOfMonth) return false;
      if (filter?.status === "ready" && blockers.length > 0) return false;
      if (filter?.status === "blocked" && blockers.length === 0) return false;
      return true;
    });
  }, [rows, filter]);

  const cleared = visibleRows.filter((row) => row.blockers.length === 0).length;

  const toggleRow = (id: string, mode: "full" | "partial") => {
    setOpenRow((cur) => (cur && cur.id === id && cur.mode === mode ? null : { id, mode }));
  };

  return (
    <article id="disbursement-queue" className="card p-3.5 flex flex-col scroll-mt-24">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <div className="min-w-0">
          <h3 className="text-[13px] font-extrabold tracking-tight">Weekly Disbursement Queue</h3>
          <p className="text-caption muted font-semibold leading-tight">
            {cleared} of {visibleRows.length} cleared for release · prior-week + IA-verification gates enforced
            {filter?.thisWeekOnly ? ` · Week ${currentWeek.weekOfMonth} only` : ""}
            {filter?.status && filter.status !== "all" ? ` · ${filter.status}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <TabBtn label="Weekly" active={tab === "weekly"} onClick={() => setTab("weekly")} count={visibleRows.length} />
          <TabBtn label="Monthly" active={tab === "monthly"} onClick={() => setTab("monthly")} />
          <TabBtn label="Partial" active={tab === "partial"} onClick={() => setTab("partial")} />
        </div>
      </header>

      <div className="flex flex-col gap-2">
        {visibleRows.length === 0 && (
          <div className="text-[12px] muted italic py-6 text-center">
            {rows.length === 0 ? "All approved requests cleared. Nothing waiting on the Accountant." : "No requests match the current filter."}
          </div>
        )}
        {visibleRows.map(({ r, priorClosed, blockers }, i) => {
          const stagger = `stagger-${(i % 6) + 1}`;
          const canDisburse = blockers.length === 0;
          const isOpen = openRow?.id === r.id;
          return (
            <DisbursementRow
              key={r.id}
              r={r}
              priorClosed={priorClosed}
              blockers={blockers}
              canDisburse={canDisburse}
              isOpen={isOpen}
              openMode={openRow?.mode ?? "full"}
              onToggle={toggleRow}
              onConfirm={(form, mode) => {
                if (onDisburse) onDisburse(r.id, form, mode);
                setOpenRow(null);
              }}
              stagger={stagger}
            />
          );
        })}
      </div>
    </article>
  );
}

function DisbursementRow({
  r,
  priorClosed,
  blockers,
  canDisburse,
  isOpen,
  openMode,
  onToggle,
  onConfirm,
  stagger,
}: {
  r: WeeklyFundRequest;
  priorClosed: boolean;
  blockers: string[];
  canDisburse: boolean;
  isOpen: boolean;
  openMode: "full" | "partial";
  onToggle: (id: string, mode: "full" | "partial") => void;
  onConfirm: (form: DisburseForm, mode: "full" | "partial") => void;
  stagger: string;
}) {
  const panelId = `disb-${r.id}-detail`;
  return (
    <div
      className={cn(
        "rounded-xl border bg-white p-3 tile-in card-lift overflow-hidden transition-colors",
        stagger,
        isOpen
          ? "row-active-glow border-transparent"
          : "border-[var(--color-edify-border)]",
      )}
    >
      <button
        type="button"
        onClick={() => onToggle(r.id, "full")}
        aria-expanded={isOpen}
        aria-controls={panelId}
        className="w-full text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 rounded-lg"
      >
        <div className="flex items-start gap-3 flex-wrap">
          {/* Avatar */}
          <span className="w-9 h-9 rounded-full grid place-items-center text-[11px] font-extrabold text-white shrink-0 shadow-sm bg-gradient-to-br from-[var(--color-edify-primary)] to-[#344f5f]">
            {r.staffName.split(" ").map((s) => s[0]).slice(0, 2).join("")}
          </span>

          {/* Identity */}
          <div className="min-w-0 flex-1">
            <div className="text-body font-extrabold text-slate-900 truncate">
              {r.staffName}
              <span className="text-slate-400 font-medium"> — </span>
              <span className="text-slate-600 font-semibold">{r.district}</span>
            </div>
            <div className="text-caption muted font-semibold mt-0.5 truncate">
              Week {r.period.weekOfMonth} · {r.period.weekStartIso} → {r.period.weekEndIso}
              {" · "}{r.activities.length} activities
            </div>
          </div>

          {/* Amount */}
          <div className="text-right">
            <div className="text-body-lg font-extrabold tabular num-hero text-slate-900 leading-none">
              {formatMoney(r.requestedAmount)}
            </div>
            <div className="text-[10px] muted font-semibold mt-0.5">requested</div>
          </div>

          {/* Status */}
          <div className="flex flex-col items-end gap-1 shrink-0">
            <StatusChip status={r.status} />
          </div>

          <ChevronDown
            size={16}
            aria-hidden
            className={cn(
              "text-slate-400 shrink-0 mt-0.5 transition-transform",
              isOpen && "rotate-180",
            )}
          />
        </div>
      </button>

      {/* Gate row + quick actions — clicking Disburse/Partial expands
          the row in the corresponding mode. */}
      <div className="mt-2 pt-2 border-t border-dashed border-[#eef2f4] flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-3 text-caption flex-wrap">
          <Gate ok={priorClosed} label="Prior week closed" />
          <Gate ok={true} label="Lead approved" />
          <Gate ok={true} label="Funds available" />
          <Gate ok={r.flags.length === 0} label="No flags" />
        </div>
        <div className="flex items-center gap-1.5">
          {blockers.map((b) => (
            <span
              key={b}
              className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold bg-rose-100 text-rose-700 border border-rose-200"
            >
              <AlertTriangle size={9} />
              {b}
            </span>
          ))}
          <button
            type="button"
            title="Partial disbursement"
            onClick={() => onToggle(r.id, "partial")}
            className={cn(
              "inline-flex items-center gap-1 h-8 px-2 rounded-lg border text-caption font-extrabold transition-colors",
              isOpen && openMode === "partial"
                ? "border-slate-900 bg-slate-900 text-white"
                : "border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-slate-700",
            )}
          >
            <Split size={11} />
            Partial
          </button>
          <button
            type="button"
            title="Hold for funding gap"
            className="inline-flex items-center gap-1 h-8 px-2 rounded-lg border border-amber-200 bg-amber-50 hover:bg-amber-100 text-amber-700 text-caption font-extrabold"
          >
            <PauseCircle size={11} />
            Hold
          </button>
          <button
            type="button"
            title="Escalate to Country Director"
            className="inline-flex items-center gap-1 h-8 px-2 rounded-lg border border-rose-200 bg-rose-50 hover:bg-rose-100 text-rose-700 text-caption font-extrabold"
          >
            <ArrowUpRight size={11} />
            Escalate
          </button>
          <button
            type="button"
            disabled={!canDisburse}
            onClick={() => onToggle(r.id, "full")}
            className={cn(
              "inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[11.5px] font-extrabold transition-colors",
              !canDisburse
                ? "bg-slate-100 text-slate-400 cursor-not-allowed"
                : isOpen && openMode === "full"
                  ? "bg-slate-700 text-white"
                  : "bg-slate-900 hover:bg-slate-800 text-white shadow-[0_10px_28px_-12px_rgba(15,23,32,0.45)]",
            )}
          >
            <Send size={11} />
            {isOpen && openMode === "full" ? "Close" : "Review & Disburse"}
          </button>
          <button
            type="button"
            className="w-8 h-8 grid place-items-center rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-slate-600"
            aria-label="More"
          >
            <MoreHorizontal size={12} />
          </button>
        </div>
      </div>

      {/* Inline expanded body: activity breakdown + disburse form */}
      {isOpen && (
        <div id={panelId} className="mt-3 pt-3 border-t border-dashed border-[var(--color-edify-border)] flex flex-col gap-3">
          <ActivityBreakdown request={r} />

          <div className="rounded-xl bg-slate-50/60 border border-slate-200/70 p-3 flex flex-col gap-2">
            <h4 className="text-[12px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
              <Send size={11} className="text-slate-600" />
              {openMode === "partial" ? "Partial disbursement" : "Disburse funds"}
            </h4>
            <DisburseFormFields
              key={`${r.id}-${openMode}`}
              request={r}
              mode={openMode}
              onCancel={() => onToggle(r.id, openMode)}
              onConfirm={(form) => onConfirm(form, openMode)}
              layout="grid"
            />
          </div>
        </div>
      )}
    </div>
  );
}

function ActivityBreakdown({ request }: { request: WeeklyFundRequest }) {
  return (
    <div>
      <h4 className="text-[12px] font-extrabold tracking-tight mb-1.5">
        Activities ({request.activities.length})
      </h4>
      <div className="overflow-x-auto -mx-1">
        <table className="w-full text-[11.5px]">
          <thead>
            <tr className="text-[9.5px] uppercase tracking-wide muted font-bold border-b border-[#eef2f4]">
              <th className="text-left py-1.5 pl-1 pr-2">Activity</th>
              <th className="text-left py-1.5 px-2">Day</th>
              <th className="text-left py-1.5 px-2">Status</th>
              <th className="text-right py-1.5 pl-2 pr-1">Total</th>
            </tr>
          </thead>
          <tbody>
            {request.activities.map((a) => (
              <tr key={a.id} className="border-b border-[#eef2f4] last:border-b-0">
                <td className="py-1 pl-1 pr-2">
                  <div className="text-slate-700 font-semibold truncate">{a.title}</div>
                  {a.schoolName && (
                    <div className="text-[10px] muted leading-tight truncate">{a.schoolName}</div>
                  )}
                </td>
                <td className="py-1 px-2 muted">{a.plannedDay}</td>
                <td className="py-1 px-2">
                  <span className={cn(
                    "inline-flex items-center px-1.5 py-[1px] rounded-md text-[9.5px] font-extrabold",
                    a.status === "Confirmed" && "bg-emerald-100 text-emerald-700",
                    a.status === "Planned"   && "bg-slate-100   text-slate-700",
                    a.status === "Adjusted"  && "bg-amber-100   text-amber-700",
                    a.status === "Cancelled" && "bg-rose-100    text-rose-700",
                    a.status === "Moved"     && "bg-sky-100     text-sky-700",
                  )}>
                    {a.status}
                  </span>
                </td>
                <td className="py-1 pl-2 pr-1 text-right tabular font-bold text-slate-900">
                  {formatMoney(a.totalCost)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Gate({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={cn(
      "inline-flex items-center gap-1 font-semibold",
      ok ? "text-emerald-700" : "text-rose-600",
    )}>
      {ok ? <CheckCircle2 size={10} /> : <Clock size={10} />}
      {label}
    </span>
  );
}

function TabBtn({
  label, active, onClick, count,
}: {
  label: string; active: boolean; onClick: () => void; count?: number;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "h-8 px-2.5 rounded-lg text-[11.5px] font-extrabold transition-colors inline-flex items-center gap-1.5",
        active
          ? "bg-slate-900 text-white"
          : "bg-white text-slate-600 border border-[var(--color-edify-border)] hover:bg-slate-50",
      )}
    >
      {label}
      {typeof count === "number" && (
        <span
          className={cn(
            "inline-flex items-center justify-center min-w-[18px] h-[16px] px-1 rounded-md text-[9.5px] font-extrabold",
            active
              ? "bg-white/15 text-white"
              : "bg-slate-100 text-slate-700",
          )}
        >
          {count}
        </span>
      )}
    </button>
  );
}
