"use client";

import Link from "next/link";
import {
  Building2,
  GraduationCap,
  ShieldCheck,
  Footprints,
  FileText,
  ArrowUpRight,
  ArrowDownRight,
  ChevronRight,
  Calendar,
  type LucideIcon,
} from "lucide-react";
import {
  cplPersonalFieldwork,
  cplFieldworkSummary,
  cplFieldworkUpcoming,
  type CplFieldworkTile,
} from "@/lib/cpl-mock";
import { cn } from "@/lib/utils";

const ICON: Record<CplFieldworkTile["icon"], LucideIcon> = {
  schoolVisit: Building2,
  training:    GraduationCap,
  ssa:         ShieldCheck,
  follow:      Footprints,
  debrief:     FileText,
};

const TONE: Record<CplFieldworkTile["tone"], { bg: string; text: string; bar: string }> = {
  edify:  { bg: "bg-[var(--color-edify-soft)]/80", text: "text-[var(--color-edify-primary)]", bar: "bg-[var(--color-edify-primary)]" },
  green:  { bg: "bg-emerald-100", text: "text-emerald-700", bar: "bg-emerald-500" },
  amber:  { bg: "bg-amber-100",   text: "text-amber-700",   bar: "bg-amber-500" },
  violet: { bg: "bg-violet-100",  text: "text-violet-700",  bar: "bg-violet-500" },
  blue:   { bg: "bg-sky-100",     text: "text-sky-700",     bar: "bg-sky-500" },
};

const UPCOMING_ICON = {
  "School Visit":      Building2,
  "Cluster Training":  GraduationCap,
  "SSA":               ShieldCheck,
  "Follow-Up Visit":   Footprints,
} as const;

// "My Field Work" card — surfaces the CPL's *direct* field activity
// (visits, trainings, SSAs, follow-ups, debriefs) so the role reads as
// player-coach, not just management.
export function CplFieldWorkCard() {
  return (
    <article id="my-field-work" className="card p-3.5 flex flex-col">
      {/* Header */}
      <header className="flex items-baseline justify-between mb-3 gap-2">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <h2 className="text-[var(--text-body-lg)] lg:text-[var(--text-h-xs)] font-extrabold tracking-tight">
              My Field Work
            </h2>
            <span className="text-[var(--text-caption)] muted">({cplFieldworkSummary.monthLabel})</span>
          </div>
          <p className="text-[var(--text-body)] muted leading-snug">
            Visits, trainings, and SSAs I personally conducted — alongside team management.
          </p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[var(--text-h-md)] font-extrabold tabular leading-none">
            {cplFieldworkSummary.overallPct}%
          </div>
          <div className="text-[var(--text-caption)] muted">overall</div>
        </div>
      </header>

      {/* Topline strip */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        <Topline label="Days in field" value={`${cplFieldworkSummary.daysInField}`} />
        <Topline label="Schools touched" value={`${cplFieldworkSummary.schoolsTouched}`} />
        <Topline label="Achievement" value={`${cplFieldworkSummary.overallPct}%`} />
      </div>

      {/* Tile grid: 5 tiles */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2.5">
        {cplPersonalFieldwork.map((t) => {
          const Icon = ICON[t.icon];
          const tone = TONE[t.tone];
          const pct = Math.round((t.value / Math.max(1, t.total)) * 100);
          const TrendIcon = t.trendTone === "up" ? ArrowUpRight : ArrowDownRight;
          const trendCls = t.trendTone === "up" ? "text-emerald-600" : "text-rose-600";
          return (
            <div
              key={t.key}
              className="rounded-xl border border-[var(--color-edify-border)] p-3 flex flex-col gap-1.5"
            >
              <div className="flex items-start gap-2">
                <span className={cn("h-8 w-8 rounded-md grid place-items-center shrink-0", tone.bg, tone.text)}>
                  <Icon size={14} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[var(--text-caption)] muted font-semibold leading-tight line-clamp-2 min-h-[26px]">
                    {t.label}
                  </div>
                </div>
              </div>
              <div className="flex items-baseline gap-1.5">
                <span className="text-[var(--text-h-sm)] font-extrabold tabular leading-none">{t.value}</span>
                <span className="text-[var(--text-caption)] muted font-semibold tabular">/ {t.total}</span>
              </div>
              <div className="h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                <div className={cn("h-full rounded-full", tone.bar)} style={{ width: `${Math.min(100, pct)}%` }} />
              </div>
              <div className={cn("text-[var(--text-tiny)] font-semibold inline-flex items-center gap-0.5", trendCls)}>
                <TrendIcon size={10} />
                {t.trendDelta}
              </div>
            </div>
          );
        })}
      </div>

      {/* Upcoming personal fieldwork */}
      <section className="mt-4 rounded-xl border border-[var(--color-edify-border)] overflow-hidden">
        <header className="px-3 pt-3 pb-2 flex items-baseline justify-between">
          <h3 className="text-[var(--text-body)] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <Calendar size={13} className="text-[var(--color-edify-primary)]" />
            My upcoming field activities
          </h3>
          <Link
            href="/today"
            className="text-[var(--text-caption)] font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-0.5"
          >
            View today
            <ChevronRight size={11} />
          </Link>
        </header>
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {cplFieldworkUpcoming.map((u) => {
            const Icon = UPCOMING_ICON[u.type];
            return (
              <li key={u.key} className="px-3 py-2.5 flex items-center gap-3">
                <span className="h-8 w-8 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                  <Icon size={13} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-[var(--text-body)] font-extrabold tracking-tight truncate">{u.title}</div>
                  <div className="text-[var(--text-caption)] muted truncate">
                    {u.type} · {u.cluster} · {u.date}
                  </div>
                </div>
                <span className="text-[var(--text-caption)] muted shrink-0">{u.weekLabel}</span>
              </li>
            );
          })}
        </ul>
      </section>

      {/* Quick actions */}
      <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Link href="/plans/new"          className="h-9 rounded-lg border border-[var(--color-edify-border)] inline-flex items-center justify-center gap-1.5 text-[var(--text-caption)] font-semibold hover:bg-[var(--color-edify-soft)]/40">
          <Building2 size={12} />
          Plan a visit
        </Link>
        <Link href="/trainings"          className="h-9 rounded-lg border border-[var(--color-edify-border)] inline-flex items-center justify-center gap-1.5 text-[var(--text-caption)] font-semibold hover:bg-[var(--color-edify-soft)]/40">
          <GraduationCap size={12} />
          Browse trainings
        </Link>
        <Link href="/ssa"                className="h-9 rounded-lg border border-[var(--color-edify-border)] inline-flex items-center justify-center gap-1.5 text-[var(--text-caption)] font-semibold hover:bg-[var(--color-edify-soft)]/40">
          <ShieldCheck size={12} />
          Open SSA
        </Link>
        <Link href="/field-intelligence" className="h-9 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white inline-flex items-center justify-center gap-1.5 text-[var(--text-caption)] font-semibold shadow-sm shadow-emerald-500/25">
          <FileText size={12} />
          Submit Debrief
        </Link>
      </div>
    </article>
  );
}

function Topline({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-[var(--color-edify-soft)]/40 border border-[var(--color-edify-border)] p-2.5 text-center">
      <div className="text-[var(--text-caption)] muted font-bold uppercase tracking-wide leading-tight">{label}</div>
      <div className="text-[var(--text-h-sm)] font-extrabold tabular leading-none mt-1">{value}</div>
    </div>
  );
}
