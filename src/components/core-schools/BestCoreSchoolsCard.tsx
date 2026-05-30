"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  Award,
  Building2,
  CheckCircle2,
  Crown,
  Sparkles,
  Star,
  Trophy,
  type LucideIcon,
} from "lucide-react";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import {
  rankBestPerformingCoreSchools,
  type ChampionStatus,
  type CoreSchoolRow,
} from "@/lib/core-schools-mock";
import { cn } from "@/lib/utils";

const championTone: Record<ChampionStatus, "green" | "violet" | "edify" | "grey"> = {
  "Not Eligible":             "grey",
  "Potential Champion":       "violet",
  "Champion Review Required": "violet",
  "Recommended as Champion":  "green",
  "Approved Champion School": "green",
};

export function BestCoreSchoolsCard({ schools }: { schools: CoreSchoolRow[] }) {
  const ranked = rankBestPerformingCoreSchools(schools).slice(0, 6);

  // Champion-pipeline summary, folded into this card so the "best" and
  // "ready for champion" narratives sit together. Real backend would
  // ship these counts; we derive from the live cohort.
  const potential        = schools.filter((s) => s.championStatus === "Potential Champion").length;
  const reviewRequired   = schools.filter((s) => s.championStatus === "Champion Review Required").length;
  const recommended      = schools.filter((s) => s.championStatus === "Recommended as Champion").length;
  const approved         = schools.filter((s) => s.championStatus === "Approved Champion School").length;
  const ready            = reviewRequired + recommended;
  const totalInPipeline  = potential + ready + approved;

  // Best of the best for the headline. Defensive fallback if cohort empty.
  const top              = ranked[0];
  const topSsa           = top?.latestVerifiedSsaAverage ?? 0;
  const topImprovement   = top?.yoyImprovement ?? 0;
  const completePackage  = ranked.filter((s) => s.visitsCompleted >= 4 && s.trainingsCompleted >= 4).length;

  const headline = top
    ? `${top.schoolName} leads at ${topSsa.toFixed(1)} — improved ${topImprovement >= 0 ? "+" : ""}${topImprovement.toFixed(1)} pts vs last FY. ${ready} ready for Champion Review · ${potential} Potential Champions in the pipeline.`
    : `${ready} ready for Champion Review · ${potential} Potential Champions in the pipeline.`;

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
      {/* Champion School Pipeline strip — folded in so the page no longer
          needs a competing donut card. Three stat tiles + a stacked
          funnel bar give the pipeline shape at a glance. */}
      <div className="mb-4">
        <div className="flex items-baseline justify-between mb-2">
          <div className="text-caption uppercase tracking-[0.12em] muted font-bold inline-flex items-center gap-1.5">
            <Star size={11} className="text-amber-500" />
            Champion School Pipeline
          </div>
          <div className="text-[11px] muted font-semibold tabular">
            {totalInPipeline} schools tracked
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2 mb-2.5">
          <PipelineStat
            icon={CheckCircle2}
            label="Ready for Review"
            count={ready}
            color="#10b981"
            tone="good"
            caption="promote this cycle"
          />
          <PipelineStat
            icon={Star}
            label="Potential Champion"
            count={potential}
            color="#22c55e"
            tone="info"
            caption="building toward review"
          />
          <PipelineStat
            icon={Award}
            label="Approved Champion"
            count={approved}
            color="#a3a3a3"
            tone="neutral"
            caption="already promoted"
          />
        </div>
        {totalInPipeline > 0 && (
          <div className="flex h-2 rounded-full overflow-hidden">
            <span className="h-full bg-emerald-500" style={{ width: `${(ready / totalInPipeline) * 100}%` }} />
            <span className="h-full bg-emerald-300" style={{ width: `${(potential / totalInPipeline) * 100}%` }} />
            <span className="h-full bg-slate-300"   style={{ width: `${(approved / totalInPipeline) * 100}%` }} />
          </div>
        )}
      </div>

      {/* Mobile-stacked rows */}
      <div className="md:hidden space-y-2">
        {ranked.map((s, i) => {
          const isLeader = i === 0;
          return (
            <div
              key={s.schoolId}
              className={cn(
                "rounded-xl border bg-white p-3 space-y-2",
                isLeader ? "border-emerald-200 bg-emerald-50/30" : "border-[var(--color-edify-border)]",
              )}
            >
              <div className="flex items-center gap-2.5">
                <div className="relative shrink-0">
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-emerald-500 to-emerald-700 text-white text-[12px] font-extrabold grid place-items-center shadow-sm">
                    {i + 1}
                  </div>
                  {isLeader && (
                    <span
                      className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-amber-500 grid place-items-center ring-2 ring-white"
                      title="Top performer this cohort"
                    >
                      <Crown size={9} className="text-white" />
                    </span>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-bold leading-tight truncate text-slate-900">{s.schoolName}</div>
                  <div className="text-caption muted leading-tight inline-flex items-center gap-1 mt-0.5">
                    <Building2 size={10} />
                    {s.district} · CCEO {s.assignedCceoName}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[18px] font-extrabold tabular leading-none text-emerald-700">
                    {s.latestVerifiedSsaAverage?.toFixed(1) ?? "—"}
                  </div>
                  <div className="text-[9.5px] muted font-bold uppercase tracking-wide mt-0.5">SSA</div>
                </div>
              </div>
              <div className="flex items-center justify-between gap-1.5 flex-wrap text-[11px]">
                <span className={cn(
                  "inline-flex items-center gap-1 font-semibold",
                  (s.yoyImprovement ?? 0) >= 0 ? "text-emerald-700" : "text-rose-700",
                )}>
                  <ArrowUpRight size={11} />
                  {(s.yoyImprovement ?? 0) >= 0 ? "+" : ""}{(s.yoyImprovement ?? 0).toFixed(1)} YoY
                </span>
                <span className="muted font-semibold tabular">{s.visitsCompleted}/4 V · {s.trainingsCompleted}/4 T</span>
                <StatusBadge tone={championTone[s.championStatus]}>{s.championStatus}</StatusBadge>
              </div>
            </div>
          );
        })}
      </div>

      {/* Desktop table — gradient header, hover rows, crown for #1.
          Internal vertical scroll keeps the card the same height as
          its row peers when the leaderboard grows. */}
      <div className="hidden md:block max-h-[280px] overflow-y-auto scrollbar -mx-1 px-1 rounded-xl border border-[var(--color-edify-border)] bg-white">
        <table className="w-full text-[11.5px]">
          <thead>
            <tr className="bg-gradient-to-r from-[var(--color-edify-soft)] to-[var(--color-edify-soft)]/40 text-[9.5px] uppercase tracking-wide text-slate-600">
              <th scope="col" className="text-left font-bold py-2 px-2">#</th>
              <th scope="col" className="text-left font-bold py-2 px-2">School</th>
              <th scope="col" className="text-left font-bold py-2 px-2">CCEO</th>
              <th scope="col" className="text-right font-bold py-2 px-2">SSA</th>
              <th scope="col" className="text-right font-bold py-2 px-2">YoY</th>
              <th scope="col" className="text-right font-bold py-2 px-2">Visits</th>
              <th scope="col" className="text-right font-bold py-2 px-2">Trainings</th>
              <th scope="col" className="text-left font-bold py-2 px-2">Champion</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((s, i) => {
              const last = i === ranked.length - 1;
              const isLeader = i === 0;
              return (
                <tr
                  key={s.schoolId}
                  className={cn("transition-colors hover:bg-[var(--color-edify-soft)]/40", !last && "border-b border-[#eef2f4]")}
                >
                  <td className="py-2 px-2">
                    <div className="relative inline-block">
                      <div className="w-7 h-7 rounded-full bg-gradient-to-br from-emerald-500 to-emerald-700 text-white text-[11px] font-extrabold grid place-items-center shadow-sm">
                        {i + 1}
                      </div>
                      {isLeader && (
                        <span
                          className="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full bg-amber-500 grid place-items-center ring-2 ring-white"
                          title="Top performer this cohort"
                        >
                          <Crown size={8} className="text-white" />
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="py-2 px-2 font-bold leading-tight">{s.schoolName}</td>
                  <td className="py-2 px-2 muted">{s.assignedCceoName}</td>
                  <td className="py-2 px-2 text-right font-extrabold tabular text-emerald-700">
                    {s.latestVerifiedSsaAverage?.toFixed(1) ?? "—"}
                  </td>
                  <td className="py-2 px-2 text-right">
                    <span className={cn("inline-flex items-center gap-0.5 font-bold tabular", (s.yoyImprovement ?? 0) >= 0 ? "text-emerald-700" : "text-rose-700")}>
                      <ArrowUpRight size={10} />
                      {(s.yoyImprovement ?? 0) >= 0 ? "+" : ""}{(s.yoyImprovement ?? 0).toFixed(1)}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-right tabular font-semibold">{s.visitsCompleted}/4</td>
                  <td className="py-2 px-2 text-right tabular font-semibold">{s.trainingsCompleted}/4</td>
                  <td className="py-2 px-2">
                    <StatusBadge tone={championTone[s.championStatus]}>{s.championStatus}</StatusBadge>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <CheckCircle2 size={12} className="text-emerald-600" />
          <span className="font-bold">Full package:</span>
          <span className="muted">{completePackage} of {ranked.length} on this leaderboard have 4 visits + 4 trainings</span>
        </span>
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <Sparkles size={12} className="text-amber-500" />
          <span className="font-bold">Promote next:</span>
          <span className="muted">{ready} ready for Champion review — book the panel this month</span>
        </span>
      </div>
    </SectionCard>
  );
}

// ───────────── PipelineStat ─────────────

type PipelineTone = "good" | "info" | "neutral";

const PIPELINE_TONE: Record<PipelineTone, { bg: string; iconBg: string; iconColor: string }> = {
  good:    { bg: "bg-gradient-to-br from-emerald-50 to-white border-emerald-200", iconBg: "bg-emerald-100", iconColor: "text-emerald-700" },
  info:    { bg: "bg-gradient-to-br from-sky-50 to-white border-sky-200",         iconBg: "bg-sky-100",     iconColor: "text-sky-700"     },
  neutral: { bg: "bg-gradient-to-br from-slate-50 to-white border-slate-200",     iconBg: "bg-slate-100",   iconColor: "text-slate-600"   },
};

function PipelineStat({
  icon: Icon,
  label,
  count,
  color,
  tone,
  caption,
}: {
  icon: LucideIcon;
  label: string;
  count: number;
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
          <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} aria-hidden />
          <div className="text-[9.5px] font-bold uppercase tracking-wide text-slate-500 truncate">
            {label}
          </div>
        </div>
        <div className="text-[18px] font-extrabold tabular leading-none mt-1">{count}</div>
        <div className="text-caption muted font-semibold mt-0.5 truncate">{caption}</div>
      </div>
    </div>
  );
}
