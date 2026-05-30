"use client";

import Link from "next/link";
import { Trophy } from "lucide-react";
import { recentAchievements } from "@/lib/work-plan-mock";

export function RecentAchievementsCard() {
  return (
    <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-[15px] font-extrabold tracking-tight">Recent Achievements</h3>
        <Link href="/leaderboard" className="text-body font-semibold text-emerald-600">
          View All
        </Link>
      </div>
      <div className="divide-y divide-[var(--color-edify-divider)]">
        {recentAchievements.map((a) => (
          <div key={a.id} className="flex items-start gap-3 py-3">
            <span className="w-10 h-10 rounded-full bg-emerald-50 grid place-items-center text-emerald-600 shrink-0">
              <Trophy size={16} />
            </span>
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-bold leading-tight">{a.title}</div>
              <div className="text-[12px] muted leading-snug mt-0.5">{a.body}</div>
            </div>
            <div className="text-[11px] muted shrink-0 whitespace-nowrap mt-0.5">{a.date}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
