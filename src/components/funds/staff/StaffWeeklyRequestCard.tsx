"use client";

import {
  AlertTriangle,
  Banknote,
  CalendarCheck,
  CheckCircle2,
  Clock,
  FileSignature,
  Hourglass,
  School,
  Send,
} from "lucide-react";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import { StatusChip } from "@/components/funds/StatusChip";
import { cn } from "@/lib/utils";
import type {
  WeeklyFundRequest,
  WeeklyFundRequestStatus,
} from "@/lib/funds/weekly-fund-types";

// One-card view of a single weekly request, with a status-driven
// primary action and a full money trail (planned → requested →
// disbursed → accounted → returned).
export function StaffWeeklyRequestCard({
  request,
}: {
  request: WeeklyFundRequest;
}) {
  const primary = primaryAction(request.status);

  return (
    <article className="card p-4 flex flex-col gap-3">
      {/* Header */}
      <header className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <h2 className="text-[15px] font-extrabold tracking-tight text-slate-900">
            Week {request.period.weekOfMonth} fund request
          </h2>
          <div className="text-[11px] muted mt-0.5 leading-tight">
            {request.period.weekStartIso} → {request.period.weekEndIso}
            {" · "}
            <span className="text-slate-700 font-semibold">{request.activities.length} activities</span>
          </div>
          <div className="mt-1.5"><StatusChip status={request.status} /></div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[18px] font-extrabold tabular num-hero text-slate-900 leading-none glow-emerald">
            {formatMoney(request.requestedAmount)}
          </div>
          <div className="text-caption muted font-semibold mt-1">
            requested · planned {formatMoney(request.plannedAmount)}
          </div>
        </div>
      </header>

      {/* Pipeline stepper */}
      <PipelineStepper status={request.status} />

      {/* Flags */}
      {request.flags.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          {request.flags.map((f) => (
            <span
              key={f}
              className="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[10px] font-extrabold bg-rose-100 text-rose-700 border border-rose-200"
            >
              <AlertTriangle size={10} />
              {labelize(f)}
            </span>
          ))}
        </div>
      )}

      {/* Money trail */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
        <MoneyTile label="Planned"      value={formatMoney(request.plannedAmount)}      tone="slate" />
        <MoneyTile label="Requested"    value={formatMoney(request.requestedAmount)}    tone="sky" />
        <MoneyTile label="Disbursed"    value={request.disbursedAmount ? formatMoney(request.disbursedAmount) : "—"}    tone="emerald" />
        <MoneyTile label="Accounted"    value={request.accountedAmount ? formatMoney(request.accountedAmount) : "—"}    tone="violet" />
        <MoneyTile label="Returned"     value={request.returnedAmount ? formatMoney(request.returnedAmount) : "—"}    tone="amber" />
      </div>

      {/* Activities */}
      <section>
        <h3 className="text-body font-extrabold tracking-tight mb-1.5">
          Activities (from your approved plan)
        </h3>
        <ul className="flex flex-col gap-1.5">
          {request.activities.map((a, i) => {
            const stagger = `stagger-${(i % 6) + 1}`;
            return (
              <li
                key={a.id}
                className={cn(
                  "rounded-xl border border-[var(--color-edify-border)] bg-white p-2.5 flex items-center gap-2.5 tile-in card-lift",
                  stagger,
                )}
              >
                <span className="w-7 h-7 rounded-lg grid place-items-center shrink-0 bg-sky-100">
                  <School size={12} className="text-sky-700" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[12px] font-extrabold text-slate-900 truncate">{a.title}</div>
                  <div className="text-[10px] muted font-semibold truncate">
                    {a.plannedDay} · {a.district}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[12px] font-extrabold tabular num-hero text-slate-900 leading-none">
                    {formatMoney(a.totalCost)}
                  </div>
                  <div className="text-[9.5px] muted font-semibold mt-0.5">{a.status}</div>
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      {/* Lead note (e.g. return reason) */}
      {request.notes && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-2.5">
          <div className="text-caption font-extrabold text-amber-800 mb-0.5">
            Note from your Program Lead
          </div>
          <p className="text-[11.5px] text-slate-700 italic leading-snug">“{request.notes}”</p>
        </div>
      )}

      {/* Status-driven action bar */}
      <footer className="pt-2 border-t border-[#eef2f4] flex items-center justify-between gap-2 flex-wrap">
        <div className="text-caption muted font-semibold inline-flex items-center gap-1">
          <CheckCircle2 size={11} className="text-emerald-600" />
          Auto-locked: only activities from your approved plan can appear here.
        </div>
        <div className="flex items-center gap-2">
          {primary && (
            <button
              type="button"
              className={cn(
                "inline-flex items-center gap-1.5 h-9 px-3.5 rounded-lg text-[12px] font-extrabold transition-colors",
                primary.tone === "primary"
                  ? "bg-slate-900 hover:bg-slate-800 text-white shadow-[0_10px_28px_-12px_rgba(15,23,32,0.45)]"
                  : "border border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-slate-700",
              )}
            >
              <primary.Icon size={12} />
              {primary.label}
            </button>
          )}
        </div>
      </footer>
    </article>
  );
}

// ────────── Helpers ──────────

const TONE_BG: Record<string, string> = {
  slate:   "bg-slate-50",
  sky:     "bg-sky-50",
  emerald: "bg-emerald-50",
  violet:  "bg-violet-50",
  amber:   "bg-amber-50",
};

function MoneyTile({
  label, value, tone,
}: { label: string; value: string; tone: keyof typeof TONE_BG }) {
  return (
    <div className={cn("rounded-xl border border-[var(--color-edify-border)] p-2.5", TONE_BG[tone])}>
      <div className="text-[9.5px] muted font-bold uppercase tracking-wide">{label}</div>
      <div className="text-body-lg font-extrabold tabular num-hero leading-none mt-1">{value}</div>
    </div>
  );
}

type Step = {
  key: string;
  label: string;
  Icon: typeof CheckCircle2;
};

const STEPS: Step[] = [
  { key: "create",         label: "Auto-generated",   Icon: FileSignature },
  { key: "submit",         label: "Confirmed",        Icon: Send },
  { key: "lead",           label: "Approved",         Icon: CheckCircle2 },
  { key: "disburse",       label: "Disbursed",        Icon: Banknote },
  { key: "receive",        label: "Received",         Icon: CalendarCheck },
  { key: "accountability", label: "Accounted",        Icon: Hourglass },
  { key: "closed",         label: "Closed",           Icon: CheckCircle2 },
];

// Maps a status to "how far along the pipeline we are" (0..6).
function statusIndex(s: WeeklyFundRequestStatus): number {
  switch (s) {
    case "AUTO_GENERATED":
    case "DRAFT":
    case "RETURNED_TO_STAFF":
      return 0;
    case "SUBMITTED":
      return 1;
    case "APPROVED":
    case "HOLD_NO_FUNDS_AVAILABLE":
    case "BLOCKED_PRIOR_OUTSTANDING":
    case "READY_TO_DISBURSE":
      return 2;
    case "DISBURSED":
      return 3;
    case "RECEIVED":
    case "IN_USE":
      return 4;
    case "ACCOUNTABILITY_SUBMITTED":
    case "ACCOUNTABILITY_RETURNED":
      return 5;
    case "ACCOUNTABILITY_APPROVED":
    case "CLOSED":
    case "ARCHIVED":
      return 6;
    case "CANCELLED":
      return -1;
  }
}

function PipelineStepper({ status }: { status: WeeklyFundRequestStatus }) {
  const idx = statusIndex(status);
  return (
    <div className="flex items-center gap-0 overflow-x-auto -mx-1 px-1 pb-1">
      {STEPS.map((s, i) => {
        const reached = idx >= i;
        const current = idx === i;
        const Icon = s.Icon;
        return (
          <div key={s.key} className="flex items-center gap-0 shrink-0">
            <div className={cn(
              "flex items-center gap-1.5 px-2 py-1 rounded-lg",
              current
                ? "bg-emerald-100 text-emerald-700"
                : reached
                  ? "text-emerald-700"
                  : "text-slate-400",
            )}>
              <span className={cn(
                "w-5 h-5 rounded-full grid place-items-center text-[10px] font-extrabold shrink-0",
                reached ? "bg-emerald-500 text-white" : "bg-slate-200 text-slate-500",
              )}>
                <Icon size={10} />
              </span>
              <span className="text-caption font-extrabold whitespace-nowrap">{s.label}</span>
            </div>
            {i < STEPS.length - 1 && (
              <span className={cn(
                "w-3 h-[2px] mx-0.5 shrink-0",
                idx > i ? "bg-emerald-500" : "bg-slate-200",
              )} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function primaryAction(status: WeeklyFundRequestStatus): {
  label: string;
  Icon: typeof CheckCircle2;
  tone: "primary" | "secondary";
} | null {
  switch (status) {
    case "AUTO_GENERATED":
    case "DRAFT":
      return { label: "Review & confirm", Icon: Send, tone: "primary" };
    case "RETURNED_TO_STAFF":
      return { label: "Fix & resubmit", Icon: Send, tone: "primary" };
    case "DISBURSED":
      return { label: "Confirm receipt", Icon: CheckCircle2, tone: "primary" };
    case "RECEIVED":
    case "IN_USE":
      return { label: "Submit accountability", Icon: FileSignature, tone: "primary" };
    case "ACCOUNTABILITY_RETURNED":
      return { label: "Update receipts", Icon: FileSignature, tone: "primary" };
    case "SUBMITTED":
      return { label: "Waiting on Lead", Icon: Clock, tone: "secondary" };
    case "APPROVED":
    case "READY_TO_DISBURSE":
    case "HOLD_NO_FUNDS_AVAILABLE":
    case "BLOCKED_PRIOR_OUTSTANDING":
      return { label: "Waiting on Accountant", Icon: Hourglass, tone: "secondary" };
    case "ACCOUNTABILITY_SUBMITTED":
      return { label: "Waiting on Lead", Icon: Hourglass, tone: "secondary" };
    case "CLOSED":
    case "ACCOUNTABILITY_APPROVED":
    case "ARCHIVED":
      return { label: "Closed", Icon: CheckCircle2, tone: "secondary" };
    case "CANCELLED":
      return { label: "Cancelled", Icon: AlertTriangle, tone: "secondary" };
  }
}

function labelize(s: string): string {
  return s.toLowerCase().split("_").map((w) => w[0]?.toUpperCase() + w.slice(1)).join(" ");
}
