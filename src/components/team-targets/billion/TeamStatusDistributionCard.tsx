"use client";

import { MapPin, Users } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { MetricStrip } from "@/components/ui/MetricStrip";
import { teamStatusDistribution } from "@/lib/team-targets-billion-mock";
import { cn } from "@/lib/utils";

// Team Status Distribution — the right-side rail that anchors the
// Pace + Staff Needs Support row. Surfaces:
//   1. The staff-bucket breakdown (On Track / Slightly Behind / High
//      Risk / Critical) as 4 KPI tiles + a stacked bar
//   2. Regions ranked by team achievement %
//
// Equivalent to the my-targets Today Focus rail in spirit — gives a
// program lead the cohort shape at a glance.
export function TeamStatusDistributionCard() {
  const d = teamStatusDistribution;
  return (
    <SectionCard
      icon={<Users size={13} />}
      title="Team Status Distribution"
      subtitle={`${d.total} staff supervised across regions`}
    >
      {/* 4 KPI tiles */}
      <div className="mb-3">
        <MetricStrip
          bare
          columns="grid-cols-2"
          metrics={d.buckets.map((b) => ({
            key: b.key,
            label: b.label,
            value: b.count,
            caption: `${b.countLabel} · ${b.pct}%`,
            tone: b.tone === "good" ? "good" : b.tone === "warn" ? "alert" : "default",
          }))}
        />
      </div>

      {/* Stacked bar */}
      <div className="flex h-2 rounded-full overflow-hidden mb-2">
        {d.buckets.map((b) => (
          <span
            key={b.key}
            className="h-full"
            title={`${b.label}: ${b.count} (${b.pct}%)`}
            style={{ width: `${b.pct}%`, backgroundColor: b.color }}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] muted">
        {d.buckets.map((b) => (
          <span key={b.key} className="inline-flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: b.color }} />
            <span>{b.label} · {b.count}</span>
          </span>
        ))}
      </div>

      {/* Regions ranked */}
      <div className="mt-4 pt-3 border-t border-[#eef2f4]">
        <div className="text-[9.5px] uppercase tracking-[0.12em] text-slate-500 font-bold mb-2 inline-flex items-center gap-1.5">
          <MapPin size={10} className="opacity-70" />
          Regions Ranked
        </div>
        <ul className="space-y-1.5">
          {d.regionsBehind.map((r) => (
            <li key={r.region} className="flex items-center gap-2 text-[11px]">
              <span className={cn(
                "w-1.5 h-1.5 rounded-full shrink-0",
                r.tone === "watch" ? "bg-amber-500"
                : "bg-rose-500",
              )} />
              <span className="font-semibold text-slate-700 flex-1 truncate">{r.region}</span>
              <span className={cn(
                "tabular font-extrabold",
                r.tone === "watch" ? "text-amber-700"
                : "text-rose-700",
              )}>
                {r.pct}%
              </span>
            </li>
          ))}
        </ul>
      </div>
    </SectionCard>
  );
}
