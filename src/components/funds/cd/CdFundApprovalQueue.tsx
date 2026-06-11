"use client";

import { useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  Banknote,
  Briefcase,
  CheckCircle2,
  Eye,
  GraduationCap,
  Shield,
  Sparkles,
  Users,
  type LucideIcon,
  XCircle,
} from "lucide-react";
import { cdFundRequests as cdFundRequestsSeed } from "@/lib/funds/weekly-fund-mock";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import { REQUESTER_LABEL, RISK_LABEL } from "@/lib/funds/weekly-fund-types";
import type {
  RequesterRole,
  WeeklyFundRequest,
} from "@/lib/funds/weekly-fund-types";
import { StatusChip } from "@/components/funds/StatusChip";
import { cn } from "@/lib/utils";

const ROLE_ICON: Record<Exclude<RequesterRole, "CCEO">, LucideIcon> = {
  ProgramLead:                Users,
  ProgramAccountant:          Banknote,
  ImpactAssessment:           GraduationCap,
  SpecialProjectsCoordinator: Sparkles,
  Admin:                      Briefcase,
};

const ROLE_TONE: Record<Exclude<RequesterRole, "CCEO">, { bg: string; fg: string; border: string }> = {
  ProgramLead:                { bg: "bg-sky-50",     fg: "text-sky-700",     border: "border-sky-200" },
  ProgramAccountant:          { bg: "bg-emerald-50", fg: "text-emerald-700", border: "border-emerald-200" },
  ImpactAssessment:           { bg: "bg-violet-50",  fg: "text-violet-700",  border: "border-violet-200" },
  SpecialProjectsCoordinator: { bg: "bg-amber-50",   fg: "text-amber-700",   border: "border-amber-200" },
  Admin:                      { bg: "bg-slate-50",   fg: "text-slate-700",   border: "border-slate-200" },
};

