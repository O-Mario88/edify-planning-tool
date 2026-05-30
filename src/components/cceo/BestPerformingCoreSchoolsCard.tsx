"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  Award,
  Building2,
  CheckCircle2,
  ChevronRight,
  Footprints,
  GraduationCap,
  MapPin,
  Sparkles,
  Star,
  TrendingUp,
  Trophy,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  bestPerformingCoreSchools,
  championPipeline,
  type CceoBestSchool,
} from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<CceoBestSchool["status"], string> = {
  "Complete":        "bg-emerald-100 text-emerald-700",
  "Nearly Complete": "bg-amber-100   text-amber-700",
};

const REC_TONE: Record<CceoBestSchool["recommendation"], string> = {
  "Champion Review":    "bg-emerald-50 text-emerald-700 border-emerald-200",
  "Potential Champion": "bg-blue-50    text-blue-700    border-blue-200",
};

export function BestPerformingCoreSchoolsCard() {
  const top         = bestPerformingCoreSchools[0];
  const completeCt  = bestPerformingCoreSchools.filter((s) => s.status === "Complete").length;
  const avgImprovement = +(
    bestPerformingCoreSchools.reduce((a, s) => a + s.improvement, 0) /
    bestPerformingCoreSchools.length
  ).toFixed(1);

  const [openRank, setOpenRank] = useState<number | null>(null);

  // Champion pipeline — folded in from the now-retired Champion Pipeline
  // donut card. The full funnel (Review / Potential / Not Eligible)
  // renders as a stat strip above the school table.
  const reviewSeg     = championPipeline.segments.find((s) => s.key === "review");
  const potentialSeg  = championPipeline.segments.find((s) => s.key === "potential");
  const ineligibleSeg = championPipeline.segments.find((s) => s.key === "ineligible");

  const headline = `${top.schoolName} leads at ${top.ssaAvg.toFixed(1)} — improved ${top.improvement.toFixed(1)} pts vs last year. ${reviewSeg?.count ?? 0} ready for Champion Review · ${potentialSeg?.count ?? 0} Potential Champions in the pipeline.`;

  return (
    <SectionCard
      id="best-performing"
      icon={<Trophy size={13} className="text-emerald-600" />}
      title="Best Performing Core Schools"
      subtitle={headline}
      actions={
        <Link
          href="/leaderboard"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View All
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      {/* Champion pipeline strip — folded in from the standalone
          Champion Pipeline donut card. Same data (4 / 8 / 2), expressed
          as 3 stat tiles + a stacked bar so the funnel is glanceable
          without taking 5 inches of vertical real estate. */}
      <div className="mb-4">
        <div className="flex items-baseline justify-between mb-2">
          <div className="text-caption uppercase tracking-[0.12em] muted font-bold inline-flex items-center gap-1.5">
            <Star size={11} className="text-amber-500" />
            Champion School Pipeline
          </div>
          <div className="text-[11px] muted font-semibold tabular">
            {championPipeline.total} schools tracked
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2 mb-2.5">
          <PipelineStat
            icon={CheckCircle2}
            label="Champion Review"
            count={reviewSeg?.count ?? 0}
            pct={reviewSeg?.pct ?? 0}
            color={reviewSeg?.color ?? "#10b981"}
            tone="good"
            caption="ready to promote"
          />
          <PipelineStat
            icon={Star}
            label="Potential Champion"
            count={potentialSeg?.count ?? 0}
            pct={potentialSeg?.pct ?? 0}
            color={potentialSeg?.color ?? "#22c55e"}
            tone="info"
            caption="building toward review"
          />
          <PipelineStat
            icon={Award}
            label="Not Eligible"
            count={ineligibleSeg?.count ?? 0}
            pct={ineligibleSeg?.pct ?? 0}
            color={ineligibleSeg?.color ?? "#cbd5e1"}
            tone="neutral"
            caption="below threshold"
          />
        </div>
        {/* Funnel bar — proportional stacked segments so the eye reads
            the full pipeline shape in one glance. */}
        <div className="flex h-2 rounded-full overflow-hidden">
          {championPipeline.segments.map((s) => (
            <div
              key={s.key}
              className="h-full"
              title={`${s.label}: ${s.count} (${s.pct}%)`}
              style={{ width: `${s.pct}%`, backgroundColor: s.color }}
            />
          ))}
        </div>
      </div>

      {/* Unified accordion — same row shape on every breakpoint, expands
          inline to a facts grid. Replaces the prior mobile-cards-+
          -desktop-9-column-table split so the user reads + drills in
          the same way no matter where they are. */}
      <ul className="space-y-2">
        {bestPerformingCoreSchools.map((s) => {
          const open = openRank === s.rank;
          return (
            <li
              key={s.rank}
              className={cn(
                "rounded-xl border border-[var(--color-edify-border)] bg-white overflow-hidden transition-colors",
                open && "bg-[var(--color-edify-soft)]/30",
              )}
            >
              <button
                type="button"
                onClick={() => setOpenRank(open ? null : s.rank)}
                aria-expanded={open}
                aria-controls={`best-school-${s.rank}-detail`}
                className="w-full flex items-center gap-3 p-3 text-left hover:bg-[var(--color-edify-soft)]/40 transition-colors"
              >
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-emerald-500 to-emerald-700 text-white text-[12px] font-extrabold grid place-items-center shrink-0 shadow-sm">
                  {s.rank}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-bold leading-tight truncate text-slate-900">{s.schoolName}</div>
                  <div className="text-caption muted leading-tight inline-flex items-center gap-1 mt-0.5">
                    <Building2 size={10} />
                    {s.district}
                    <span aria-hidden className="mx-1 opacity-50">·</span>
                    <ArrowUpRight size={10} className="text-emerald-600" />
                    <span className="text-emerald-700 font-semibold">+{s.improvement.toFixed(1)}</span>
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[18px] font-extrabold tabular leading-none text-emerald-700">
                    {s.ssaAvg.toFixed(1)}
                  </div>
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
                  id={`best-school-${s.rank}-detail`}
                  className="px-3 pb-3 -mt-1 space-y-3"
                >
                  <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-3 gap-y-3 rounded-xl bg-white border border-[var(--color-edify-border)] p-3.5">
                    <Fact icon={<MapPin size={11} />}        label="District" value={s.district} />
                    <Fact label="SSA Average" value={
                      <span className="inline-flex items-baseline gap-1">
                        <span className="text-emerald-700">{s.ssaAvg.toFixed(1)}</span>
                        <span className="muted text-[11px] font-semibold">/ 10</span>
                      </span>
                    } />
                    <Fact icon={<TrendingUp size={11} />}     label="Improvement" value={
                      <span className="text-emerald-700">+{s.improvement.toFixed(1)} pts</span>
                    } />
                    <Fact label="Rank" value={`#${s.rank}`} />
                    <Fact icon={<Footprints size={11} />}     label="Visits"    value={s.visits} />
                    <Fact icon={<GraduationCap size={11} />}  label="Trainings" value={s.trainings} />
                    <Fact label="Status" value={
                      <span className={cn("inline-flex items-center px-1.5 py-[1.5px] rounded-md text-[10.5px] font-bold", STATUS_TONE[s.status])}>
                        {s.status}
                      </span>
                    } />
                    <Fact label="Recommendation" value={
                      <span className={cn("inline-flex items-center px-1.5 py-[1.5px] rounded-md border text-[10.5px] font-bold", REC_TONE[s.recommendation])}>
                        {s.recommendation}
                      </span>
                    } />
                  </dl>

                  <div className="flex items-center gap-2 flex-wrap">
                    <Link
                      href="/leaderboard"
                      className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-bold hover:bg-[var(--color-edify-dark)] transition-colors whitespace-nowrap"
                    >
                      <Trophy size={12} />
                      Promote to champion
                    </Link>
                    <Link
                      href={`/schools?name=${encodeURIComponent(s.schoolName)}`}
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
          <span className="font-bold">Full package:</span>
          <span className="muted">{completeCt} of {bestPerformingCoreSchools.length} have both 4 visits + 4 trainings</span>
        </span>
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <Sparkles size={12} className="text-amber-500" />
          <span className="font-bold">Promote next:</span>
          <span className="muted">{reviewSeg?.count ?? 0} ready to formally Champion · avg +{avgImprovement} pts vs last year</span>
        </span>
      </div>
    </SectionCard>
  );
}

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

// ───────────── PipelineStat ─────────────

type PipelineTone = "good" | "info" | "neutral";

const PIPELINE_TONE: Record<PipelineTone, { bg: string; iconBg: string; iconColor: string }> = {
  good: {
    bg:        "bg-gradient-to-br from-emerald-50 to-white border-emerald-200",
    iconBg:    "bg-emerald-100",
    iconColor: "text-emerald-700",
  },
  info: {
    bg:        "bg-gradient-to-br from-sky-50 to-white border-sky-200",
    iconBg:    "bg-sky-100",
    iconColor: "text-sky-700",
  },
  neutral: {
    bg:        "bg-gradient-to-br from-slate-50 to-white border-slate-200",
    iconBg:    "bg-slate-100",
    iconColor: "text-slate-600",
  },
};

function PipelineStat({
  icon: Icon,
  label,
  count,
  pct,
  color,
  tone,
  caption,
}: {
  icon: LucideIcon;
  label: string;
  count: number;
  pct: number;
  color: string;
  tone: PipelineTone;
  caption: string;
}) {
  const p = PIPELINE_TONE[tone];
  return (
    <div className={cn("rounded-xl border p-2.5 flex items-start gap-2", p.bg)}>
      <span className={cn("w-8 h-8 rounded-lg grid place-items-center shrink-0", p.iconBg)}>
        <Icon size={14} className={p.iconColor} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{ backgroundColor: color }}
            aria-hidden
          />
          <div className="text-[9.5px] font-bold uppercase tracking-wide text-slate-500 truncate">
            {label}
          </div>
        </div>
        <div className="text-[18px] font-extrabold tabular leading-none mt-1 inline-flex items-baseline gap-1">
          {count}
          <span className="text-caption muted font-semibold">({pct}%)</span>
        </div>
        <div className="text-caption muted font-semibold mt-0.5 truncate">{caption}</div>
      </div>
    </div>
  );
}
