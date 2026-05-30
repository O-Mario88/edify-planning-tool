"use client";

import Link from "next/link";
import { Layers, Briefcase } from "lucide-react";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import {
  type SpecialProject,
  type ProjectStatus,
} from "@/lib/special-projects-mock";

const statusTone: Record<ProjectStatus, "green" | "amber" | "red" | "blue" | "grey"> = {
  Planning:  "blue",
  Active:    "green",
  "At Risk": "amber",
  Completed: "grey",
  Delayed:   "red",
};

function shortDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" });
}

function impactMetricLabel(p: SpecialProject): string {
  switch (p.impactMeasurementType) {
    case "Schools":      return "Schools Reached";
    case "Teachers":     return "Teachers Impacted";
    case "Participants": return "Participants Reached";
    case "Sessions":     return "Sessions Completed";
  }
}

function healthDotColor(score: number): string {
  if (score >= 4.3) return "var(--color-success)";
  if (score >= 3.8) return "var(--color-edify-orange)";
  return "var(--color-danger)";
}

const typeBadge: Record<string, string> = {
  EdTech:        "bg-blue-100 text-[#1e40af]",
  SEL:           "bg-violet-100 text-violet-700",
  "Teacher Dev": "bg-green-100 text-[#166534]",
  ECE:           "bg-orange-100 text-[#9a3412]",
};

export function ProjectPortfolioTable({ projects }: { projects: SpecialProject[] }) {
  return (
    <SectionCard
      icon={<Briefcase size={13} />}
      title="Project Portfolio"
    >
      <div className="overflow-x-auto scrollbar -mx-1 px-1">
        <table className="w-full dtable">
          <thead>
            <tr>
              <th scope="col" className="text-left">Project Name</th>
              <th scope="col" className="text-left">Project Type</th>
              <th scope="col" className="text-left">Assigned Partner</th>
              <th scope="col" className="text-right">Schools Enrolled</th>
              <th scope="col" className="text-right">Teachers Impacted</th>
              <th scope="col" className="text-left">Start Date</th>
              <th scope="col" className="text-left">End Date</th>
              <th scope="col" className="text-left">Status</th>
              <th scope="col" className="text-left">Health</th>
              <th scope="col" className="text-left">Impact Metric</th>
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => {
              const typeChip = typeBadge[p.projectType] ?? "bg-[#eef2f4] text-[#475467]";
              return (
                <tr key={p.projectId} className="hover:bg-[var(--color-edify-soft)]/40">
                  <td>
                    <div className="flex items-center gap-2">
                      <span className="w-6 h-6 rounded-md grid place-items-center bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
                        <Layers size={12} />
                      </span>
                      <Link
                        href={`/projects/${p.projectId}`}
                        className="text-body font-semibold whitespace-nowrap hover:text-[var(--color-edify-primary)] hover:underline"
                      >
                        {p.projectName}
                      </Link>
                    </div>
                  </td>
                  <td>
                    <span className={`inline-flex items-center px-2 py-[2px] rounded-md text-[11px] font-semibold ${typeChip}`}>
                      {p.projectType}
                    </span>
                  </td>
                  <td className="text-[12px] muted">{p.assignedPartnerName ?? "—"}</td>
                  <td className="text-right tabular text-body font-semibold">
                    {p.schoolsEnrolled?.toLocaleString() ?? "—"}
                  </td>
                  <td className="text-right tabular text-body">
                    {p.teachersImpacted?.toLocaleString() ?? "—"}
                  </td>
                  <td className="text-[12px] muted whitespace-nowrap">{shortDate(p.startDate)}</td>
                  <td className="text-[12px] muted whitespace-nowrap">{shortDate(p.endDate)}</td>
                  <td>
                    <StatusBadge tone={statusTone[p.status]}>{p.status}</StatusBadge>
                  </td>
                  <td>
                    <span className="inline-flex items-center gap-1.5">
                      <span
                        className="w-2 h-2 rounded-full inline-block"
                        style={{ background: healthDotColor(p.healthScore) }}
                      />
                      <span className="text-[12px] font-bold tabular">
                        {p.healthScore.toFixed(1)}
                      </span>
                    </span>
                  </td>
                  <td className="text-[12px] muted whitespace-nowrap">{impactMetricLabel(p)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] flex items-center justify-between text-[12px]">
        <div className="muted">
          Showing 1 to {projects.length} of{" "}
          <span className="font-semibold text-[var(--color-edify-text)]">{projects.length}</span>{" "}
          projects
        </div>
        <a href="/special-projects" className="font-semibold text-[var(--color-edify-primary)]">
          View All projects →
        </a>
      </div>
    </SectionCard>
  );
}
