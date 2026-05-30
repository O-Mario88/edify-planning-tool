"use client";

import Link from "next/link";
import {
  Activity,
  ArrowUpRight,
  BookOpen,
  GraduationCap,
  Heart,
  Scale,
  ScrollText,
  Shield,
  Sparkles,
  TrendingDown,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { ssaInterventionRows, type CceoInterventionRow } from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

const ICON_MAP: Record<CceoInterventionRow["icon"], LucideIcon> = {
  heart:         Heart,
  book:          BookOpen,
  shield:        Shield,
  graduationCap: GraduationCap,
  schoolBook:    ScrollText,
  scale:         Scale,
  wallet:        Wallet,
  users:         Users,
};

function barColor(score: number) {
  if (score >= 7.5) return "#10b981"; // emerald
  if (score >= 6.5) return "#f59e0b"; // amber
  return "#ef4444";                   // rose
}

export function SsaInterventionCard() {
  // Sort + extrema for the editorial headline.
  const sorted = [...ssaInterventionRows].sort((a, b) => b.score - a.score);
  const best   = sorted[0];
  const worst  = sorted[sorted.length - 1];
  const avg    = +(ssaInterventionRows.reduce((a, r) => a + r.score, 0) / ssaInterventionRows.length).toFixed(1);
  const belowThreshold = ssaInterventionRows.filter((r) => r.score < 7.0).length;

  const headline = `${best.label} leads at ${best.score.toFixed(1)} — ${worst.label} trails at ${worst.score.toFixed(1)}. Average: ${avg}.`;

  return (
    <SectionCard
      icon={<Activity size={13} />}
      title="SSA Performance by Intervention"
      subtitle={headline}
      actions={
        <Link
          href="/ssa#interventions"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View All
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      <ul className="space-y-2 flex-1">
        {ssaInterventionRows.map((row) => {
          const Icon = ICON_MAP[row.icon];
          const widthPct = (row.score / 10) * 100;
          const color = barColor(row.score);
          return (
            <li key={row.key} className="flex items-center gap-2">
              <Icon size={13} className="text-[var(--color-edify-muted)] shrink-0" />
              <span className="text-[11px] font-semibold flex-1 min-w-0 truncate w-[140px]">
                {row.label}
              </span>
              <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${widthPct}%`, backgroundColor: color }}
                />
              </div>
              <span className="text-[11.5px] font-extrabold tabular shrink-0 w-[28px] text-right">
                {row.score.toFixed(1)}
              </span>
            </li>
          );
        })}
      </ul>

      {/* X-axis ticks */}
      <div className="mt-3 ml-[170px] flex justify-between text-[10px] muted tabular pr-[36px]">
        {[0, 2, 4, 6, 8, 10].map((v) => (
          <span key={v}>{v}</span>
        ))}
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <Sparkles size={12} className="text-emerald-600" />
          <span className="font-bold">Strongest:</span>
          <span className="muted">{best.label} ({best.score.toFixed(1)})</span>
        </span>
        <span className={cn("inline-flex items-center gap-1.5 text-slate-700")}>
          <TrendingDown size={12} className="text-rose-600" />
          <span className="font-bold">Push next:</span>
          <span className="muted">{worst.label} ({worst.score.toFixed(1)}) · {belowThreshold} dimension{belowThreshold === 1 ? "" : "s"} below 7.0</span>
        </span>
      </div>
    </SectionCard>
  );
}
