// Project Impact Comparison — the third layer of intelligence made visible:
// for each project, did the SSA intervention it targets actually move, and
// did project schools outperform comparable non-project schools?
//
// Server component (no client state) — reads the impact engines directly.

import Link from "next/link";
import { TrendingUp, TrendingDown, Minus, LineChart } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import type { SpecialProject } from "@/lib/special-projects-mock";
import { computeProjectImpact, projectVsNonProject } from "@/lib/projects/project-impact";

function fmtDelta(n: number): string {
  return `${n > 0 ? "+" : ""}${n.toFixed(1)}`;
}

function DeltaPill({ value }: { value: number }) {
  const tone =
    value > 0 ? "bg-emerald-50 text-emerald-700"
    : value < 0 ? "bg-rose-50 text-rose-700"
    : "bg-slate-100 text-slate-500";
  const Icon = value > 0 ? TrendingUp : value < 0 ? TrendingDown : Minus;
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[11px] font-extrabold tabular ${tone}`}>
      <Icon size={11} /> {fmtDelta(value)}
    </span>
  );
}

export function ProjectImpactComparisonCard({ projects }: { projects: SpecialProject[] }) {
  const rows = projects
    .map((p) => {
      const impact = computeProjectImpact(p.projectId);
      const comparison = projectVsNonProject(p.projectId);
      return impact && impact.schoolsWithSsa > 0 ? { p, impact, comparison } : null;
    })
    .filter((r): r is NonNullable<typeof r> => Boolean(r));

  return (
    <SectionCard
      icon={<LineChart size={13} />}
      title="Project Impact vs. SSA Intervention"
      subtitle="Did the mapped intervention move for project schools — and did they outperform comparable non-project schools?"
    >
      {rows.length === 0 ? (
        <p className="text-[12px] muted py-6 text-center">
          No project has enough school SSA data yet. Assign schools and complete a follow-up SSA to measure impact.
        </p>
      ) : (
        <div className="overflow-x-auto scrollbar -mx-1 px-1">
          <table className="w-full dtable">
            <thead>
              <tr>
                <th scope="col" className="text-left">Project</th>
                <th scope="col" className="text-left">Mapped Intervention</th>
                <th scope="col" className="text-right">Schools</th>
                <th scope="col" className="text-right">Before → After</th>
                <th scope="col" className="text-right">Project Δ</th>
                <th scope="col" className="text-right">Non-Project Δ</th>
                <th scope="col" className="text-right">Improved</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ p, impact, comparison }) => (
                <tr key={p.projectId} className="hover:bg-[var(--color-edify-soft)]/40">
                  <td>
                    <Link
                      href={`/projects/${p.projectId}`}
                      className="text-body font-semibold whitespace-nowrap hover:text-[var(--color-edify-primary)] hover:underline"
                    >
                      {p.projectShortName}
                    </Link>
                  </td>
                  <td>
                    <span className="inline-flex items-center px-2 py-[2px] rounded-md text-[11px] font-semibold bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] whitespace-nowrap">
                      {impact.intervention}
                    </span>
                  </td>
                  <td className="text-right tabular text-body">{impact.schoolsWithSsa}</td>
                  <td className="text-right tabular text-[12px] muted whitespace-nowrap">
                    {impact.avgBefore.toFixed(1)} → <span className="font-bold text-[var(--color-edify-text)]">{impact.avgAfter.toFixed(1)}</span>
                  </td>
                  <td className="text-right"><DeltaPill value={impact.avgImprovement} /></td>
                  <td className="text-right">
                    {comparison ? <DeltaPill value={comparison.nonProject.avgImprovement} /> : <span className="muted text-[11px]">—</span>}
                  </td>
                  <td className="text-right tabular text-[12px]">
                    <span className="font-bold text-emerald-700">{impact.schoolsImproved}</span>
                    <span className="muted">/{impact.schoolsWithSsa}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}
