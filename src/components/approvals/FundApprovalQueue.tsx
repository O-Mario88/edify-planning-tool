"use client";

import { useState } from "react";
import { Building2, ChevronDown, ChevronLeft, ChevronRight as ChevronRightIcon, Layers, Users, GraduationCap, CheckCircle2 } from "lucide-react";
import { type FundApprovalItem } from "@/lib/fund-approvals-mock";
import { cn } from "@/lib/utils";
import { useUrlState } from "@/hooks/use-url-state";
import { FundPlanInlineDetail } from "./FundPlanInlineDetail";

// "Valid" = ready to approve in bulk (not returned / still in review).
const BULK_APPROVABLE = new Set<FundApprovalItem["status"]>(["Awaiting Approval", "Ready"]);

const STATUS_TONE: Record<FundApprovalItem["status"], string> = {
  "Awaiting Approval": "bg-amber-100   text-amber-700",
  "Needs Review":      "bg-sky-100     text-sky-700",
  "Ready":             "bg-emerald-100 text-emerald-700",
  "Returned":          "bg-rose-100    text-rose-700",
  "Awaiting Review":   "bg-amber-100   text-amber-700",
};

// CCEO Fund Approval Queue.
//
// Each row is now an inline-expanding accordion: clicking the header
// reveals the full plan detail (funding breakdown + snapshot + the
// Approve / Return / View action row) without a side pane. PLs and
// Accountants can walk the queue top-to-bottom and act on each plan in
// place — no context switch to a separate pane.
//
// The URL key (`?plan=fp-X`) still drives which row is open so deep
// links keep working and the right rail / KPI counters can still react
// to the selection.
export function FundApprovalQueue({ queue }: { queue: FundApprovalItem[] }) {
  const queueIds = queue.map((q) => q.id);
  // Default to nothing open. Users explicitly open the row they want
  // to act on; if a deep link points at a plan id, that row opens.
  const [openPlanId, setOpenPlanId] = useUrlState<string>({
    key: "plan",
    defaultValue: "",
    allowed: ["", ...queueIds],
  });

  const toggle = (id: string) => {
    setOpenPlanId(openPlanId === id ? "" : id);
  };

  const [approved, setApproved] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState<string | null>(null);
  const pendingValid = queue.filter((q) => BULK_APPROVABLE.has(q.status) && !approved.has(q.id));

  const approveAllValid = () => {
    if (pendingValid.length === 0) return;
    setApproved((prev) => {
      const next = new Set(prev);
      pendingValid.forEach((q) => next.add(q.id));
      return next;
    });
    setToast(`Approved ${pendingValid.length} valid request${pendingValid.length === 1 ? "" : "s"} — funds released to disbursement.`);
    setTimeout(() => setToast(null), 4000);
  };

  return (
    <article className="card p-3.5 flex flex-col h-full">
      <header className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <div className="flex items-center gap-2">
          <h3 className="text-body-lg font-extrabold tracking-tight">CCEO Fund Approval Queue</h3>
          <span className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-slate-100 text-caption font-extrabold tabular text-slate-700">
            {queue.length}
          </span>
        </div>
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={approveAllValid}
            disabled={pendingValid.length === 0}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-emerald-600 text-white text-[12px] font-extrabold hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <CheckCircle2 size={13} />
            Approve all valid{pendingValid.length > 0 ? ` (${pendingValid.length})` : ""}
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1 text-[11.5px] font-semibold muted whitespace-nowrap"
          >
            Sort by: <span className="text-slate-700 font-bold">Amount</span>
          </button>
        </div>
      </header>

      {toast && (
        <div className="mb-2.5 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[12px] font-semibold text-emerald-800">
          <CheckCircle2 size={14} className="shrink-0" /> {toast}
        </div>
      )}

      {queue.length === 0 ? (
        <div className="flex-1 grid place-items-center py-10">
          <p className="text-[12px] muted text-center max-w-md leading-snug">
            Nothing waiting on you right now. When a CCEO on your team submits
            a weekly fund slip — or you return one for edits — it appears here
            with the funding breakdown and the Approve / Return actions.
          </p>
        </div>
      ) : (
        <ul className="flex flex-col gap-2 flex-1">
          {queue.map((q, i) => (
            <QueueRow
              key={q.id}
              q={q}
              approved={approved.has(q.id)}
              isOpen={q.id === openPlanId}
              onToggle={() => toggle(q.id)}
              stagger={["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5","stagger-6"][i] ?? ""}
            />
          ))}
        </ul>
      )}

      <footer className="mt-3 pt-3 border-t border-[#eef2f4] flex items-center justify-between text-[11px] muted">
        <span>Showing 1–{queue.length} of {queue.length}</span>
        <div className="flex items-center gap-1">
          <button type="button" disabled aria-label="Previous page" className="w-6 h-6 rounded-md border border-[var(--color-edify-border)] grid place-items-center disabled:opacity-40">
            <ChevronLeft size={12} />
          </button>
          <button type="button" disabled aria-label="Next page" className="w-6 h-6 rounded-md border border-[var(--color-edify-border)] grid place-items-center disabled:opacity-40">
            <ChevronRightIcon size={12} />
          </button>
        </div>
      </footer>
    </article>
  );
}

