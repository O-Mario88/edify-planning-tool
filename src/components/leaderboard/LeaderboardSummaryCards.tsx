"use client";

import { Trophy, Star, Flame, Sparkles } from "lucide-react";
import {
  overallMonthlyLeaders,
  programLeadLeaderboard,
  mostImprovedStaff,
} from "@/lib/leaderboard-mock";

export function LeaderboardSummaryCards() {
  const top = overallMonthlyLeaders[0];
  const bestPl = programLeadLeaderboard[0];
  const improved = mostImprovedStaff[0];
  const consistencyLeader = [...overallMonthlyLeaders].sort(
    (a, b) => b.consistencyScore - a.consistencyScore,
  )[0];

  const tiles = [
    { label: "Monthly Target Champion",  value: top?.staffName ?? "—",          caption: `${top?.achievementPercent ?? 0}% overall score`,           Icon: Trophy,   tone: "bg-amber-100 text-amber-700" },
    { label: "Best Performing Program Lead", value: bestPl?.programLeadName ?? "—", caption: `${bestPl?.overallProgramLeadScore ?? 0} score · ${bestPl?.staffSupervised ?? 0} staff`, Icon: Star, tone: "bg-violet-100 text-violet-700" },
    { label: "Most Improved",            value: improved?.staffName ?? "—",     caption: `+${improved?.improvementPoints ?? 0} pts in ${improved?.category}`, Icon: Sparkles, tone: "bg-emerald-100 text-emerald-700" },
    { label: "Most Consistent",          value: consistencyLeader?.staffName ?? "—", caption: `${consistencyLeader?.consistencyScore ?? 0}% consistency`,    Icon: Flame, tone: "bg-rose-100 text-rose-700" },
  ];

  return (
    <section className="grid grid-cols-4 gap-3">
      {tiles.map((t) => (
        <div key={t.label} className="card p-3.5">
          <div className="flex items-start gap-3">
            <span className={`w-12 h-12 rounded-full grid place-items-center shrink-0 ${t.tone}`}>
              <t.Icon size={20} />
            </span>
            <div className="leading-tight min-w-0">
              <div className="text-[11px] muted font-semibold leading-tight uppercase tracking-wide">{t.label}</div>
              <div className="text-[16px] font-extrabold leading-tight mt-1 truncate">{t.value}</div>
              <div className="text-caption muted mt-0.5">{t.caption}</div>
            </div>
          </div>
        </div>
      ))}
    </section>
  );
}