// Country Director Fund Approval Queue.
//
// The CD does NOT approve CCEO weekly requests — those go through the
// Program Lead. The CD only approves requests from higher-tier
// requesters: PL supervision funds, IA verification funds, Accountant
// ops funds, Special Projects funds, Admin/operations funds.
//
// Requests are grouped by requester type so the CD can scan the
// inbox by category at a glance.
// `requests` comes from the live fundRequestsStore (passed by the
// /approvals page via liveCdFundRequests()). Falls back to the demo
// seed only when a caller renders the queue without props.
export function CdFundApprovalQueue({ requests }: { requests?: WeeklyFundRequest[] } = {}) {
  const cdFundRequests = requests ?? cdFundRequestsSeed;
  const [selectedId, setSelectedId] = useState<string | undefined>(() =>
    cdFundRequests.find((r) => r.status === "SUBMITTED")?.id,
  );

  const allGroups: { role: Exclude<RequesterRole, "CCEO">; rows: WeeklyFundRequest[] }[] = [
    { role: "ProgramLead",                rows: cdFundRequests.filter((r) => r.requesterRole === "ProgramLead") },
    { role: "ImpactAssessment",           rows: cdFundRequests.filter((r) => r.requesterRole === "ImpactAssessment") },
    { role: "ProgramAccountant",          rows: cdFundRequests.filter((r) => r.requesterRole === "ProgramAccountant") },
    { role: "SpecialProjectsCoordinator", rows: cdFundRequests.filter((r) => r.requesterRole === "SpecialProjectsCoordinator") },
    { role: "Admin",                      rows: cdFundRequests.filter((r) => r.requesterRole === "Admin") },
  ];
  const groups = allGroups.filter((g) => g.rows.length > 0);

  const pendingCount = cdFundRequests.filter((r) => r.status === "SUBMITTED").length;
  const approvedCount = cdFundRequests.filter((r) => r.status === "APPROVED").length;

  return (
    <article className="card p-3.5 flex flex-col">
      <header className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <div className="min-w-0">
          <h3 className="text-[13px] font-extrabold tracking-tight">
            Country Director Fund Approval Queue
          </h3>
          <p className="text-caption muted font-semibold leading-tight">
            {pendingCount} pending · {approvedCount} approved — auto-routed from PL / IA / Accountant / SP / Admin plans
          </p>
        </div>
        <span className="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[10px] font-extrabold bg-emerald-100 text-emerald-700 border border-emerald-200">
          <Shield size={10} />
          CCEO requests handled by Program Leads
        </span>
      </header>

      <div className="flex flex-col gap-3">
        {groups.map((g) => {
          const Icon = ROLE_ICON[g.role];
          const tone = ROLE_TONE[g.role];
          return (
            <section key={g.role} className={cn("rounded-xl border p-2.5", tone.border, tone.bg)}>
              <header className="flex items-center justify-between gap-2 mb-2">
                <div className="flex items-center gap-2">
                  <span className={cn("w-7 h-7 rounded-lg grid place-items-center", tone.bg.replace("-50", "-100"))}>
                    <Icon size={13} className={tone.fg} />
                  </span>
                  <div className="min-w-0">
                    <div className="text-[12px] font-extrabold text-slate-900">
                      {REQUESTER_LABEL[g.role]} Requests
                    </div>
                    <div className="text-[10px] muted font-semibold">
                      {g.rows.length} item{g.rows.length === 1 ? "" : "s"} this week
                    </div>
                  </div>
                </div>
                <span className="text-caption font-extrabold tabular text-slate-700">
                  {formatMoney({
                    amount: g.rows.reduce((a, r) => a + r.requestedAmount.amount, 0),
                    currency: "UGX",
                  })}
                </span>
              </header>

              <ul className="flex flex-col gap-1.5">
                {g.rows.map((r, i) => {
                  const stagger = `stagger-${(i % 6) + 1}`;
                  const isPending = r.status === "SUBMITTED";
                  const selected = selectedId === r.id;
                  const linkedPlan = r.weeklyPlanId ? `Linked to ${r.weeklyPlanId}` : "";
                  return (
                    <li key={r.id}>
                      <div
                        role="button"
                        tabIndex={0}
                        onClick={() => setSelectedId(r.id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            setSelectedId(r.id);
                          }
                        }}
                        className={cn(
                          "w-full text-left rounded-xl bg-white p-2.5 tile-in card-lift border transition-colors cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-edify-primary)]/30",
                          selected
                            ? "border-[var(--color-edify-primary)] ring-2 ring-[var(--color-edify-primary)]/15"
                            : "border-[var(--color-edify-border)] hover:border-slate-300",
                          stagger,
                        )}
                      >
                        <div className="flex items-start gap-2.5 flex-wrap">
                          <span className="w-8 h-8 rounded-full grid place-items-center text-caption font-extrabold text-white shrink-0 bg-gradient-to-br from-[var(--color-edify-primary)] to-[#344f5f]">
                            {r.staffName.split(" ").map((p) => p[0]).join("").slice(0, 2)}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="text-[12px] font-extrabold text-slate-900 truncate">
                              {r.staffName}
                              <span className="text-slate-400 font-medium"> — </span>
                              <span className="text-slate-600 font-semibold">{r.district}</span>
                            </div>
                            <div className="text-[10px] muted font-semibold truncate mt-0.5">
                              Week {r.period.weekOfMonth} · {r.activities.length} activity line{r.activities.length === 1 ? "" : "s"}
                              {linkedPlan && <> · {linkedPlan}</>}
                            </div>
                          </div>
                          <div className="text-right shrink-0">
                            <div className="text-[13px] font-extrabold tabular num-hero text-slate-900 leading-none">
                              {formatMoney(r.requestedAmount)}
                            </div>
                            <div className="text-[9.5px] muted font-semibold mt-0.5">requested</div>
                          </div>
                        </div>
                        <div className="mt-1.5 flex items-center justify-between gap-2 flex-wrap">
                          <StatusChip status={r.status} size="xs" />
                          <div className="flex items-center gap-1">
                            {(r.risks ?? []).slice(0, 2).map((rk) => (
                              <span
                                key={rk}
                                className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold bg-amber-100 text-amber-700 border border-amber-200"
                              >
                                <AlertTriangle size={9} />
                                {RISK_LABEL[rk]}
                              </span>
                            ))}
                            {r.adjustments.length > 0 && (
                              <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold bg-violet-100 text-violet-700 border border-violet-200">
                                {r.adjustments.length} adj.
                              </span>
                            )}
                            {isPending && (
                              <div className="flex items-center gap-1 ml-1">
                                <button
                                  type="button"
                                  onClick={(e) => e.stopPropagation()}
                                  className="inline-flex items-center gap-1 h-7 px-2 rounded-md border border-rose-200 bg-rose-50 hover:bg-rose-100 text-caption font-extrabold text-rose-700"
                                >
                                  <XCircle size={10} />
                                  Return
                                </button>
                                <button
                                  type="button"
                                  onClick={(e) => e.stopPropagation()}
                                  className="inline-flex items-center gap-1 h-7 px-2 rounded-md bg-slate-900 hover:bg-slate-800 text-white text-caption font-extrabold"
                                >
                                  <CheckCircle2 size={10} />
                                  Approve
                                </button>
                              </div>
                            )}
                            {!isPending && (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setSelectedId(r.id);
                                }}
                                className="inline-flex items-center gap-1 text-caption font-extrabold text-[var(--color-edify-primary)]"
                              >
                                <Eye size={10} />
                                View
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}
      </div>

      <footer className="mt-3 pt-2.5 border-t border-dashed border-[#eef2f4] flex items-center justify-between gap-2 text-caption muted font-semibold">
        <span className="inline-flex items-center gap-1">
          <CheckCircle2 size={11} className="text-emerald-600" />
          Auto-routed: only PL / IA / Accountant / SP / Admin requests reach this queue.
        </span>
        <a
          href="#cd-history"
          className="inline-flex items-center gap-1 text-[var(--color-edify-primary)] font-extrabold"
        >
          History
          <ArrowUpRight size={10} />
        </a>
      </footer>
    </article>
  );
}
