"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Banknote,
  Briefcase,
  CheckCircle2,
  Eye,
  Sparkles,
  Shield,
  GraduationCap,
  Hammer,
  Send,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import {
  pendingCountryBudgets,
  ugandaCountryBudget,
} from "@/lib/funds/weekly-fund-mock";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import type {
  CountryBudgetCategory,
  CountryMonthlyBudget,
} from "@/lib/funds/weekly-fund-types";
import { cn } from "@/lib/utils";

const CAT_ICON: Record<CountryBudgetCategory, LucideIcon> = {
  FieldWork:       Send,
  AdminOps:        Briefcase,
  SpecialProjects: Sparkles,
  Contingency:     Shield,
  Training:        GraduationCap,
  PartnerWork:     Hammer,
};

const CAT_TONE: Record<CountryBudgetCategory, { bg: string; fg: string }> = {
  FieldWork:       { bg: "bg-sky-100",     fg: "text-sky-700" },
  AdminOps:        { bg: "bg-slate-100",   fg: "text-slate-700" },
  SpecialProjects: { bg: "bg-amber-100",   fg: "text-amber-700" },
  Contingency:     { bg: "bg-rose-100",    fg: "text-rose-700" },
  Training:        { bg: "bg-violet-100",  fg: "text-violet-700" },
  PartnerWork:     { bg: "bg-emerald-100", fg: "text-emerald-700" },
};

// RVP Country Monthly Budget approval card.
//
// RVP approves only the country MONTHLY BUDGET ENVELOPE — not
// individual weekly fund requests. Once approved, weekly fund-request
// auto-generation becomes active for the month.
//
// Layout:
//   • Top — Uganda's already-approved May 2026 envelope (reference)
//   • Bottom — pending June 2026 envelopes from KE + TZ requiring RVP
//     review (Approve / Approve with conditions / Return)
export function RvpCountryBudgetCard() {
  return (
    <article className="card p-3.5 flex flex-col">
      <header className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <div className="min-w-0">
          <h3 className="text-[13px] font-extrabold tracking-tight">
            Country Monthly Budget — RVP Approval
          </h3>
          <p className="text-caption muted font-semibold leading-tight">
            Approve the monthly envelope · weekly fund auto-generation activates afterward
          </p>
        </div>
        <span className="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[10px] font-extrabold bg-emerald-100 text-emerald-700 border border-emerald-200">
          <Shield size={10} />
          Envelope approval only — not weekly requests
        </span>
      </header>

      {/* Approved (Uganda) */}
      <BudgetCard budget={ugandaCountryBudget} mode="approved" />

      {/* Pending — KE + TZ */}
      <div className="mt-3 space-y-3">
        {pendingCountryBudgets.map((b, i) => (
          <BudgetCard
            key={b.id}
            budget={b}
            mode="pending"
            stagger={`stagger-${i + 1}`}
          />
        ))}
      </div>
    </article>
  );
}

