"use client";

import { Activity } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  ssaIntelligence,
  ssaInterventionOrder,
  ssaInterventionFullName,
} from "@/lib/director-mock";
import { cn } from "@/lib/utils";

function scoreClass(v: number) {
  if (v >= 75) return "bg-green-100 text-[#166534]";
  if (v >= 65) return "bg-[#ecfeff] text-[#155e75]";
  if (v >= 55) return "bg-[#fef9c3] text-[#854d0e]";
  if (v >= 45) return "bg-orange-100 text-[#9a3412]";
  return "bg-red-100 text-red-700";
}

export function SchoolSsaIntelligenceCard() {
  return (
    <SectionCard
      icon={<Activity size={13} />}
      title="School & SSA Intelligence"
      subtitle="Cluster SSA Performance (8 Interventions). Hover any column header to see the full intervention name."
      actions={
        <a className="text-[12px] font-semibold text-[var(--color-edify-primary)]" href="#ssa-intelligence">
          View full SSA performance →
        </a>
      }
    >
      <div className="overflow-x-auto scrollbar -mx-1 px-1">
        <table className="w-full dtable">
          <thead>
            <tr className="bg-[var(--color-edify-soft)]/60">
              <th scope="col" className="text-left">Region</th>
              {ssaInterventionOrder.map((k) => (
                <th
                  key={k}
                  className="text-center"
                  title={ssaInterventionFullName[k]}
                >
                  {k}
                </th>
              ))}
              <th scope="col" className="text-center">Overall</th>
            </tr>
          </thead>
          <tbody>
            {ssaIntelligence.map((row) => (
              <tr key={row.region} className="hover:bg-[var(--color-edify-soft)]/40">
                <td className="text-body font-semibold whitespace-nowrap">{row.region}</td>
                {ssaInterventionOrder.map((k) => {
                  const v = row.scores[k];
                  return (
                    <td key={k} className="text-center">
                      <span
                        className={cn(
                          "inline-flex items-center justify-center w-12 h-7 rounded-md text-[11.5px] font-bold tabular",
                          scoreClass(v),
                        )}
                      >
                        {v}%
                      </span>
                    </td>
                  );
                })}
                <td className="text-center">
                  <span
                    className={cn(
                      "inline-flex items-center justify-center w-12 h-7 rounded-md text-[11.5px] font-extrabold tabular border",
                      scoreClass(row.overall),
                      "border-current/0",
                    )}
                  >
                    {row.overall}%
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11px] muted leading-snug">
        <span className="font-semibold text-[var(--color-edify-text)]">
          SSA performance leads school priority.
        </span>{" "}
        Inactivity and missing visits / trainings are tie-breakers when SSA scores are tied or unavailable.
      </div>
    </SectionCard>
  );
}
