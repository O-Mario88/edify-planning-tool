"use client";

import { useMemo, useState } from "react";
import { Trophy, ArrowUp, ArrowDown, Minus } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  LEADERBOARD_CATEGORIES,
  calculateCategoryLeaderboard,
  type LeaderboardCategory,
  type LeaderboardRecord,
} from "@/lib/leaderboard-mock";
import { cn } from "@/lib/utils";

const rankBg = (rank: number) =>
  rank === 1
    ? "bg-amber-200 text-amber-900"
    : rank === 2
      ? "bg-slate-200 text-slate-800"
      : rank === 3
        ? "bg-orange-200 text-orange-900"
        : "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]";

function trend(r: LeaderboardRecord) {
  if (r.achievementPercent >= 100) return { Icon: ArrowUp, cls: "text-emerald-700" };
  if (r.achievementPercent >= 75)  return { Icon: Minus,   cls: "text-amber-700" };
  return { Icon: ArrowDown, cls: "text-rose-700" };
}

export function CategoryLeaderboardTabs({
  initialCategory = "Overall",
  showAll = true,
}: {
  initialCategory?: LeaderboardCategory;
  showAll?: boolean;
}) {
  const [category, setCategory] = useState<LeaderboardCategory>(initialCategory);
  const rows = useMemo(() => calculateCategoryLeaderboard(category), [category]);
  const visible = showAll ? rows : rows.slice(0, 5);

  return (
    <SectionCard
      icon={<Trophy size={13} />}
      title="Verified Impact Leaderboard"
      subtitle="Verified results only. Context such as leave, workload, route difficulty, and assigned school load is considered before performance escalation."
      actions={
        <div className="text-[11px] muted">November 2025 · Monthly</div>
      }
    >
      <div className="flex flex-wrap items-center gap-1.5 mb-3">
        {LEADERBOARD_CATEGORIES.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setCategory(c)}
            className={cn(
              "h-7 px-2.5 rounded-md text-[11.5px] font-semibold transition-colors",
              category === c
                ? "bg-[var(--color-edify-primary)] text-white"
                : "border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]",
            )}
          >
            {c}
          </button>
        ))}
      </div>

      <table className="w-full dtable">
        <thead>
          <tr>
            <th scope="col" className="text-left">#</th>
            <th scope="col" className="text-left">Staff</th>
            <th scope="col" className="text-left">Region</th>
            <th scope="col" className="text-left">Program Lead</th>
            <th scope="col" className="text-right">Verified</th>
            <th scope="col" className="text-right">Target</th>
            <th scope="col" className="text-right">Achievement</th>
            <th scope="col" className="text-right">SF Compliance</th>
            <th scope="col" className="text-right">Verification %</th>
            <th scope="col" className="text-left">Trend</th>
            <th scope="col" className="text-left">Badge</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((r) => {
            const t = trend(r);
            return (
              <tr key={r.leaderboardId}>
                <td>
                  <span className={cn("inline-flex items-center justify-center w-7 h-7 rounded-md text-[11px] font-extrabold tabular", rankBg(r.rank))}>
                    {r.rank}
                  </span>
                </td>
                <td>
                  <div className="flex items-center gap-2">
                    <div className="w-7 h-7 rounded-full bg-[var(--color-edify-primary)] text-white text-[11px] font-bold grid place-items-center shrink-0">
                      {r.initials}
                    </div>
                    <span className="text-body font-semibold whitespace-nowrap">{r.staffName}</span>
                  </div>
                </td>
                <td className="text-[12px] muted">{r.region}</td>
                <td className="text-[12px] muted">{r.programLeadName ?? "—"}</td>
                <td className="text-right tabular text-body font-semibold">{r.verifiedCompleted}</td>
                <td className="text-right tabular text-[12px] muted">{r.targetValue}</td>
                <td className="text-right tabular text-[13px] font-extrabold">
                  {r.achievementPercent}
                  {r.targetCategory === "Overall" || r.targetCategory === "Salesforce Compliance" ? "" : "%"}
                </td>
                <td className="text-right tabular text-[12px]">{r.salesforceCompliancePercent}%</td>
                <td className="text-right tabular text-[12px]">{r.verificationPassRate}%</td>
                <td>
                  <span className={cn("inline-flex items-center gap-1 text-[11.5px] font-bold", t.cls)}>
                    <t.Icon size={12} />
                  </span>
                </td>
                <td className="text-[11.5px] font-semibold text-[var(--color-edify-primary)]">
                  {r.recognitionBadge ?? "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </SectionCard>
  );
}
