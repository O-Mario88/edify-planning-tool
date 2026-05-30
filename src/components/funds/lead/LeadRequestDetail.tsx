"use client";

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  GraduationCap,
  MessageSquare,
  RotateCcw,
  School,
  Users,
  UsersRound,
  Heart,
  XCircle,
} from "lucide-react";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import { StatusChip } from "@/components/funds/StatusChip";
import { cn } from "@/lib/utils";
import type { WeeklyFundRequest } from "@/lib/funds/weekly-fund-types";

const KIND_ICON = {
  SchoolVisit:        School,
  Cluster:            Users,
  TeacherTraining:    GraduationCap,
  FollowUp:           UsersRound,
  StakeholderMeeting: Heart,
  Other:              ClipboardCheck,
} as const;

const KIND_TONE = {
  SchoolVisit:        { bg: "bg-sky-100",     fg: "text-sky-700" },
  Cluster:            { bg: "bg-violet-100",  fg: "text-violet-700" },
  TeacherTraining:    { bg: "bg-rose-100",    fg: "text-rose-700" },
  FollowUp:           { bg: "bg-amber-100",   fg: "text-amber-700" },
  StakeholderMeeting: { bg: "bg-emerald-100", fg: "text-emerald-700" },
  Other:              { bg: "bg-slate-100",   fg: "text-slate-700" },
} as const;

