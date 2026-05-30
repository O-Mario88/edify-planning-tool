"use client";

import {
  CheckCircle2,
  FilePlus2,
  FileWarning,
  Send,
  ShieldOff,
  XCircle,
} from "lucide-react";
import { recentAuditEvents } from "@/lib/funds/weekly-fund-mock";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import { cn } from "@/lib/utils";
import type { WeeklyFundAuditAction } from "@/lib/funds/weekly-fund-types";

const ACTION_ICON: Record<WeeklyFundAuditAction, typeof Send> = {
  AUTO_GENERATED:            FilePlus2,
  OPENED:                    FilePlus2,
  EDITED:                    FilePlus2,
  ADJUSTMENT_ADDED:          FilePlus2,
  SUBMITTED:                 FilePlus2,
  APPROVED:                  CheckCircle2,
  RETURNED:                  XCircle,
  CANCELLED:                 XCircle,
  FUNDS_CONFIRMED_AT_COUNTRY:CheckCircle2,
  DISBURSED:                 Send,
  RECEIPT_CONFIRMED:         CheckCircle2,
  ACCOUNTABILITY_SUBMITTED:  FileWarning,
  ACCOUNTABILITY_APPROVED:   CheckCircle2,
  ACCOUNTABILITY_RETURNED:   FileWarning,
  CLOSED:                    CheckCircle2,
  BLOCKER_RAISED:            ShieldOff,
  BLOCKER_CLEARED:           CheckCircle2,
  OVERRIDE:                  ShieldOff,
};

const ACTION_TONE: Record<WeeklyFundAuditAction, string> = {
  AUTO_GENERATED:            "bg-slate-100   text-slate-700",
  OPENED:                    "bg-slate-100   text-slate-700",
  EDITED:                    "bg-slate-100   text-slate-700",
  ADJUSTMENT_ADDED:          "bg-violet-100  text-violet-700",
  SUBMITTED:                 "bg-sky-100     text-sky-700",
  APPROVED:                  "bg-emerald-100 text-emerald-700",
  RETURNED:                  "bg-rose-100    text-rose-700",
  CANCELLED:                 "bg-slate-200   text-slate-700",
  FUNDS_CONFIRMED_AT_COUNTRY:"bg-emerald-100 text-emerald-700",
  DISBURSED:                 "bg-emerald-100 text-emerald-700",
  RECEIPT_CONFIRMED:         "bg-sky-100     text-sky-700",
  ACCOUNTABILITY_SUBMITTED:  "bg-amber-100   text-amber-700",
  ACCOUNTABILITY_APPROVED:   "bg-emerald-100 text-emerald-700",
  ACCOUNTABILITY_RETURNED:   "bg-rose-100    text-rose-700",
  CLOSED:                    "bg-emerald-100 text-emerald-700",
  BLOCKER_RAISED:            "bg-rose-100    text-rose-700",
  BLOCKER_CLEARED:           "bg-emerald-100 text-emerald-700",
  OVERRIDE:                  "bg-amber-100   text-amber-700",
};

// Audit Trail Feed — every state transition (system + human).
// This is the legal record for finance audits.
export function AuditTrailFeed() {
  return (
    <article className="card p-3.5 flex flex-col">
      <header className="flex items-center justify-between gap-2 mb-2.5">
        <div className="min-w-0">
          <h3 className="text-[13px] font-extrabold tracking-tight">Audit Trail</h3>
          <p className="text-caption muted font-semibold leading-tight">
            Every state change · immutable record
          </p>
        </div>
      </header>

      <ul className="flex flex-col gap-2.5 max-h-[420px] overflow-y-auto pr-1">
        {recentAuditEvents.map((e, i) => {
          const Icon = ACTION_ICON[e.action];
          const tone = ACTION_TONE[e.action];
          const stagger = `stagger-${(i % 6) + 1}`;
          const when = new Date(e.at).toLocaleString("en-GB", {
            day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
          });
          return (
            <li
              key={e.id}
              className={cn(
                "flex items-start gap-2.5 tile-in",
                stagger,
              )}
            >
              <span className={cn("w-8 h-8 rounded-lg grid place-items-center shrink-0", tone)}>
                <Icon size={13} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-1.5 flex-wrap">
                  <span className="text-[11.5px] font-extrabold text-slate-900">
                    {e.actorName}
                  </span>
                  <span className="text-[10px] muted font-semibold">({e.actorRole})</span>
                  <span className="text-[10px] muted font-semibold ml-auto">{when}</span>
                </div>
                <div className="text-[11.5px] text-slate-700 leading-snug mt-0.5">
                  <span className="font-extrabold">{labelize(e.action)}</span>
                  {e.fromStatus && e.toStatus && (
                    <span className="muted font-semibold">
                      {" "}· {e.fromStatus} → {e.toStatus}
                    </span>
                  )}
                  {e.delta && (
                    <span className="font-extrabold tabular text-slate-900"> · {formatMoney(e.delta)}</span>
                  )}
                </div>
                {e.note && (
                  <div className="text-caption muted italic mt-0.5 truncate">
                    “{e.note}”
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </article>
  );
}

function labelize(action: WeeklyFundAuditAction): string {
  return action
    .toLowerCase()
    .split("_")
    .map((w) => w[0]!.toUpperCase() + w.slice(1))
    .join(" ");
}
