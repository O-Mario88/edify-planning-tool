"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  Award,
  Flame,
  Trophy,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { achievementMomentum } from "@/lib/my-targets-billion-mock";

// Achievement & Momentum — compact horizontal strip with three mini
// tiles (streak · best this month · recognition). Designed to fit
// directly under Needs Attention in the right column without doubling
// the row height; the previous vertical stack was 300px+ tall and
// blew out the row alignment with Pace & Forecast on the left.
export function AchievementMomentumCard() {
  const m = achievementMomentum;
  const recogInitials = initials(m.recognition.person);
  return (
    <SectionCard
      icon={<Trophy size={13} className="text-amber-500" />}
      title="Achievement & Momentum"
      actions={
        <Link
          href="/team-targets"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View Leaderboard
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {/* Streak */}
        <div className="rounded-xl border border-rose-200 bg-gradient-to-br from-rose-50 to-white p-2.5 flex items-center gap-2.5">
          <span className="w-9 h-9 rounded-lg bg-gradient-to-br from-rose-400 to-rose-600 text-white grid place-items-center shrink-0 shadow-[0_4px_12px_-2px_rgba(244,63,94,0.45)]">
            <Flame size={14} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[9.5px] uppercase tracking-wide muted font-bold truncate">{m.streak.label}</div>
            <div className="flex items-baseline gap-1 mt-0.5">
              <span className="text-[16px] font-extrabold tabular leading-none text-slate-900">{m.streak.value}</span>
              <span className="text-[10px] muted font-semibold">{m.streak.unit}</span>
            </div>
            <div className="text-[9.5px] muted font-semibold mt-0.5 truncate">{m.streak.caption}</div>
          </div>
        </div>

        {/* Best This Month */}
        <div className="rounded-xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-white p-2.5 flex items-center gap-2.5">
          <span className="w-9 h-9 rounded-lg bg-gradient-to-br from-emerald-400 to-emerald-600 text-white grid place-items-center shrink-0 shadow-[0_4px_12px_-2px_rgba(16,185,129,0.45)]">
            <Award size={14} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[9.5px] uppercase tracking-wide muted font-bold truncate">{m.bestMonth.label}</div>
            <div className="text-[11px] font-extrabold text-slate-900 leading-tight mt-0.5 truncate">
              {m.bestMonth.category}
            </div>
            <div className="flex items-baseline gap-1.5 mt-0.5">
              <span className="text-body-lg font-extrabold tabular leading-none text-emerald-700">{m.bestMonth.pct}</span>
              <span className="text-[9px] font-bold text-emerald-700 inline-flex items-center gap-0.5 truncate">
                <ArrowUpRight size={9} />
                {m.bestMonth.trend}
              </span>
            </div>
          </div>
        </div>

        {/* Recognition */}
        <div className="rounded-xl border border-amber-200 bg-gradient-to-br from-amber-50 to-white p-2.5 flex items-center gap-2.5">
          <span className="w-9 h-9 rounded-full bg-gradient-to-br from-amber-400 to-amber-600 text-white grid place-items-center shrink-0 shadow-[0_4px_12px_-2px_rgba(245,158,11,0.45)] text-caption font-extrabold">
            {recogInitials}
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[9.5px] uppercase tracking-wide muted font-bold truncate">{m.recognition.label}</div>
            <div className="text-[11px] font-extrabold text-slate-900 leading-tight mt-0.5 truncate">
              {m.recognition.person}
            </div>
            <div className="text-[9.5px] muted font-semibold mt-0.5 truncate">
              {m.recognition.title} · {m.recognition.verified.replace(" Verified Achievement", "")}
            </div>
          </div>
        </div>
      </div>
    </SectionCard>
  );
}

function initials(name: string): string {
  return name
    .split(" ")
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}
