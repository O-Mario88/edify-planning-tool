"use client";

import { AlertTriangle } from "lucide-react";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import { priorityDirectorSchools, type DirectorPriorityRow } from "@/lib/director-mock";

const riskTone = (r: DirectorPriorityRow["risk"]) =>
  r === "High" ? "red" : r === "Medium" ? "amber" : "grey";

export function PrioritySchoolsUrgentAttentionCard() {
  return (
    <SectionCard
      icon={<AlertTriangle size={13} />}
      title="Priority Schools Needing Urgent Attention"
      subtitle="SSA performance leads. Inactivity, no-visit, and no-training are secondary tie-breakers."
      actions={
        <a className="text-[12px] font-semibold text-[var(--color-edify-primary)]" href="#priority-schools">
          View All priority schools →
        </a>
      }
    >
      {/* Mobile card list — each school becomes a card with the
          5 columns from the table laid out vertically. */}
      <ul className="md:hidden flex flex-col gap-2">
        {priorityDirectorSchools.map((s) => (
          <li key={s.id} className="rounded-xl border border-[var(--color-edify-border)] bg-white px-3 py-2.5 flex flex-col gap-1.5">
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <div className="text-body font-extrabold text-slate-900 truncate">{s.school}</div>
                <div className="text-caption muted">{s.region} · SSA {s.ssaScore}%</div>
              </div>
              <StatusBadge tone={riskTone(s.risk)}>{s.risk}</StatusBadge>
            </div>
            <div className="flex flex-wrap gap-1">
              {s.issues.map((i) => (
                <span
                  key={i}
                  className={`chip ${
                    i === "SSA Weakness" ? "chip-red" : i === "No Visit" ? "chip-amber" : "chip-grey"
                  }`}
                >
                  {i}
                </span>
              ))}
            </div>
            <div className="flex justify-end">
              <button
                type="button"
                className={`btn btn-sm ${s.action === "Inspect" ? "btn-primary" : ""}`}
              >
                {s.action}
              </button>
            </div>
          </li>
        ))}
      </ul>

      <div className="hidden md:block overflow-x-auto -mx-1 px-1">
        <table className="w-full dtable">
          <thead>
            <tr>
              <th scope="col" className="text-left">School</th>
              <th scope="col" className="text-left">Region</th>
              <th scope="col" className="text-left">Key Issues</th>
              <th scope="col" className="text-left">Risk</th>
              <th scope="col" className="text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {priorityDirectorSchools.map((s) => (
              <tr key={s.id}>
                <td>
                  <div className="text-body font-semibold whitespace-nowrap">{s.school}</div>
                  <div className="text-caption muted">SSA Score: {s.ssaScore}%</div>
                </td>
                <td className="text-[12px] muted">{s.region}</td>
                <td className="text-[12px]">
                  <div className="flex flex-wrap gap-1">
                    {s.issues.map((i) => (
                      <span
                        key={i}
                        className={`chip ${
                          i === "SSA Weakness" ? "chip-red" : i === "No Visit" ? "chip-amber" : "chip-grey"
                        }`}
                      >
                        {i}
                      </span>
                    ))}
                  </div>
                </td>
                <td>
                  <StatusBadge tone={riskTone(s.risk)}>{s.risk}</StatusBadge>
                </td>
                <td className="text-right">
                  <button
                    type="button"
                    className={`btn btn-sm ${s.action === "Inspect" ? "btn-primary" : ""}`}
                  >
                    {s.action}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}
