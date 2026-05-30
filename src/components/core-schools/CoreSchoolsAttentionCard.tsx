"use client";

import Link from "next/link";
import {
  AlertOctagon,
  AlertTriangle,
  ArrowUpRight,
  Building2,
  ChevronRight,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import {
  detectCoreSchoolsNeedingAttention,
  type CorePackageStatus,
  type CoreSchoolRow,
} from "@/lib/core-schools-mock";
import { cn } from "@/lib/utils";

const pkgTone: Record<CorePackageStatus, "green" | "amber" | "red" | "grey" | "blue"> = {
  "Not Started":       "red",
  Started:             "blue",
  "Halfway Supported": "amber",
  "Nearly Complete":   "green",
  "Package Complete":  "green",
  "Behind Schedule":   "amber",
  "Critical Gap":      "red",
};

// Map package status to a row left-edge color so the urgency reads at
// a glance — rose for critical / not started, amber for behind /
// halfway, emerald for nearly / complete.
const edgeTone: Record<CorePackageStatus, string> = {
  "Not Started":       "border-l-rose-500 bg-rose-50/30",
  Started:             "border-l-sky-400",
  "Halfway Supported": "border-l-amber-400",
  "Nearly Complete":   "border-l-emerald-400",
  "Package Complete":  "border-l-emerald-500",
  "Behind Schedule":   "border-l-amber-500",
  "Critical Gap":      "border-l-rose-500 bg-rose-50/30",
};

// Pick an issue icon by package status. Falls back to a generic alert
// so unknown statuses still render.
function statusIcon(status: CorePackageStatus): LucideIcon {
  if (status === "Critical Gap" || status === "Not Started") return AlertOctagon;
  if (status === "Behind Schedule") return AlertTriangle;
  return AlertTriangle;
}

export function CoreSchoolsAttentionCard({ schools }: { schools: CoreSchoolRow[] }) {
  const list = detectCoreSchoolsNeedingAttention(schools).slice(0, 8);

  // Editorial computations — surface the highest-priority signal so
  // the headline answers "what's most urgent?" not "here is a table."
  const critical    = schools.filter((s) => s.packageStatus === "Critical Gap" || s.packageStatus === "Not Started").length;
  const behind      = schools.filter((s) => s.packageStatus === "Behind Schedule").length;
  const zeroVisits  = schools.filter((s) => s.visitsCompleted === 0).length;
  const zeroTrain   = schools.filter((s) => s.trainingsCompleted === 0).length;
  const lowest      = list[0];
  const lowestSsa   = lowest?.latestVerifiedSsaAverage;
  const totalAttn   = list.length;

  const headline =
    lowest
      ? `${lowest.schoolName} is the most urgent — ${lowestSsa ? `SSA ${lowestSsa.toFixed(1)}, ` : "no SSA, "}${lowest.visitsCompleted}/4 visits, ${lowest.trainingsCompleted}/4 trainings. ${totalAttn} schools need attention this week.`
      : `${totalAttn} schools need attention this week.`;

  return (
    <SectionCard
      icon={<AlertTriangle size={13} className="text-[var(--color-danger)]" />}
      title="Core Schools Needing Attention"
      subtitle={headline}
      actions={
        <Link
          href="/notifications"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View All
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      {/* KPI strip removed to match the reference — the subtitle now
          carries the critical / behind / zero counts editorially. */}


      {/* Mobile-stacked rows */}
      <div className="md:hidden space-y-2">
        {list.map((s) => {
          const Icon = statusIcon(s.packageStatus);
          return (
            <div
              key={s.schoolId}
              className={cn(
                "rounded-xl border border-[var(--color-edify-border)] border-l-[3px] bg-white p-3 space-y-2",
                edgeTone[s.packageStatus],
              )}
            >
              <div className="flex items-start gap-2.5">
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-bold leading-tight truncate text-slate-900">{s.schoolName}</div>
                  <div className="text-caption muted leading-tight inline-flex items-center gap-1 mt-0.5">
                    <Building2 size={10} />
                    {s.district} · CCEO {s.assignedCceoName}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className={cn(
                    "text-[18px] font-extrabold tabular leading-none",
                    s.latestVerifiedSsaAverage == null
                      ? "text-rose-700"
                      : s.latestVerifiedSsaAverage < 6
                        ? "text-rose-700"
                        : "text-amber-700",
                  )}>
                    {s.latestVerifiedSsaAverage?.toFixed(1) ?? "—"}
                  </div>
                  <div className="text-[9.5px] muted font-bold uppercase tracking-wide mt-0.5">SSA</div>
                </div>
              </div>
              <div className="text-caption muted leading-snug inline-flex items-center gap-1.5">
                <Icon size={11} className={
                  s.packageStatus === "Critical Gap" || s.packageStatus === "Not Started"
                    ? "text-rose-600"
                    : "text-amber-600"
                } />
                <span className="font-semibold text-slate-700">{s.lowestIntervention ?? "Lowest intervention not yet identified"}</span>
              </div>
              <div className="flex items-center justify-between gap-2 flex-wrap text-caption">
                <span className="muted font-semibold tabular">{s.visitsCompleted}/4 V · {s.trainingsCompleted}/4 T</span>
                <StatusBadge tone={pkgTone[s.packageStatus]}>{s.packageStatus}</StatusBadge>
              </div>
              {s.riskReasons.length > 0 && (
                <div className="text-caption muted leading-snug">
                  {s.riskReasons.join(" · ")}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Desktop table — gradient header, hover rows, drilldown chevron */}
      <div className="hidden md:block max-h-[320px] overflow-y-auto scrollbar -mx-1 px-1 rounded-xl border border-[var(--color-edify-border)] bg-white">
        <table className="w-full text-[11.5px]">
          <thead>
            <tr className="bg-gradient-to-r from-[var(--color-edify-soft)] to-[var(--color-edify-soft)]/40 text-[9.5px] uppercase tracking-wide text-slate-600">
              <th scope="col" className="text-left font-bold py-2 px-2">School</th>
              <th scope="col" className="text-left font-bold py-2 px-2">District · CCEO</th>
              <th scope="col" className="text-right font-bold py-2 px-2">SSA</th>
              <th scope="col" className="text-left font-bold py-2 px-2">Lowest Intervention</th>
              <th scope="col" className="text-right font-bold py-2 px-2">V</th>
              <th scope="col" className="text-right font-bold py-2 px-2">T</th>
              <th scope="col" className="text-left font-bold py-2 px-2">Package</th>
              <th scope="col" className="text-left font-bold py-2 px-2">Risk Reason</th>
              <th scope="col" className="py-2 px-2"><span className="sr-only">Open</span></th>
            </tr>
          </thead>
          <tbody>
            {list.map((s, idx) => {
              const last = idx === list.length - 1;
              const isCritical = s.packageStatus === "Critical Gap" || s.packageStatus === "Not Started";
              return (
                <tr
                  key={s.schoolId}
                  className={cn(
                    "transition-colors hover:bg-[var(--color-edify-soft)]/40",
                    !last && "border-b border-[#eef2f4]",
                    isCritical && "bg-rose-50/30",
                  )}
                >
                  <td className="py-2 px-2 font-bold leading-tight whitespace-nowrap">{s.schoolName}</td>
                  <td className="py-2 px-2 muted">
                    <span>{s.district}</span>
                    <span className="opacity-60"> · </span>
                    <span>{s.assignedCceoName}</span>
                  </td>
                  <td className={cn(
                    "py-2 px-2 text-right font-extrabold tabular",
                    s.latestVerifiedSsaAverage == null || s.latestVerifiedSsaAverage < 6
                      ? "text-rose-700"
                      : "text-amber-700",
                  )}>
                    {s.latestVerifiedSsaAverage?.toFixed(1) ?? "—"}
                  </td>
                  <td className="py-2 px-2 muted">{s.lowestIntervention ?? "—"}</td>
                  <td className="py-2 px-2 text-right tabular font-semibold">{s.visitsCompleted}/4</td>
                  <td className="py-2 px-2 text-right tabular font-semibold">{s.trainingsCompleted}/4</td>
                  <td className="py-2 px-2">
                    <StatusBadge tone={pkgTone[s.packageStatus]}>{s.packageStatus}</StatusBadge>
                  </td>
                  <td className="py-2 px-2 text-caption muted leading-snug">
                    {s.riskReasons.length === 0 ? "—" : s.riskReasons.join(" · ")}
                  </td>
                  <td className="py-2 px-2 text-right">
                    <ChevronRight size={14} className="text-[var(--color-edify-muted)] inline-block" />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <AlertOctagon size={12} className="text-rose-600" />
          <span className="font-bold">High risk:</span>
          <span className="muted">{critical} critical · {behind} behind schedule</span>
        </span>
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <Sparkles size={12} className="text-amber-500" />
          <span className="font-bold">Lift the floor:</span>
          <span className="muted">{zeroVisits + zeroTrain} schools sit at zero on visits or trainings — book a cluster visit this week.</span>
        </span>
      </div>
    </SectionCard>
  );
}

