import Link from "next/link";
import { ArrowUpRight, UserCog } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import {
  staffTargetPerformance,
  type StaffTargetRow,
} from "@/lib/team-targets-mock";
import { cn } from "@/lib/utils";

// Staff Performance Summary — leadership visibility without HR detail.
// The CD sees pace distribution, early warnings, and who needs support
// review; row-level context (leave, route difficulty, funding delays)
// stays on /staff where the support conversation happens.

const PACE_TONE: Record<StaffTargetRow["paceStatus"], string> = {
  "On Track":        "bg-emerald-50 text-emerald-700 border-emerald-200",
  "Slightly Behind": "bg-amber-50 text-amber-700 border-amber-200",
  "Behind":          "bg-amber-50 text-amber-700 border-amber-200",
  "High Risk":       "bg-rose-50 text-rose-700 border-rose-200",
  "Critical":        "bg-rose-50 text-rose-700 border-rose-200",
};

export function StaffPerformanceSummary() {
  const rows = staffTargetPerformance;
  const onTrack = rows.filter((s) => s.paceStatus === "On Track" || s.paceStatus === "Slightly Behind").length;
  const atRisk = rows.filter((s) => s.paceStatus === "High Risk" || s.paceStatus === "Critical");
  const earlyWarnings = rows.filter((s) => s.earlyWarningTriggered).length;
  const supportReviews = rows.filter((s) => s.possiblePipReviewRequired).length;
  const avgAchievement = rows.length
    ? Math.round(rows.reduce((a, s) => a + s.achievementPercent, 0) / rows.length)
    : 0;

  const metrics: MetricCell[] = [
    { key: "tracked",  label: "Staff tracked",      value: rows.length },
    { key: "ontrack",  label: "On / near track",    value: onTrack, tone: "good" },
    { key: "risk",     label: "High risk / critical", value: atRisk.length, tone: atRisk.length ? "alert" : "default" },
    { key: "warn",     label: "Early warnings",     value: earlyWarnings, tone: earlyWarnings ? "alert" : "default" },
    { key: "review",   label: "Support reviews due", value: supportReviews },
    { key: "avg",      label: "Avg achievement",    value: `${avgAchievement}%` },
  ];

  const watchlist = [...atRisk].sort((a, b) => a.achievementPercent - b.achievementPercent).slice(0, 4);

  return (
    <SectionCard
      icon={<UserCog size={13} />}
      title="Staff Performance Summary"
      actions={
        <Link href="/staff" className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline">
          Full summary <ArrowUpRight size={12} />
        </Link>
      }
    >
      <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-3 xl:grid-cols-6" />
      {watchlist.length > 0 && (
        <ul className="mt-2.5 divide-y divide-[var(--color-edify-divider)]">
          {watchlist.map((s) => (
            <li key={s.staffId} className="flex items-center gap-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="text-[12.5px] font-bold tracking-tight truncate">{s.staffName}</div>
                <div className="text-[11px] muted truncate">
                  {s.role} · {s.region}
                  {s.earlyWarningReasons[0] ? ` · ${s.earlyWarningReasons[0]}` : ""}
                </div>
              </div>
              <span className={cn("shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-extrabold", PACE_TONE[s.paceStatus])}>
                {s.paceStatus}
              </span>
              <span className="shrink-0 w-10 text-right text-[12px] font-extrabold tabular">{s.achievementPercent}%</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[11px] muted leading-snug">
        Context flags (leave, funding delays, route difficulty) are reviewed before any escalation — overload and underperformance look the same in raw numbers.
      </p>
    </SectionCard>
  );
}