function BudgetCard({
  budget,
  mode,
  stagger,
}: {
  budget: CountryMonthlyBudget;
  mode: "approved" | "pending";
  stagger?: string;
}) {
  const [returning, setReturning] = useState(false);
  const [reason, setReason] = useState("");
  const [withConditions, setWithConditions] = useState(false);

  return (
    <section
      className={cn(
        "rounded-xl border bg-white p-3 tile-in card-lift",
        mode === "approved"
          ? "border-emerald-200 bg-emerald-50/30"
          : "border-[var(--color-edify-border)]",
        stagger,
      )}
    >
      <header className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="text-[24px] leading-none">{budget.flag}</span>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[13px] font-extrabold text-slate-900">
                {budget.countryName} — {budget.monthLabel}
              </span>
              {mode === "approved" ? (
                <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold bg-emerald-100 text-emerald-700 border border-emerald-200">
                  <CheckCircle2 size={9} />
                  Approved · auto-generation active
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold bg-amber-100 text-amber-700 border border-amber-200">
                  Pending RVP
                </span>
              )}
            </div>
            <div className="text-caption muted font-semibold mt-0.5">
              Submitted by <span className="text-slate-700">{budget.submittedByCdName}</span>
              {budget.submittedAt && <> · {budget.submittedAt.slice(0, 10)}</>}
            </div>
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[16px] font-extrabold tabular num-hero text-slate-900 leading-none glow-emerald">
            {formatMoney(budget.total)}
          </div>
          <div className="text-[10px] muted font-semibold mt-0.5">total envelope</div>
        </div>
      </header>

      {/* Lines */}
      <ul className="mt-2.5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-1.5">
        {budget.lines.map((l) => {
          const Icon = CAT_ICON[l.category];
          const tone = CAT_TONE[l.category];
          const pct = (l.amount.amount / budget.total.amount) * 100;
          return (
            <li
              key={l.category}
              className="rounded-lg border border-[var(--color-edify-border)] bg-white p-2 flex items-start gap-2"
            >
              <span className={cn("w-7 h-7 rounded-lg grid place-items-center shrink-0", tone.bg)}>
                <Icon size={12} className={tone.fg} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-caption muted font-bold uppercase tracking-wide leading-tight truncate">{l.label}</div>
                <div className="flex items-baseline gap-1 mt-0.5">
                  <span className="text-[13px] font-extrabold tabular num-hero text-slate-900 leading-none">
                    {formatMoney(l.amount)}
                  </span>
                  <span className="text-[9.5px] muted font-semibold tabular">{pct.toFixed(0)}%</span>
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      {/* Approved meta */}
      {mode === "approved" && budget.approvedByRvpName && (
        <div className="mt-2 pt-2 border-t border-dashed border-[#eef2f4] flex items-center justify-between gap-2 flex-wrap text-caption">
          <span className="muted font-semibold">
            <CheckCircle2 size={11} className="inline text-emerald-600 mr-1" />
            Approved by <span className="text-slate-700 font-extrabold">{budget.approvedByRvpName}</span>
            {budget.approvedAt && <> · {budget.approvedAt.slice(0, 10)}</>}
          </span>
          <Link
            href="/budget/breakdown"
            className="inline-flex items-center gap-1 font-extrabold text-[var(--color-edify-primary)] hover:underline"
          >
            <Eye size={10} />
            View envelope
          </Link>
        </div>
      )}

      {/* Pending actions */}
      {mode === "pending" && (
        <footer className="mt-2 pt-2 border-t border-dashed border-[#eef2f4]">
          {returning ? (
            <div className="flex flex-col gap-2">
              <label className="text-caption font-extrabold text-slate-700">
                Return reason <span className="text-rose-600">*</span>
              </label>
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Why is the envelope being returned to the CD…"
                className="w-full min-h-[56px] rounded-lg border border-[var(--color-edify-border)] bg-white px-2.5 py-2 text-[11.5px] text-slate-700 outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
              />
              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => { setReturning(false); setReason(""); }}
                  className="h-8 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-[11.5px] font-semibold text-slate-700"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={reason.trim().length < 5}
                  className={cn(
                    "h-8 px-3 rounded-lg text-[11.5px] font-extrabold inline-flex items-center gap-1",
                    reason.trim().length >= 5
                      ? "bg-rose-600 hover:bg-rose-700 text-white"
                      : "bg-slate-100 text-slate-400 cursor-not-allowed",
                  )}
                >
                  <XCircle size={11} />
                  Return envelope
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <label className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-slate-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={withConditions}
                  onChange={(e) => setWithConditions(e.target.checked)}
                />
                Approve with conditions
              </label>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  className="h-8 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-[11.5px] font-semibold text-slate-700 inline-flex items-center gap-1"
                >
                  <Eye size={11} />
                  Review
                </button>
                <button
                  type="button"
                  onClick={() => setReturning(true)}
                  className="h-8 px-3 rounded-lg border border-rose-200 bg-rose-50 hover:bg-rose-100 text-[11.5px] font-extrabold text-rose-700 inline-flex items-center gap-1"
                >
                  <XCircle size={11} />
                  Return
                </button>
                <button
                  type="button"
                  className="h-8 px-3 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-[11.5px] font-extrabold inline-flex items-center gap-1 shadow-[0_10px_28px_-12px_rgba(15,23,32,0.45)]"
                >
                  <CheckCircle2 size={11} />
                  {withConditions ? "Approve with conditions" : "Approve envelope"}
                </button>
              </div>
            </div>
          )}
        </footer>
      )}

      {/* Unused for clean import */}
      <span className="hidden">
        <Banknote />
      </span>
    </section>
  );
}
