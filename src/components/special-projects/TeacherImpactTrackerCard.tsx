"use client";

import { TrendingUp, TrendingDown, GraduationCap } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  buildTeacherImpactTracker,
  teacherImpactTotals,
  type SpecialProject,
} from "@/lib/special-projects-mock";
import { cn } from "@/lib/utils";

// CRITICAL — only projects with impactMeasurementType = "Teachers" appear
// here. Schools-based projects must NOT be folded into this tracker.
export function TeacherImpactTrackerCard({ projects }: { projects: SpecialProject[] }) {
  const rows = buildTeacherImpactTracker(projects);
  const totals = teacherImpactTotals(rows);

  return (
    <SectionCard
      icon={<GraduationCap size={13} />}
      title="Teacher Impact Tracker"
      subtitle="(Projects measured by teachers impacted)"
      actions={
        <a className="text-[12px] font-semibold text-[var(--color-edify-primary)]" href="/analytics">
          View All
        </a>
      }
    >
      <table className="w-full dtable">
        <thead>
          <tr>
            <th scope="col" className="text-left">Project</th>
            <th scope="col" className="text-right">Teachers Target</th>
            <th scope="col" className="text-right">Teachers Reached</th>
            <th scope="col" className="text-right">Completion %</th>
            <th scope="col" className="text-right">Trend</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.projectId}>
              <td className="text-body font-semibold whitespace-nowrap">
                {r.projectShortName}
              </td>
              <td className="text-right tabular text-body font-semibold">
                {r.teachersTarget.toLocaleString()}
              </td>
              <td className="text-right tabular text-body">
                {r.teachersReached.toLocaleString()}
              </td>
              <td className="text-right">
                <span
                  className={cn(
                    "inline-flex items-center justify-center w-12 h-6 rounded-md text-[11.5px] font-bold tabular",
                    r.completionPct >= 75
                      ? "bg-green-100 text-[#166534]"
                      : "bg-orange-100 text-[#9a3412]",
                  )}
                >
                  {r.completionPct}%
                </span>
              </td>
              <td className="text-right">
                {r.trend === "up" ? (
                  <TrendingUp size={14} className="inline text-[var(--color-success)]" />
                ) : (
                  <TrendingDown size={14} className="inline text-[var(--color-danger)]" />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] grid grid-cols-3 text-center text-[12px]">
        <div>
          <div className="muted text-caption font-semibold">Total Target</div>
          <div className="text-[16px] font-extrabold tabular">
            {totals.totalTarget.toLocaleString()}
          </div>
        </div>
        <div>
          <div className="muted text-caption font-semibold">Total Reached</div>
          <div className="text-[16px] font-extrabold tabular">
            {totals.totalReached.toLocaleString()}
          </div>
        </div>
        <div>
          <div className="muted text-caption font-semibold">Overall Completion</div>
          <div className="text-[16px] font-extrabold tabular text-[var(--color-success)]">
            {totals.overallPct}%
          </div>
        </div>
      </div>
    </SectionCard>
  );
}
