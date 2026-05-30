"use client";

import {
  Activity,
  AlertTriangle,
  AlertOctagon,
  ArrowUpRight,
  Award,
  Building2,
  ChevronRight,
  Crown,
  Footprints,
  GraduationCap,
  Layers,
  Sparkles,
  TrendingDown,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import {
  ssaClusterPerformance,
  ssaClusterColumnOrder,
  ssaClusterColumnMap,
  urgentSchools,
  type UrgentSchoolRow,
} from "@/lib/cpl-mock";
import { cn } from "@/lib/utils";

// ───────────── Shared scoring + tone helpers ─────────────

// 5-step heatmap so the eye can rank clusters without reading
// numbers. Thresholds match the SSA scoring rubric (≥80 excellent,
// ≥70 good, ≥60 watch, ≥45 weak, <45 critical).
function scoreClass(v: number): { chip: string; ring: string } {
  if (v >= 80) return { chip: "bg-emerald-100 text-emerald-800",  ring: "ring-emerald-200" };
  if (v >= 70) return { chip: "bg-emerald-50  text-emerald-700",  ring: "ring-emerald-100" };
  if (v >= 60) return { chip: "bg-amber-100   text-amber-800",    ring: "ring-amber-200"   };
  if (v >= 45) return { chip: "bg-amber-50    text-amber-700",    ring: "ring-amber-100"   };
  return        { chip: "bg-rose-100    text-rose-800",     ring: "ring-rose-200"    };
}

const riskTone = (r: UrgentSchoolRow["risk"]) => (r === "High" ? "red" : "amber");

// Public wrapper — keeps the existing import path working for
// `cpl/page.tsx`. Renders two billion-dollar SectionCards stacked
// (mobile) or side-by-side (desktop ≥ lg).
export function SchoolSsaIntelligenceCard() {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <InterventionPerformanceByClusterCard />
      <SchoolsNeedingUrgentAttentionCard />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// 1) Intervention Performance by Cluster
// ─────────────────────────────────────────────────────────────

export function InterventionPerformanceByClusterCard() {
  // Sort + extrema for the KPI strip + headline.
  const sorted    = [...ssaClusterPerformance].sort((a, b) => b.overall - a.overall);
  const best      = sorted[0];
  const worst     = sorted[sorted.length - 1];
  const avgOverall = Math.round(
    ssaClusterPerformance.reduce((a, c) => a + c.overall, 0) / ssaClusterPerformance.length,
  );

  // Find the weakest dimension across all clusters — the strongest
  // operational nudge this card can produce. ("Linkage is dragging
  // every cluster down" beats "your average is 63%".)
  const dimensionAverages = ssaClusterColumnOrder.map((k) => {
    const avg = Math.round(
      ssaClusterPerformance.reduce((a, c) => a + c.scores[k], 0) / ssaClusterPerformance.length,
    );
    return { key: k, avg };
  });
  const weakestDim   = dimensionAverages.reduce((w, d) => (d.avg < w.avg ? d : w));
  const strongestDim = dimensionAverages.reduce((s, d) => (d.avg > s.avg ? d : s));

  const headline = `${worst.cluster} trails at ${worst.overall}% — ${best.cluster} leads at ${best.overall}%. ${ssaClusterColumnMap[weakestDim.key].short} is the weakest dimension (${weakestDim.avg}%).`;

  return (
    <SectionCard
      icon={<Activity size={13} />}
      title="Intervention Performance by Cluster"
      subtitle={headline}
      actions={
        <a
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
          href="#ssa-intelligence"
        >
          View All
          <ArrowUpRight size={11} />
        </a>
      }
    >
      {/* KPI strip — best / worst / avg / weakest dimension. */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5 mb-4">
        <ClusterStat
          icon={Crown}
          label="Top Cluster"
          value={`${best.overall}%`}
          caption={best.cluster}
          tone="good"
          stagger="stagger-1"
        />
        <ClusterStat
          icon={AlertOctagon}
          label="Weakest"
          value={`${worst.overall}%`}
          caption={worst.cluster}
          tone="warn"
          stagger="stagger-2"
        />
        <ClusterStat
          icon={Layers}
          label="Avg Overall"
          value={`${avgOverall}%`}
          caption={`${ssaClusterPerformance.length} clusters tracked`}
          tone="neutral"
          stagger="stagger-3"
        />
        <ClusterStat
          icon={TrendingDown}
          label="Weakest Dim."
          value={`${weakestDim.avg}%`}
          caption={ssaClusterColumnMap[weakestDim.key].short}
          tone="warn"
          stagger="stagger-4"
        />
      </div>

      {/* Mobile + tablet: stacked cluster cards. Each cluster reads
          as a heatmap row — overall pill at top-right, then a 3×2
          mini-grid of the 6 SSA dimensions, each chip colored by
          score so the eye spots weak spots without reading numbers. */}
      <div className="md:hidden space-y-2.5">
        {ssaClusterPerformance.map((row) => {
          const overallTone = scoreClass(row.overall);
          return (
            <div
              key={row.cluster}
              className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3 space-y-2.5"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-body font-extrabold leading-tight text-slate-900">{row.cluster}</div>
                  <div className="text-caption muted font-semibold">Cluster overall score</div>
                </div>
                <span
                  className={cn(
                    "inline-flex items-center justify-center min-w-[54px] h-8 px-2.5 rounded-lg text-[15px] font-extrabold tabular ring-1",
                    overallTone.chip,
                    overallTone.ring,
                  )}
                >
                  {row.overall}%
                </span>
              </div>
              <div className="grid grid-cols-3 gap-1.5">
                {ssaClusterColumnOrder.map((k) => {
                  const v = row.scores[k];
                  const tone = scoreClass(v);
                  return (
                    <div
                      key={k}
                      title={ssaClusterColumnMap[k].full}
                      className="rounded-md bg-[var(--color-edify-soft)]/30 px-1.5 py-1.5 text-center"
                    >
                      <div className="text-[9.5px] font-bold uppercase tracking-wide text-slate-500 truncate">
                        {ssaClusterColumnMap[k].short}
                      </div>
                      <div
                        className={cn(
                          "mt-0.5 inline-flex items-center justify-center min-w-[36px] h-6 px-1.5 rounded-md text-[11.5px] font-extrabold tabular",
                          tone.chip,
                        )}
                      >
                        {v}%
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {/* Desktop heatmap table — same data, dense layout. Cluster
          left, 6 dimension cells, overall right. Score chips share
          the same colour scale as the mobile cards. */}
      <div className="hidden md:block overflow-x-auto scrollbar -mx-1 px-1 rounded-xl border border-[var(--color-edify-border)] bg-white">
        <table className="w-full text-body">
          <thead>
            <tr className="bg-gradient-to-r from-[var(--color-edify-soft)] to-[var(--color-edify-soft)]/40 text-caption uppercase tracking-wide text-slate-600">
              <th scope="col" className="text-left font-bold py-2.5 px-3">Cluster</th>
              {ssaClusterColumnOrder.map((k) => (
                <th key={k} className="text-center font-bold py-2.5 px-2" title={ssaClusterColumnMap[k].full}>
                  {ssaClusterColumnMap[k].short}
                </th>
              ))}
              <th scope="col" className="text-center font-bold py-2.5 px-3">Overall</th>
            </tr>
          </thead>
          <tbody>
            {ssaClusterPerformance.map((row, idx) => {
              const overallTone = scoreClass(row.overall);
              const last = idx === ssaClusterPerformance.length - 1;
              return (
                <tr
                  key={row.cluster}
                  className={cn(
                    "transition-colors hover:bg-[var(--color-edify-soft)]/40",
                    !last && "border-b border-[#eef2f4]",
                  )}
                >
                  <td className="text-left font-bold py-2 px-3 whitespace-nowrap text-slate-900">
                    {row.cluster}
                  </td>
                  {ssaClusterColumnOrder.map((k) => {
                    const v = row.scores[k];
                    const tone = scoreClass(v);
                    return (
                      <td key={k} className="text-center py-2 px-1.5">
                        <span
                          className={cn(
                            "inline-flex items-center justify-center w-12 h-7 rounded-md text-[11.5px] font-extrabold tabular",
                            tone.chip,
                          )}
                        >
                          {v}%
                        </span>
                      </td>
                    );
                  })}
                  <td className="text-center py-2 px-3">
                    <span
                      className={cn(
                        "inline-flex items-center justify-center w-14 h-7 rounded-md text-[12px] font-extrabold tabular ring-1",
                        overallTone.chip,
                        overallTone.ring,
                      )}
                    >
                      {row.overall}%
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <TrendingUp size={12} className="text-emerald-600" />
          <span className="font-bold">Strongest:</span>
          <span className="muted">{ssaClusterColumnMap[strongestDim.key].short} ({strongestDim.avg}%)</span>
        </span>
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <TrendingDown size={12} className="text-rose-600" />
          <span className="font-bold">Push next:</span>
          <span className="muted">{ssaClusterColumnMap[weakestDim.key].short} ({weakestDim.avg}%)</span>
        </span>
      </div>
    </SectionCard>
  );
}

// ─────────────────────────────────────────────────────────────
// 2) Schools Needing Urgent Attention
// ─────────────────────────────────────────────────────────────

const ISSUE_ICON: Record<UrgentSchoolRow["issue"], LucideIcon> = {
  "No Visit, No Training": AlertOctagon,
  "No Visit":              Footprints,
  "No Training":           GraduationCap,
};

export function SchoolsNeedingUrgentAttentionCard() {
  // Sort by risk (High first) then by ssaScore ascending so the
  // worst schools land at the top of the list.
  const sorted = [...urgentSchools].sort((a, b) => {
    if (a.risk === b.risk) return a.ssaScore - b.ssaScore;
    return a.risk === "High" ? -1 : 1;
  });

  const highCount   = urgentSchools.filter((s) => s.risk === "High").length;
  const mediumCount = urgentSchools.filter((s) => s.risk === "Medium").length;
  const avgScore    = Math.round(
    urgentSchools.reduce((a, s) => a + s.ssaScore, 0) / urgentSchools.length,
  );

  // Issue counts → "most common issue" framing for the takeaway.
  const issueCounts = new Map<UrgentSchoolRow["issue"], number>();
  urgentSchools.forEach((s) => issueCounts.set(s.issue, (issueCounts.get(s.issue) ?? 0) + 1));
  const mostCommon = [...issueCounts.entries()].sort((a, b) => b[1] - a[1])[0];

  const headline = `${urgentSchools.length} schools flagged — ${highCount} High risk, ${mediumCount} Medium. Avg SSA: ${avgScore}%.`;

  return (
    <SectionCard
      icon={<AlertTriangle size={13} className="text-[var(--color-danger)]" />}
      title="Schools Needing Urgent Attention"
      subtitle={headline}
      actions={
        <Link
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
          href="/schools"
        >
          View All
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5 mb-4">
        <ClusterStat
          icon={AlertOctagon}
          label="High Risk"
          value={highCount}
          caption={highCount === 0 ? "All clear" : "Immediate action"}
          tone="warn"
          stagger="stagger-1"
        />
        <ClusterStat
          icon={AlertTriangle}
          label="Medium"
          value={mediumCount}
          caption="Plan this month"
          tone={mediumCount > 0 ? "watch" : "good"}
          stagger="stagger-2"
        />
        <ClusterStat
          icon={Award}
          label="Avg SSA"
          value={`${avgScore}%`}
          caption={avgScore < 45 ? "Below critical line" : "Below target"}
          tone="warn"
          stagger="stagger-3"
        />
        <ClusterStat
          icon={Sparkles}
          label="Top Issue"
          value={mostCommon[1]}
          caption={mostCommon[0]}
          tone="watch"
          stagger="stagger-4"
        />
      </div>

      {/* Row cards — color-coded left edge, school header, SSA score,
          issue, drilldown. Now that this card spans the full row
          width, schools fan out into a responsive grid (1 col on
          phone → 2 at sm → 3 at lg → 5 at xl) so the worst 5–6
          schools sit on a single line. */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-2.5">
        {sorted.map((s) => {
          const Icon = ISSUE_ICON[s.issue];
          const edge = s.risk === "High" ? "border-l-rose-500 bg-rose-50/30" : "border-l-amber-500";
          const scoreTone =
            s.ssaScore < 45 ? "text-rose-700"
            : s.ssaScore < 60 ? "text-amber-700"
            : "text-emerald-700";
          return (
            <div
              key={s.id}
              className={cn(
                "rounded-xl border border-[var(--color-edify-border)] border-l-[3px] bg-white p-2.5 flex flex-col gap-1.5 card-lift cursor-pointer tile-in",
                edge,
              )}
            >
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <div className="text-body font-extrabold leading-tight text-slate-900 truncate">
                    {s.school}
                  </div>
                  <div className="text-caption muted leading-tight inline-flex items-center gap-1 mt-0.5">
                    <Building2 size={9} />
                    {s.district}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className={cn("text-[18px] font-extrabold tabular leading-none", scoreTone)}>
                    {s.ssaScore}%
                  </div>
                  <div className="text-[9px] muted font-bold uppercase tracking-wide mt-0.5">
                    SSA
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-1.5 text-caption font-semibold text-slate-700">
                <Icon size={11} className={cn("shrink-0", s.risk === "High" ? "text-rose-600" : "text-amber-600")} />
                <span className="truncate">{s.issue}</span>
              </div>
              <div className="flex items-center justify-between gap-1.5 mt-auto pt-1">
                <StatusBadge tone={riskTone(s.risk)}>{s.risk}</StatusBadge>
                <Link
                  href={`/schools/${s.id}`}
                  className="inline-flex items-center gap-0.5 text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline"
                >
                  Open
                  <ChevronRight size={11} />
                </Link>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] leading-snug">
        <span className="font-bold text-slate-700">SSA performance leads school priority.</span>
        <span className="muted"> Most common issue: <span className="font-semibold text-slate-700">{mostCommon[0]}</span> ({mostCommon[1]} schools). Inactivity and missing visits / trainings are tie-breakers.</span>
      </div>
    </SectionCard>
  );
}

// ───────────── ClusterStat ─────────────

type StatTone = "good" | "warn" | "watch" | "neutral";

const STAT_TONE: Record<StatTone, { bg: string; iconBg: string; iconColor: string; valueColor: string }> = {
  good: {
    bg:         "bg-gradient-to-br from-emerald-50 to-white border-emerald-200",
    iconBg:     "bg-emerald-100",
    iconColor:  "text-emerald-700",
    valueColor: "text-emerald-800",
  },
  warn: {
    bg:         "bg-gradient-to-br from-rose-50 to-white border-rose-200",
    iconBg:     "bg-rose-100",
    iconColor:  "text-rose-700",
    valueColor: "text-rose-800",
  },
  watch: {
    bg:         "bg-gradient-to-br from-amber-50 to-white border-amber-200",
    iconBg:     "bg-amber-100",
    iconColor:  "text-amber-700",
    valueColor: "text-amber-800",
  },
  neutral: {
    bg:         "bg-gradient-to-br from-slate-50 to-white border-slate-200",
    iconBg:     "bg-slate-100",
    iconColor:  "text-slate-600",
    valueColor: "text-slate-900",
  },
};

function ClusterStat({
  icon: Icon,
  label,
  value,
  caption,
  tone,
  stagger,
}: {
  icon: LucideIcon;
  label: string;
  value: number | string;
  caption: string;
  tone: StatTone;
  stagger?: string;
}) {
  const p = STAT_TONE[tone];
  const glowClass =
    tone === "good"    ? "glow-emerald"
    : tone === "warn"  ? "glow-rose"
    : tone === "watch" ? "glow-amber"
    : "glow-slate";
  return (
    <div className={cn("rounded-xl border card-lift cursor-default tile-in p-2.5 flex items-start gap-2", stagger, p.bg)}>
      <span className={cn("w-8 h-8 rounded-lg grid place-items-center shrink-0", p.iconBg)}>
        <Icon size={14} className={p.iconColor} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[9.5px] font-bold uppercase tracking-wide text-slate-500">
          {label}
        </div>
        <div className={cn("text-[18px] font-extrabold tabular leading-none mt-0.5 num-hero", p.valueColor, glowClass)}>
          {value}
        </div>
        <div className="text-caption muted font-semibold mt-0.5 truncate">{caption}</div>
      </div>
    </div>
  );
}
