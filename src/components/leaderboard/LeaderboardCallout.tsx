"use client";

import Link from "next/link";
import { Trophy, ArrowRight } from "lucide-react";
import { leaderboardSummaryFor } from "@/lib/leaderboard-mock";
import type { CurrentUser } from "@/lib/schools-mock";

// Drop into CCEO / CPL / Director dashboards. Reads from the same engine
// that powers the leaderboard page; no duplicated math.
export function LeaderboardCallout({
  variant,
  user,
}: {
  variant: "cpl" | "cceo" | "director";
  user: CurrentUser;
}) {
  const s = leaderboardSummaryFor(user);
  return (
    <section className="card p-3.5">
      <div className="flex items-center gap-2 mb-2">
        <span className="w-7 h-7 rounded-md grid place-items-center bg-amber-100 text-amber-700">
          <Trophy size={14} />
        </span>
        <div className="leading-tight">
          <h3 className="text-[13px] font-bold">Verified Impact Leaderboard</h3>
          <div className="text-caption muted">
            {variant === "cceo"
              ? "Your verified work this month"
              : variant === "cpl"
                ? "Your Team's verified results this month"
                : "Country leaders this month"}
          </div>
        </div>
        <Link
          href="/leaderboard"
          className="ml-auto inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)]"
        >
          Open leaderboard
          <ArrowRight size={11} />
        </Link>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Tile label="Monthly Champion"     value={s.topStaffName ?? "—"}    sub={s.topStaffScore != null ? `${s.topStaffScore} pts` : ""} />
        <Tile label="Best Program Lead"     value={s.bestProgramLead ?? "—"} sub={s.bestProgramLeadScore != null ? `${s.bestProgramLeadScore} score` : ""} />
        <Tile
          label={variant === "cceo" ? "Your rank" : "Top staff in your scope"}
          value={variant === "cceo" ? (s.myRank != null ? `#${s.myRank}` : "—") : (s.topStaffName ?? "—")}
          sub={variant === "cceo" ? (s.myAchievement != null ? `${s.myAchievement} overall` : "") : ""}
        />
      </div>
      <div className="mt-2 pt-2 border-t border-[#eef2f4] text-caption muted">
        Verified results only — leave, route load, and approval delays are factored before any escalation.
      </div>
    </section>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-[var(--color-edify-border)] p-2.5">
      <div className="text-caption muted font-semibold leading-tight uppercase tracking-wide">{label}</div>
      <div className="text-body-lg font-extrabold leading-tight mt-1 truncate">{value}</div>
      {sub && <div className="text-caption muted mt-0.5">{sub}</div>}
    </div>
  );
}
