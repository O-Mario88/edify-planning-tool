"use client";

import { useState } from "react";
import Link from "next/link";
import {
  AlertOctagon,
  ArrowUpRight,
  Award,
  Building2,
  Calendar,
  CheckCircle2,
  ChevronRight,
  Footprints,
  GraduationCap,
  MapPin,
  Sparkles,
  TrendingUp,
  Trophy,
  UserCircle,
} from "lucide-react";
import {
  replicaAttention,
  replicaBestPerforming,
  type ReplicaAttentionRow,
} from "@/lib/core-school-replica-mock";
import { cn } from "@/lib/utils";

// Best Performing + Needing More Attention side by side. Both tables
// used to keep a dual mobile-cards + desktop-11-column layout. They've
// been unified into a single accordion list per card so the row reads
// the same on every breakpoint and every drilldown happens INLINE —
// the user never has to leave the dashboard to see "what's going on
// with this school?".
export function ReplicaTablesRow() {
  return (
    <section className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch">
      <div className="col-span-12 lg:col-span-7">
        <BestPerformingTable />
      </div>
      <div className="col-span-12 lg:col-span-5">
        <NeedingAttentionTable />
      </div>
    </section>
  );
}

// ───────────── Best Performing Core Schools ─────────────

function BestPerformingTable() {
  const [openRank, setOpenRank] = useState<number | null>(null);

  return (
    <article className="card p-3.5 h-full flex flex-col">
      <header className="flex items-center justify-between gap-2 mb-2">
        <h3 className="text-body-lg font-extrabold tracking-tight">Best Performing Core Schools</h3>
        <Link
          href="/core-schools"
          className="text-[11.5px] font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-0.5 whitespace-nowrap"
        >
          View All <ArrowUpRight size={11} />
        </Link>
      </header>

      <ul className="flex flex-col gap-2">
        {replicaBestPerforming.map((r) => {
          const open = openRank === r.rank;
          return (
            <li
              key={r.rank}
              className={cn(
                "rounded-xl border bg-white overflow-hidden transition-colors",
                open
                  ? "row-active-glow border-transparent bg-[var(--color-edify-soft)]/30"
                  : "border-[var(--color-edify-border)]",
              )}
            >
              <button
                type="button"
                onClick={() => setOpenRank(open ? null : r.rank)}
                aria-expanded={open}
                aria-controls={`best-${r.rank}-detail`}
                className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-[var(--color-edify-soft)]/40 transition-colors"
              >
                <span className="w-7 h-7 rounded-full bg-gradient-to-br from-emerald-400 to-emerald-600 text-white text-[12px] font-extrabold tabular grid place-items-center shrink-0 shadow-[0_4px_12px_-4px_rgba(16,185,129,0.45)]">
                  {r.rank}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-body font-extrabold text-slate-900 truncate">{r.schoolName}</div>
                  <div className="text-caption muted leading-tight mt-0.5 flex items-center gap-1.5">
                    <span className="truncate">{r.district}</span>
                    <span className="text-slate-300">·</span>
                    <span className="inline-flex items-center gap-0.5 text-emerald-700 font-bold whitespace-nowrap">
                      <ArrowUpRight size={9} />+{r.improvement.toFixed(1)}
                    </span>
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[16px] font-extrabold tabular text-emerald-700 leading-none">{r.ssaAvg.toFixed(1)}</div>
                  <div className="text-[10px] muted font-semibold mt-1">SSA</div>
                </div>
                <ChevronRight
                  size={14}
                  className={cn(
                    "text-[var(--color-edify-muted)] shrink-0 transition-transform",
                    open && "rotate-90",
                  )}
                />
              </button>

              {open && (
                <div id={`best-${r.rank}-detail`} className="px-3 pb-3 -mt-1 space-y-3">
                  <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-3 gap-y-3 rounded-xl bg-white border border-[var(--color-edify-border)] p-3.5">
                    <Fact icon={<MapPin size={11} />}        label="District" value={r.district} />
                    <Fact icon={<UserCircle size={11} />}    label="Assigned CCEO" value={r.cceo} />
                    <Fact label="SSA Average" value={
                      <span className="inline-flex items-baseline gap-1">
                        <span className="text-emerald-700">{r.ssaAvg.toFixed(1)}</span>
                        <span className="muted text-[11px] font-semibold">/ 10</span>
                      </span>
                    } />
                    <Fact icon={<TrendingUp size={11} />} label="Improvement" value={
                      <span className="text-emerald-700">+{r.improvement.toFixed(1)} pts</span>
                    } />
                    <Fact icon={<Footprints size={11} />}    label="Visits"    value={r.visits} />
                    <Fact icon={<GraduationCap size={11} />} label="Trainings" value={r.trainings} />
                    <Fact label="Package Status" value={
                      <span className={cn(
                        "inline-flex items-center px-1.5 py-[1.5px] rounded-md text-[10.5px] font-bold",
                        r.packageStatus === "Complete"
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-amber-100 text-amber-800",
                      )}>
                        {r.packageStatus}
                      </span>
                    } />
                    <Fact label="Salesforce" value={`${r.salesforceCompliance}%`} />
                    <Fact label="Champion Recommendation" value={
                      <span className={cn(
                        "inline-flex items-center px-1.5 py-[1.5px] rounded-md border text-[10.5px] font-bold",
                        r.championRecommendation === "Champion Review"
                          ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                          : "bg-sky-50 text-sky-700 border-sky-200",
                      )}>
                        {r.championRecommendation}
                      </span>
                    } fullWidth />
                  </dl>

                  <div className="flex items-center gap-2 flex-wrap">
                    <Link
                      href="/core-schools"
                      className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-bold hover:bg-[var(--color-edify-dark)] transition-colors whitespace-nowrap"
                    >
                      <Trophy size={12} />
                      Promote to champion
                    </Link>
                    <Link
                      href={`/schools?name=${encodeURIComponent(r.schoolName)}`}
                      className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/60 transition-colors whitespace-nowrap"
                    >
                      Open school
                      <ArrowUpRight size={11} />
                    </Link>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <CheckCircle2 size={12} className="text-emerald-600" />
          <span className="font-bold">{replicaBestPerforming.filter((r) => r.packageStatus === "Complete").length}</span>
          <span className="muted">complete · ready for Champion Review</span>
        </span>
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <Sparkles size={12} className="text-amber-500" />
          <span className="muted">Tap a row to see the full school packet</span>
        </span>
      </div>
    </article>
  );
}

// ───────────── Core Schools Needing More Attention ─────────────

const RISK_TONE: Record<ReplicaAttentionRow["riskTone"], string> = {
  rose:   "bg-rose-100   text-rose-700",
  amber:  "bg-amber-100  text-amber-800",
  violet: "bg-violet-100 text-violet-700",
};

const RISK_BORDER: Record<ReplicaAttentionRow["riskTone"], string> = {
  rose:   "border-l-rose-500",
  amber:  "border-l-amber-500",
  violet: "border-l-violet-500",
};

function NeedingAttentionTable() {
  const [openName, setOpenName] = useState<string | null>(null);

  return (
    <article className="card p-3.5 h-full flex flex-col">
      <header className="flex items-center justify-between gap-2 mb-2">
        <h3 className="text-body-lg font-extrabold tracking-tight">Core Schools Needing More Attention</h3>
        <Link
          href="/notifications"
          className="text-[11.5px] font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-0.5 whitespace-nowrap"
        >
          View All <ArrowUpRight size={11} />
        </Link>
      </header>

      <ul className="flex flex-col gap-2">
        {replicaAttention.map((r) => {
          const open = openName === r.schoolName;
          return (
            <li
              key={r.schoolName}
              className={cn(
                "rounded-xl border border-l-[3px] bg-white overflow-hidden transition-colors",
                RISK_BORDER[r.riskTone],
                open
                  ? "row-active-glow border-transparent bg-[var(--color-edify-soft)]/30"
                  : "border-[var(--color-edify-border)]",
              )}
            >
              <button
                type="button"
                onClick={() => setOpenName(open ? null : r.schoolName)}
                aria-expanded={open}
                aria-controls={`attention-${r.schoolName.replace(/\s+/g, "-")}-detail`}
                className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-[var(--color-edify-soft)]/40 transition-colors"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-body font-extrabold text-slate-900 truncate">{r.schoolName}</div>
                  <div className="text-caption muted leading-tight inline-flex items-center gap-1 mt-0.5">
                    <Building2 size={10} />
                    {r.district}
                    <span aria-hidden className="mx-1 opacity-50">·</span>
                    <span className="truncate">{r.cceo}</span>
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[16px] font-extrabold tabular text-rose-700 leading-none">{r.ssaScore.toFixed(1)}</div>
                  <div className="text-[9.5px] muted font-bold uppercase tracking-wide mt-0.5">SSA</div>
                </div>
                <ChevronRight
                  size={14}
                  className={cn(
                    "text-[var(--color-edify-muted)] shrink-0 transition-transform",
                    open && "rotate-90",
                  )}
                />
              </button>

              {open && (
                <div
                  id={`attention-${r.schoolName.replace(/\s+/g, "-")}-detail`}
                  className="px-3 pb-3 -mt-1 space-y-3"
                >
                  <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-3 gap-y-3 rounded-xl bg-white border border-[var(--color-edify-border)] p-3.5">
                    <Fact icon={<MapPin size={11} />}        label="District" value={r.district} />
                    <Fact icon={<UserCircle size={11} />}    label="Assigned CCEO" value={r.cceo} />
                    <Fact label="SSA Score" value={
                      <span className="inline-flex items-baseline gap-1">
                        <span className="text-rose-700">{r.ssaScore.toFixed(1)}</span>
                        <span className="muted text-[11px] font-semibold">/ 10</span>
                      </span>
                    } />
                    <Fact icon={<AlertOctagon size={11} />} label="Gap to Package" value={
                      <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-amber-100 text-amber-800 text-[10px] font-extrabold tabular">
                        {r.gapToPackage}
                      </span>
                    } />
                    <Fact icon={<Footprints size={11} />}    label="Visits"    value={r.visitsCompleted} />
                    <Fact icon={<GraduationCap size={11} />} label="Trainings" value={r.trainingsCompleted} />
                    <Fact label="Lowest Intervention" value={r.lowestIntervention} fullWidth />
                    <Fact label="Risk Reason" value={
                      <span className={cn(
                        "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10.5px] font-bold",
                        RISK_TONE[r.riskTone],
                      )}>
                        <AlertOctagon size={9} />
                        {r.riskReason}
                      </span>
                    } fullWidth />
                  </dl>

                  {/* Recommended action callout — the highest-leverage
                      output of the row. Used to be hidden in a thin
                      muted column; now it's the visual anchor of the
                      expanded body. */}
                  <div className="rounded-lg bg-amber-50 border border-amber-100 px-3 py-2.5 flex items-start gap-2">
                    <Award size={13} className="text-amber-600 shrink-0 mt-0.5" />
                    <div className="min-w-0">
                      <div className="text-[10px] muted font-semibold uppercase tracking-wide">Recommended next action</div>
                      <div className="text-[12.5px] font-semibold text-slate-800 leading-snug mt-0.5">{r.recommendedAction}</div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 flex-wrap">
                    <Link
                      href="/plans/new"
                      className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-bold hover:bg-[var(--color-edify-dark)] transition-colors whitespace-nowrap"
                    >
                      <Calendar size={12} />
                      Plan next action
                    </Link>
                    <Link
                      href={`/schools?name=${encodeURIComponent(r.schoolName)}`}
                      className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/60 transition-colors whitespace-nowrap"
                    >
                      Open school
                      <ArrowUpRight size={11} />
                    </Link>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <AlertOctagon size={12} className="text-rose-600" />
          <span className="font-bold">{replicaAttention.filter((r) => r.riskTone === "rose").length}</span>
          <span className="muted">high-risk schools · tap to see the recommended action</span>
        </span>
      </div>
    </article>
  );
}

// ────────── Helpers ────────────────────────────────────────────────

function Fact({
  icon,
  label,
  value,
  fullWidth = false,
}: {
  icon?: React.ReactNode;
  label: string;
  value: React.ReactNode;
  fullWidth?: boolean;
}) {
  return (
    <div className={cn("min-w-0", fullWidth && "col-span-2 sm:col-span-4")}>
      <dt className="text-[10px] muted font-semibold uppercase tracking-wide flex items-center gap-1">
        {icon && <span className="text-[var(--color-edify-muted)]">{icon}</span>}
        {label}
      </dt>
      <dd className="text-[13px] font-extrabold tracking-tight mt-0.5 truncate">{value}</dd>
    </div>
  );
}
