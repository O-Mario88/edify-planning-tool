"use client";

import Link from "next/link";
import {
  AlertOctagon,
  AlertTriangle,
  Building2,
  ChevronRight,
  Info,
} from "lucide-react";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import {
  urgentInterventionSchools,
  type UrgentInterventionSchool,
} from "@/lib/ssa-mock";
import { cn } from "@/lib/utils";

const riskTone: Record<UrgentInterventionSchool["riskStatus"], "red" | "amber"> = {
  Critical: "red",
  High:     "red",
  Medium:   "amber",
};

const riskEdge: Record<UrgentInterventionSchool["riskStatus"], string> = {
  Critical: "border-l-rose-500 bg-rose-50/30",
  High:     "border-l-rose-500",
  Medium:   "border-l-amber-500",
};

export function UrgentInterventionSchoolsCard() {
  return (
    <SectionCard
      icon={<AlertTriangle size={13} className="text-[var(--color-danger)]" />}
      title="Schools Requiring Urgent Attention"
      actions={
        <div className="flex items-center gap-2">
          <Info size={13} className="text-[var(--color-edify-muted)]" />
          <Link
            className="text-[12px] font-semibold text-[var(--color-edify-primary)]"
            href="/schools"
          >
            View All
          </Link>
        </div>
      }
    >
      {/* Mobile-stacked row cards. Color-coded left edge by risk;
          rank avatar; school + district; lowest score as a bold rose
          number on the right; lowest intervention + recommended action
          on stacked lines below; risk pill at the bottom. */}
      <div className="md:hidden space-y-2">
        {urgentInterventionSchools.map((s) => {
          const Icon = s.riskStatus === "Critical" ? AlertOctagon : AlertTriangle;
          return (
            <div
              key={s.school}
              className={cn(
                "rounded-xl border border-[var(--color-edify-border)] border-l-[3px] bg-white p-3 space-y-2",
                riskEdge[s.riskStatus],
              )}
            >
              <div className="flex items-start gap-2.5">
                <div className="w-7 h-7 rounded-full bg-gradient-to-br from-rose-500 to-rose-700 text-white text-caption font-extrabold grid place-items-center shrink-0 shadow-sm">
                  {s.rank}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-bold leading-tight truncate text-slate-900">
                    {s.school}
                  </div>
                  <div className="text-caption muted leading-tight inline-flex items-center gap-1 mt-0.5">
                    <Building2 size={10} />
                    {s.district}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[18px] font-extrabold tabular leading-none text-rose-700">
                    {s.lowestScore.toFixed(1)}
                  </div>
                  <div className="text-[9.5px] muted font-bold uppercase tracking-wide mt-0.5">
                    Lowest
                  </div>
                </div>
              </div>

              <div className="text-caption leading-snug">
                <div className="inline-flex items-start gap-1.5 text-slate-700">
                  <Icon size={11} className={s.riskStatus === "Medium" ? "text-amber-600 mt-[1px] shrink-0" : "text-rose-600 mt-[1px] shrink-0"} />
                  <span>
                    <span className="muted font-semibold">Weakest:</span>{" "}
                    <span className="font-semibold">{s.lowestIntervention}</span>
                  </span>
                </div>
                <div className="muted mt-1 leading-snug">
                  <span className="font-semibold">Action:</span> {s.recommendedAction}
                </div>
              </div>

              <div className="flex items-center justify-between gap-2">
                <StatusBadge tone={riskTone[s.riskStatus]}>{s.riskStatus}</StatusBadge>
                <Link
                  href={`/schools`}
                  className="inline-flex items-center gap-0.5 text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline"
                >
                  Open
                  <ChevronRight size={11} />
                </Link>
              </div>
            </div>
          );
        })}
      </div>

      {/* Desktop table — gradient header, hover rows, drilldown chevron. */}
      <div className="hidden md:block overflow-x-auto -mx-1 px-1 rounded-xl border border-[var(--color-edify-border)] bg-white">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="bg-gradient-to-r from-[var(--color-edify-soft)] to-[var(--color-edify-soft)]/40 text-[9.5px] uppercase tracking-wide text-slate-600">
              <th scope="col" className="text-left font-bold py-2 px-2">#</th>
              <th scope="col" className="text-left font-bold py-2 px-2">School</th>
              <th scope="col" className="text-left font-bold py-2 px-2">District</th>
              <th scope="col" className="text-left font-bold py-2 px-2">Lowest Intervention</th>
              <th scope="col" className="text-right font-bold py-2 px-2">Lowest Score</th>
              <th scope="col" className="text-left font-bold py-2 px-2">Recommended Action</th>
              <th scope="col" className="text-left font-bold py-2 px-2">Risk</th>
              <th scope="col" className="py-2 px-2"><span className="sr-only">Open</span></th>
            </tr>
          </thead>
          <tbody>
            {urgentInterventionSchools.map((s, idx) => {
              const last = idx === urgentInterventionSchools.length - 1;
              const isCritical = s.riskStatus === "Critical";
              return (
                <tr
                  key={s.school}
                  className={cn(
                    "transition-colors hover:bg-[var(--color-edify-soft)]/40",
                    !last && "border-b border-[#eef2f4]",
                    isCritical && "bg-rose-50/30",
                  )}
                >
                  <td className="py-2 px-2 font-extrabold tabular">{s.rank}</td>
                  <td className="py-2 px-2 font-semibold whitespace-nowrap">{s.school}</td>
                  <td className="py-2 px-2 muted">{s.district}</td>
                  <td className="py-2 px-2 muted">{s.lowestIntervention}</td>
                  <td className="py-2 px-2 text-right tabular text-[13px] font-extrabold text-rose-700">
                    {s.lowestScore.toFixed(1)}
                  </td>
                  <td className="py-2 px-2 muted">{s.recommendedAction}</td>
                  <td className="py-2 px-2">
                    <StatusBadge tone={riskTone[s.riskStatus]}>{s.riskStatus}</StatusBadge>
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

      <div className="mt-3 text-[11px] muted">
        Showing 1 to {urgentInterventionSchools.length} of 112 schools
      </div>
    </SectionCard>
  );
}
