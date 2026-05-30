"use client";

import { AlertCircle, ArrowUpRight, Bell, CheckCircle2, Clock } from "lucide-react";
import { receiptTrackerRows, type ReceiptTrackerRow } from "@/lib/accountant-console-mock";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<
  ReceiptTrackerRow["status"],
  { chip: string; Icon: typeof Clock; pillBorder: string; pillBg: string; avatar: string }
> = {
  Awaiting:  { chip: "bg-amber-50   text-amber-700   ring-1 ring-amber-200/70",   Icon: Clock,        pillBorder: "ring-amber-100",   pillBg: "bg-amber-50/30",   avatar: "from-amber-400 to-amber-600" },
  Confirmed: { chip: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200/70", Icon: CheckCircle2, pillBorder: "ring-emerald-100", pillBg: "bg-emerald-50/30", avatar: "from-emerald-400 to-emerald-600" },
  Disputed:  { chip: "bg-rose-50    text-rose-700    ring-1 ring-rose-200/70",    Icon: AlertCircle,  pillBorder: "ring-rose-100",    pillBg: "bg-rose-50/40",    avatar: "from-rose-400 to-rose-600" },
};

const fmtM = (n: number) => `UGX ${(n / 1_000_000).toFixed(1)}M`;

// Receipt Confirmation Tracker.
//
// Surfaces every disbursement where money has been released but the
// staff member hasn't yet clicked "Confirm Received". A 3-up summary
// strip sits above the list so the accountant sees the awaiting /
// confirmed / disputed split before scanning individual rows.
export function ReceiptConfirmationTracker() {
  const awaiting = receiptTrackerRows.filter((r) => r.status === "Awaiting");
  const confirmed = receiptTrackerRows.filter((r) => r.status === "Confirmed");
  const disputed = receiptTrackerRows.filter((r) => r.status === "Disputed");
  const overdue = awaiting.filter((r) => r.hoursSince >= 24).length;
  const sum = (rows: ReceiptTrackerRow[]) =>
    rows.reduce((a, r) => a + r.amountUgx, 0);

  return (
    <article className="card p-5 lg:p-6 flex flex-col h-full overflow-hidden">
      <header className="flex items-start justify-between gap-2 mb-3 flex-wrap">
        <div className="min-w-0">
          <h3 className="text-[14.5px] font-extrabold tracking-tight text-slate-900">
            Receipt Confirmation Tracker
          </h3>
          <p className="text-caption text-slate-500 font-semibold mt-0.5">
            Disbursed funds awaiting staff acknowledgement
          </p>
        </div>
        {overdue > 0 && (
          <span className="inline-flex items-center gap-1 px-2 py-[3px] rounded-full text-[10px] font-extrabold bg-rose-50 text-rose-700 ring-1 ring-rose-200/70">
            <AlertCircle size={10} strokeWidth={2.4} />
            {overdue} overdue
          </span>
        )}
      </header>

      {/* Summary strip — awaiting / confirmed / disputed split */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        <SummaryStat
          label="Awaiting"
          amount={fmtM(sum(awaiting))}
          count={awaiting.length}
          tone="amber"
        />
        <SummaryStat
          label="Confirmed"
          amount={fmtM(sum(confirmed))}
          count={confirmed.length}
          tone="emerald"
        />
        <SummaryStat
          label="Disputed"
          amount={fmtM(sum(disputed))}
          count={disputed.length}
          tone="rose"
        />
      </div>

      <ul className="flex flex-col gap-2 flex-1">
        {receiptTrackerRows.map((row, i) => {
          const tone = STATUS_TONE[row.status];
          const isOverdue = row.status === "Awaiting" && row.hoursSince >= 24;
          const StatusIcon = tone.Icon;
          return (
            <li
              key={row.id}
              className={cn(
                "rounded-xl ring-1 p-2.5 flex items-center gap-2.5 transition-colors tile-in min-w-0",
                tone.pillBorder,
                tone.pillBg,
                `stagger-${(i % 8) + 1}`,
              )}
            >
              <span
                className={cn(
                  "w-9 h-9 rounded-full grid place-items-center text-[11px] font-extrabold text-white shrink-0 bg-gradient-to-br shadow-[0_4px_10px_-4px_rgba(15,23,32,0.35)]",
                  tone.avatar,
                )}
              >
                {row.initials}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[12px] font-extrabold text-slate-900 truncate">
                  {row.staff}{" "}
                  <span className="text-slate-400 font-semibold">({row.staffRole})</span>
                </div>
                <div className="text-[10px] text-slate-500 font-semibold truncate tabular">
                  {row.disbursementId} · disbursed {row.disbursedDate}
                </div>
                <div
                  className={cn(
                    "text-[10px] mt-0.5 inline-flex items-center gap-1 font-extrabold",
                    isOverdue
                      ? "text-rose-600"
                      : row.status === "Disputed"
                        ? "text-rose-600"
                        : row.status === "Confirmed"
                          ? "text-emerald-600"
                          : "text-slate-500",
                  )}
                >
                  <StatusIcon size={9} strokeWidth={2.6} />
                  {row.status === "Disputed"
                    ? "Receipt disputed — resolve before accountability"
                    : row.status === "Confirmed"
                      ? `Confirmed · ${row.hoursSince}h after disbursement`
                      : isOverdue
                        ? `Overdue · ${row.hoursSince}h since disbursement`
                        : `${row.hoursSince}h since disbursement`}
                </div>
              </div>
              <div className="text-right shrink-0">
                <div className="text-body font-extrabold tabular num-hero text-slate-900 leading-none">
                  {fmtM(row.amountUgx)}
                </div>
                <span
                  className={cn(
                    "inline-flex items-center px-2 py-[2px] mt-1 rounded-md text-[9.5px] font-extrabold whitespace-nowrap",
                    tone.chip,
                  )}
                >
                  {row.status === "Awaiting" ? "Awaiting receipt" : row.status}
                </span>
              </div>
              {row.status !== "Confirmed" && (
                <button
                  type="button"
                  title={
                    row.status === "Disputed"
                      ? "Open dispute resolution"
                      : "Send receipt reminder to staff"
                  }
                  aria-label={
                    row.status === "Disputed"
                      ? "Open dispute resolution"
                      : "Send receipt reminder"
                  }
                  className={cn(
                    "inline-flex items-center justify-center w-7 h-7 rounded-md ring-1 bg-white shrink-0 transition-colors",
                    row.status === "Disputed"
                      ? "ring-rose-200 hover:bg-rose-50 text-rose-600"
                      : "ring-amber-200 hover:bg-amber-50 text-amber-600",
                  )}
                >
                  <Bell size={11} strokeWidth={2.2} />
                </button>
              )}
            </li>
          );
        })}
      </ul>

      <a
        href="#receipts-all"
        className="mt-3 inline-flex items-center gap-1 text-[11.5px] font-extrabold text-sky-700 hover:text-sky-800"
      >
        View All unconfirmed receipts
        <ArrowUpRight size={11} />
      </a>
    </article>
  );
}

function SummaryStat({
  label,
  amount,
  count,
  tone,
}: {
  label: string;
  amount: string;
  count: number;
  tone: "amber" | "emerald" | "rose";
}) {
  const palette: Record<string, { bg: string; dot: string; text: string }> = {
    amber:   { bg: "bg-amber-50/70   ring-amber-100",   dot: "bg-amber-500",   text: "text-amber-700" },
    emerald: { bg: "bg-emerald-50/70 ring-emerald-100", dot: "bg-emerald-500", text: "text-emerald-700" },
    rose:    { bg: "bg-rose-50/70    ring-rose-100",    dot: "bg-rose-500",    text: "text-rose-700" },
  };
  const p = palette[tone];
  return (
    <div className={cn("rounded-xl ring-1 px-2.5 py-2", p.bg)}>
      <div className="flex items-center gap-1.5">
        <span className={cn("w-1.5 h-1.5 rounded-full", p.dot)} />
        <span className="text-[9px] font-extrabold uppercase tracking-[0.08em] text-slate-500">
          {label}
        </span>
      </div>
      <div className="text-body-lg font-extrabold tabular num-hero text-slate-900 leading-none mt-1.5">
        {amount}
      </div>
      <div className={cn("text-[9.5px] font-extrabold mt-1", p.text)}>
        {count} disbursement{count === 1 ? "" : "s"}
      </div>
    </div>
  );
}
