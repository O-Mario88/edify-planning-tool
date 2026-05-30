"use client";

import { Star } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { programLeadLeaderboard } from "@/lib/leaderboard-mock";
import { cn } from "@/lib/utils";

const rankBg = (rank: number) =>
  rank === 1
    ? "bg-amber-200 text-amber-900"
    : rank === 2
      ? "bg-slate-200 text-slate-800"
      : rank === 3
        ? "bg-orange-200 text-orange-900"
        : "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]";

export function ProgramLeadLeaderboardCard() {
  return (
    <SectionCard
      icon={<Star size={13} className="text-violet-700" />}
      title="Best Performing Program Lead"
      subtitle="Score = team target (30%) + staff on track (15%) + verification (15%) + Salesforce (10%) + Core (10%) + backlog (10%) + support (5%) + feedback (5%)."
    >
      <table className="w-full dtable">
        <thead>
          <tr>
            <th scope="col" className="text-left">#</th>
            <th scope="col" className="text-left">Program Lead</th>
            <th scope="col" className="text-left">Region</th>
            <th scope="col" className="text-right">Staff</th>
            <th scope="col" className="text-right">Team Target</th>
            <th scope="col" className="text-right">Staff On Track</th>
            <th scope="col" className="text-right">Verification</th>
            <th scope="col" className="text-right">Salesforce</th>
            <th scope="col" className="text-right">Backlog Reduction</th>
            <th scope="col" className="text-right">Feedback</th>
            <th scope="col" className="text-right">PL Score</th>
            <th scope="col" className="text-left">Badge</th>
          </tr>
        </thead>
        <tbody>
          {programLeadLeaderboard.map((p) => (
            <tr key={p.programLeadId}>
              <td>
                <span className={cn("inline-flex items-center justify-center w-7 h-7 rounded-md text-[11px] font-extrabold tabular", rankBg(p.rank))}>
                  {p.rank}
                </span>
              </td>
              <td>
                <div className="flex items-center gap-2">
                  <div className="w-7 h-7 rounded-full bg-violet-200 text-violet-800 text-[11px] font-bold grid place-items-center shrink-0">
                    {p.initials}
                  </div>
                  <span className="text-body font-semibold whitespace-nowrap">{p.programLeadName}</span>
                </div>
              </td>
              <td className="text-[12px] muted">{p.region}</td>
              <td className="text-right tabular text-body">{p.staffSupervised}</td>
              <td className="text-right tabular text-body font-bold">{p.teamTargetAchievement}%</td>
              <td className="text-right tabular text-body">{p.staffOnTrackPercent}%</td>
              <td className="text-right tabular text-body">{p.verificationPassRate}%</td>
              <td className="text-right tabular text-body">{p.salesforceCompliancePercent}%</td>
              <td className="text-right tabular text-body">{p.backlogReductionScore}%</td>
              <td className="text-right tabular text-body">{p.feedbackScore}</td>
              <td className="text-right tabular text-body-lg font-extrabold text-[var(--color-edify-primary)]">
                {p.overallProgramLeadScore}
              </td>
              <td className="text-[11.5px] font-semibold text-violet-700">{p.recognitionBadge}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </SectionCard>
  );
}