// Right-side detail panel.
//
// Shows the selected request's activities with full cost breakdown
// (transport/allowance/meals/materials/misc), any staff adjustments,
// flags, and the Approve / Return action set.
export function LeadRequestDetail({ request }: { request: WeeklyFundRequest }) {
  const [returnNote, setReturnNote] = useState("");
  const [returning, setReturning] = useState(false);

  return (
    <article className="card p-4 flex flex-col">
      {/* Identity header */}
      <header className="flex items-start justify-between gap-3 flex-wrap pb-3 border-b border-[#eef2f4]">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          <span className="w-11 h-11 rounded-full grid place-items-center text-[13px] font-extrabold text-white shrink-0 bg-gradient-to-br from-[var(--color-edify-primary)] to-[#344f5f] shadow-sm">
            {request.staffName.split(" ").map((p) => p[0]).join("").slice(0, 2)}
          </span>
          <div className="min-w-0">
            <h2 className="text-[15px] font-extrabold tracking-tight text-slate-900 truncate">
              {request.staffName}
            </h2>
            <div className="text-[11px] muted mt-0.5 leading-tight">
              <span className="text-slate-700 font-semibold">{request.district}</span>
              {" · "}
              <span className="text-slate-700 font-semibold">Week {request.period.weekOfMonth}</span>
              {" · "}
              <span>{request.period.weekStartIso} → {request.period.weekEndIso}</span>
            </div>
            <div className="mt-1.5"><StatusChip status={request.status} /></div>
          </div>
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

      {/* Flag strip */}
      {request.flags.length > 0 && (
        <div className="mt-2.5 flex items-center gap-1.5 flex-wrap">
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

      {/* Activities */}
      <div className="mt-3">
        <div className="flex items-center justify-between mb-1.5">
          <h3 className="text-body font-extrabold tracking-tight">Activities — Week {request.period.weekOfMonth}</h3>
          <span className="text-caption muted font-semibold">
            {request.activities.length} from approved plan
          </span>
        </div>
        <ul className="flex flex-col gap-1.5">
          {request.activities.map((a, i) => {
            const Icon = KIND_ICON[a.kind];
            const tone = KIND_TONE[a.kind];
            const stagger = `stagger-${(i % 6) + 1}`;
            return (
              <li
                key={a.id}
                className={cn(
                  "rounded-xl border border-[var(--color-edify-border)] bg-white p-2.5 tile-in card-lift",
                  stagger,
                )}
              >
                <div className="flex items-center gap-2.5">
                  <span className={cn("w-8 h-8 rounded-lg grid place-items-center shrink-0", tone.bg)}>
                    <Icon size={13} className={tone.fg} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-[12px] font-extrabold text-slate-900 truncate">
                      {a.title}
                    </div>
                    <div className="text-[10px] muted font-semibold truncate">
                      {a.plannedDay} · {a.district}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-body font-extrabold tabular num-hero text-slate-900 leading-none">
                      {formatMoney(a.totalCost)}
                    </div>
                    <div className="text-[9.5px] muted font-semibold mt-0.5">{a.status}</div>
                  </div>
                </div>
                {/* Cost breakdown chips */}
                <div className="mt-1.5 flex items-center gap-1 flex-wrap">
                  {[
                    { k: "Transport",  v: a.costBreakdown.transport },
                    { k: "Allowance",  v: a.costBreakdown.allowance },
                    { k: "Meals",      v: a.costBreakdown.meals },
                    { k: "Materials",  v: a.costBreakdown.materials },
                    { k: "Misc",       v: a.costBreakdown.misc },
                  ].map(({ k, v }) => v.amount > 0 && (
                    <span
                      key={k}
                      className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[9.5px] font-semibold bg-slate-50 text-slate-700 border border-slate-200"
                    >
                      {k} <span className="font-extrabold tabular">{formatMoney(v)}</span>
                    </span>
                  ))}
                </div>
              </li>
            );
          })}
        </ul>
      </div>

      {/* Adjustments */}
      {request.adjustments.length > 0 && (
        <div className="mt-3 rounded-xl border border-violet-200 bg-violet-50/50 p-2.5">
          <div className="flex items-center gap-1.5 mb-1.5">
            <RotateCcw size={12} className="text-violet-700" />
            <span className="text-[11.5px] font-extrabold text-violet-800">
              Staff adjustments — {request.adjustments.length}
            </span>
          </div>
          <ul className="flex flex-col gap-1">
            {request.adjustments.map((a) => (
              <li key={a.activityId} className="text-[11px] text-slate-700">
                <span className="font-extrabold">{labelize(a.type)}</span>
                {a.costDelta && <> · <span className="tabular">{formatMoney(a.costDelta)}</span></>}
                <span className="muted"> — {a.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Lead notes */}
      {request.notes && (
        <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50/50 p-2.5">
          <div className="flex items-center gap-1.5 mb-1">
            <MessageSquare size={11} className="text-amber-700" />
            <span className="text-[11px] font-extrabold text-amber-800">
              Note on this request
            </span>
          </div>
          <p className="text-[11px] text-slate-700 italic">“{request.notes}”</p>
        </div>
      )}

      {/* Action bar */}
      <footer className="mt-4 pt-3 border-t border-[#eef2f4]">
        {returning ? (
          <div className="flex flex-col gap-2">
            <label className="text-[11px] font-extrabold text-slate-700">
              Return reason <span className="text-rose-600">*</span>
            </label>
            <textarea
              value={returnNote}
              onChange={(e) => setReturnNote(e.target.value)}
              placeholder="Explain what needs fixing (min 5 chars)…"
              className="w-full min-h-[72px] rounded-lg border border-[var(--color-edify-border)] bg-white px-2.5 py-2 text-[12px] text-slate-700 outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => { setReturning(false); setReturnNote(""); }}
                className="h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-[12px] font-semibold text-slate-700"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={returnNote.trim().length < 5}
                className={cn(
                  "inline-flex items-center gap-1.5 h-9 px-3 rounded-lg text-[12px] font-extrabold",
                  returnNote.trim().length >= 5
                    ? "bg-rose-600 hover:bg-rose-700 text-white shadow-[0_10px_28px_-12px_rgba(225,29,72,0.5)]"
                    : "bg-slate-100 text-slate-400 cursor-not-allowed",
                )}
              >
                <XCircle size={12} />
                Return to staff
              </button>
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-end gap-2 flex-wrap">
            <button
              type="button"
              className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-[12px] font-semibold text-slate-700"
            >
              <MessageSquare size={12} />
              Message staff
            </button>
            <button
              type="button"
              onClick={() => setReturning(true)}
              className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg border border-rose-200 bg-rose-50 hover:bg-rose-100 text-[12px] font-extrabold text-rose-700"
            >
              <XCircle size={12} />
              Return
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-[12px] font-extrabold shadow-[0_10px_28px_-12px_rgba(15,23,32,0.45)]"
            >
              <CheckCircle2 size={12} />
              Approve & release to Accountant
            </button>
          </div>
        )}
      </footer>
    </article>
  );
}

function labelize(s: string): string {
  return s.toLowerCase().split("_").map((w) => w[0]?.toUpperCase() + w.slice(1)).join(" ");
}
