"use client";

import { Trophy, Users, BadgeCheck, ArrowUpRight } from "lucide-react";
import {
  MobileSubpageShell,
  MobileKpiGrid,
  MobileSectionCard,
  type MobileKpiTile,
  type KpiTone,
} from "@/components/mobile/views/MobileSubpageShell";
import {
  overallMonthlyLeaders,
  mostImprovedStaff,
} from "@/lib/leaderboard-mock";
import { cn } from "@/lib/utils";

function rankPill(rank: number): { tone: KpiTone; label: string } {
  if (rank === 1) return { tone: "yellow", label: "🥇" };
  if (rank === 2) return { tone: "slate",  label: "🥈" };
  if (rank === 3) return { tone: "amber",  label: "🥉" };
  return { tone: "edify", label: `#${rank}` };
}

export function LeaderboardMobileView() {
  const top10 = overallMonthlyLeaders.slice(0, 10);
  const improved = mostImprovedStaff.slice(0, 5);

  const avgAchievement = Math.round(
    overallMonthlyLeaders.reduce((a, r) => a + r.achievementPercent, 0) /
      Math.max(1, overallMonthlyLeaders.length),
  );

  const tiles: MobileKpiTile[] = [
    { key: "leaders",   Icon: Trophy,     label: "Leaders Tracked",  value: overallMonthlyLeaders.length.toString(), caption: "this month",      tone: "yellow" },
    { key: "avg",       Icon: BadgeCheck, label: "Avg Achievement",  value: `${avgAchievement}%`,                    caption: "verified portion", tone: "green"  },
    { key: "improved",  Icon: ArrowUpRight, label: "Most Improved",  value: mostImprovedStaff.length.toString(),     caption: "since last cycle", tone: "edify"  },
    { key: "ccecount",  Icon: Users,      label: "CCEOs",            value: overallMonthlyLeaders.filter(r => r.role === "CCEO").length.toString(), caption: "in leaderboard", tone: "violet" },
  ];

  return (
    <MobileSubpageShell
      title="Verified Impact"
      subtitle={`${overallMonthlyLeaders.length} staff ranked · only verified work counts`}
    >
      <MobileKpiGrid tiles={tiles} cols={2} />

      <MobileSectionCard
        title="This Month — Top 10"
        subtitle="Overall verified achievement"
      >
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {top10.map((r) => {
            const p = rankPill(r.rank);
            return (
              <li key={r.leaderboardId} className="px-3 py-2.5 flex items-center gap-3">
                <span className={cn(
                  "h-8 w-8 rounded-md grid place-items-center shrink-0 text-[12px] font-extrabold",
                  p.tone === "yellow" ? "bg-yellow-100 text-yellow-700" :
                  p.tone === "amber"  ? "bg-amber-100  text-amber-700"  :
                  p.tone === "slate"  ? "bg-slate-200  text-slate-700"  :
                                        "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
                )}>
                  {p.label}
                </span>
                <div className="h-9 w-9 rounded-full bg-[var(--color-edify-primary)] text-white text-[11px] font-extrabold grid place-items-center shrink-0">
                  {r.initials}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-body font-extrabold tracking-tight truncate">{r.staffName}</div>
                  <div className="text-caption muted truncate">{r.role} · {r.district ?? r.region}</div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-body-lg font-extrabold tabular leading-none">
                    {r.achievementPercent}%
                  </div>
                  <div className="text-[10px] muted mt-0.5">
                    {r.verifiedCompleted}/{r.targetValue}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      </MobileSectionCard>

      <MobileSectionCard title="Most Improved" subtitle="Biggest jumps vs last cycle">
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {improved.map((r) => {
            const initials = r.staffName
              .split(" ")
              .map((p) => p[0])
              .join("")
              .slice(0, 2)
              .toUpperCase();
            return (
              <li key={r.staffId} className="px-3 py-2.5 flex items-center gap-3">
                <div className="h-9 w-9 rounded-full bg-emerald-500 text-white text-[11px] font-extrabold grid place-items-center shrink-0">
                  {initials}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-body font-extrabold tracking-tight truncate">{r.staffName}</div>
                  <div className="text-caption muted truncate">{r.category}</div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-body-lg font-extrabold tabular leading-none text-emerald-600 inline-flex items-center gap-0.5">
                    <ArrowUpRight size={11} />
                    {r.improvementPoints} pts
                  </div>
                  <div className="text-[10px] muted mt-0.5">vs last cycle</div>
                </div>
              </li>
            );
          })}
        </ul>
      </MobileSectionCard>
    </MobileSubpageShell>
  );
}
