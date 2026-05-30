"use client";

import { Sparkles, ChevronDown } from "lucide-react";
import { SectionCard, TableEmptyRow } from "@/components/ui/primitives";
import { targetRecoveryFocus, type RiskLevel } from "@/lib/team-targets-mock";
import { cn } from "@/lib/utils";

const RISK: Record<RiskLevel, string> = {
  Low:      "bg-emerald-100 text-emerald-700",
  Medium:   "bg-amber-100 text-amber-700",
  High:     "bg-orange-100 text-orange-700",
  Critical: "bg-rose-100 text-rose-700",
};

export function TargetRecoveryFocusTable() {
  return (
    <SectionCard
      icon={<Sparkles size={13} />}
      title="Target Recovery Focus"
      subtitle="(Requires Immediate Action)"
      actions={
        <a className="text-[12px] font-semibold text-[var(--color-edify-primary)]" href="/team-targets">
          View All recovery items →
        </a>
      }
    >
      <table className="w-full dtable">
        <thead>
          <tr>
            <th scope="col" className="text-left">School / Team</th>
            <th scope="col" className="text-left">Region</th>
            <th scope="col" className="text-left">Owner</th>
            <th scope="col" className="text-right">Gap<br /><span className="font-medium normal-case muted text-caption">Activities</span></th>
            <th scope="col" className="text-left">Achievement %</th>
            <th scope="col" className="text-left">Recommended Action</th>
            <th scope="col" className="text-left">Deadline</th>
            <th scope="col" className="text-left">Risk Level</th>
            <th scope="col" className="text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {targetRecoveryFocus.map((r) => (
            <tr key={r.id}>
              <td className="text-body font-semibold whitespace-nowrap">{r.schoolOrTeam}</td>
              <td className="text-[12px] muted">{r.region}</td>
              <td>
                <div className="flex items-center gap-1.5">
                  <div className="w-6 h-6 rounded-full bg-[var(--color-edify-primary)] text-white text-[10px] font-bold grid place-items-center shrink-0">
                    {r.ownerInitials}
                  </div>
                  <span className="text-[12px]">{r.ownerName}</span>
                </div>
              </td>
              <td className="text-right tabular text-body font-bold text-[var(--color-danger)]">{r.gapActivities}</td>
              <td>
                <div className="flex items-center gap-2 min-w-[110px]">
                  <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                    <div
                      className={cn(
                        "h-full rounded-full",
                        r.achievementPercent >= 50 ? "bg-amber-500" : "bg-rose-500",
                      )}
                      style={{ width: `${r.achievementPercent}%` }}
                    />
                  </div>
                  <span className="text-[12px] font-bold tabular w-9 text-right">{r.achievementPercent}%</span>
                </div>
              </td>
              <td className="text-[12px]">{r.recommendedAction}</td>
              <td className="text-[12px] muted whitespace-nowrap">{r.deadline}</td>
              <td>
                <span className={cn("inline-flex items-center px-2 py-[2px] rounded-md text-[11px] font-bold", RISK[r.riskLevel])}>
                  {r.riskLevel}
                </span>
              </td>
              <td className="text-right">
                <div className="inline-flex items-center gap-1.5">
                  <button type="button" className="btn btn-sm">View Plan</button>
                  <button type="button" aria-label="More" className="h-7 w-7 rounded-md border border-[var(--color-edify-border)] grid place-items-center bg-white">
                    <ChevronDown size={12} />
                  </button>
                </div>
              </td>
            </tr>
          ))}
          {targetRecoveryFocus.length === 0 && (
            <TableEmptyRow
              colSpan={9}
              title="No teams or schools currently need recovery focus"
              body="Teams below target pacing or critical risk thresholds will surface here automatically — together with recommended next actions."
            />
          )}
        </tbody>
      </table>
    </SectionCard>
  );
}