function QueueRow({
  q,
  approved,
  isOpen,
  onToggle,
  stagger,
}: {
  q: FundApprovalItem;
  approved?: boolean;
  isOpen: boolean;
  onToggle: () => void;
  stagger: string;
}) {
  const panelId = `fund-plan-${q.id}-detail`;
  return (
    <li
      className={cn(
        "rounded-xl border bg-white card-lift cursor-pointer tile-in overflow-hidden transition-colors",
        stagger,
        isOpen
          ? "row-active-glow border-transparent bg-emerald-50/40"
          : "border-[var(--color-edify-border)]",
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isOpen}
        aria-controls={panelId}
        aria-label={`${isOpen ? "Collapse" : "Expand"} ${q.cceoName}'s plan`}
        className="w-full p-3 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 rounded-xl"
      >
        <div className="flex items-start gap-2.5">
          <Avatar initials={q.initials} active={q.isActive} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-body font-extrabold text-slate-900 truncate">{q.cceoName}</span>
              {q.isOwnPlan && (
                <span className="inline-flex items-center px-1.5 py-[1px] rounded-md text-[9.5px] font-extrabold bg-slate-100 text-slate-600 uppercase tracking-wide">
                  My Own Plan
                </span>
              )}
            </div>
            <div className="text-caption muted leading-tight mt-0.5 truncate">
              {q.district} · {q.region}
            </div>
            <p className="text-caption muted leading-snug mt-1 line-clamp-1">
              {q.description}
            </p>
          </div>
          <div className="flex flex-col items-end gap-1.5 shrink-0">
            <span className={cn(
              "inline-flex items-center gap-1 px-2 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap",
              approved ? "bg-emerald-100 text-emerald-700" : STATUS_TONE[q.status],
            )}>
              {approved && <CheckCircle2 size={10} />}
              {approved ? "Approved" : q.status}
            </span>
            <span className="text-body-lg font-extrabold tabular text-slate-900 num-hero">
              {q.amount}
            </span>
          </div>
          {/* Mobile / tablet: chevron rotates to show expand/collapse.
              Desktop (xl+): the right pane handles the detail view, so
              the row gets a right-chevron instead — selection is the
              affordance, not expansion. */}
          <ChevronDown
            size={16}
            className={cn(
              "text-slate-400 shrink-0 transition-transform mt-0.5 xl:hidden",
              isOpen && "rotate-180",
            )}
            aria-hidden
          />
          <ChevronRightIcon
            size={16}
            className="text-slate-400 shrink-0 mt-0.5 hidden xl:block"
            aria-hidden
          />
        </div>

        <div className="mt-2 flex items-center flex-wrap gap-x-2 gap-y-1">
          <CountChip icon={Building2}      value={q.counts.visits}    label="Visits" />
          <CountChip icon={Users}          value={q.counts.partners}  label="Partner" />
          <CountChip icon={Layers}         value={q.counts.clusters}  label="Clusters" />
          <CountChip icon={GraduationCap}  value={q.counts.trainings} label="Trainings" />
        </div>
      </button>

      {isOpen && (
        // Inline expansion is only used on mobile + tablet. On xl the
        // queue page renders the detail in a dedicated side pane, so
        // we hide the inline body to avoid the same plan rendering
        // twice and to keep the queue rows compact.
        <div id={panelId} className="px-3 pb-3 cursor-default xl:hidden">
          <FundPlanInlineDetail item={q} />
        </div>
      )}
    </li>
  );
}

function Avatar({ initials, active }: { initials: string; active?: boolean }) {
  return (
    <span className={cn(
      "w-9 h-9 rounded-full grid place-items-center text-[11px] font-extrabold text-white shrink-0 shadow-sm",
      active
        ? "bg-gradient-to-br from-emerald-500 to-emerald-700"
        : "bg-gradient-to-br from-[var(--color-edify-primary)] to-[#344f5f]",
    )}>
      {initials}
    </span>
  );
}

function CountChip({
  icon: Icon,
  value,
  label,
}: {
  icon: typeof Building2;
  value: number;
  label: string;
}) {
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md bg-slate-50 border border-slate-200 text-[10px]">
      <Icon size={9} className="text-slate-500 shrink-0" />
      <span className="font-extrabold tabular text-slate-700">{value}</span>
      <span className="muted font-semibold">{label}</span>
    </span>
  );
}
