"use client";

import { Activity, MapPin } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { interventionHeatmap, SSA_EIGHT } from "@/lib/ssa-mock";
import { cn } from "@/lib/utils";

// Short labels for narrow cell headers — keeps the heatmap dense
// without word-wrapping each column.
const SHORT_LABEL: Record<typeof SSA_EIGHT[number], string> = {
  "Christ-like Behavior":        "Christ-like",
  "Exposure to the Word of God": "Word",
  "Leadership Best Practice":    "Leadership",
  "Teaching Environment":        "Teaching",
  "Learning Environment":        "Learning",
  "Government Requirements":     "Govt",
  "Fees / Budget / Accounts":    "Fees",
  "Enrollment":                  "Enrollment",
};

function cellTone(score: number) {
  if (score >= 7.5) return "bg-emerald-100 text-emerald-800";
  if (score >= 6.0) return "bg-amber-100 text-amber-800";
  if (score >= 4.5) return "bg-orange-100 text-orange-800";
  return "bg-rose-100 text-rose-800";
}

function rowOverallTone(scores: number[]): { chip: string; ring: string } {
  const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
  if (avg >= 7.5) return { chip: "bg-emerald-100 text-emerald-800", ring: "ring-emerald-200" };
  if (avg >= 6.0) return { chip: "bg-amber-100   text-amber-800",   ring: "ring-amber-200"   };
  if (avg >= 4.5) return { chip: "bg-orange-100  text-orange-800",  ring: "ring-orange-200"  };
  return                  { chip: "bg-rose-100    text-rose-800",    ring: "ring-rose-200"    };
}

export function PriorityInterventionGapsCard() {
  return (
    <SectionCard
      icon={<Activity size={13} />}
      title="Priority Intervention Gaps by District"
      subtitle="Interventions (Average Score out of 10) — colored cells flag gaps; lower is worse."
    >
      {/* Mobile-stacked variant — one card per district, overall pill
          top-right, 4×2 mini-grid of the 8 intervention chips below. */}
      <div className="md:hidden space-y-2.5">
        {interventionHeatmap.map((row) => {
          const tone = rowOverallTone(row.scores);
          const avg = +(row.scores.reduce((a, b) => a + b, 0) / row.scores.length).toFixed(1);
          return (
            <div
              key={row.district}
              className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3 space-y-2.5"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-[13.5px] font-extrabold leading-tight text-slate-900 inline-flex items-center gap-1.5">
                    <MapPin size={11} className="text-[var(--color-edify-muted)]" />
                    {row.district}
                  </div>
                  <div className="text-caption muted font-semibold mt-0.5">
                    District average across all 8 interventions
                  </div>
                </div>
                <span
                  className={cn(
                    "inline-flex items-center justify-center min-w-[54px] h-8 px-2.5 rounded-lg text-body-lg font-extrabold tabular ring-1",
                    tone.chip,
                    tone.ring,
                  )}
                >
                  {avg.toFixed(1)}
                </span>
              </div>
              <div className="grid grid-cols-4 gap-1.5">
                {SSA_EIGHT.map((label, i) => {
                  const score = row.scores[i];
                  return (
                    <div
                      key={label}
                      title={label}
                      className="rounded-md bg-[var(--color-edify-soft)]/30 px-1.5 py-1.5 text-center"
                    >
                      <div className="text-[9px] font-bold uppercase tracking-tight text-slate-500 truncate">
                        {SHORT_LABEL[label]}
                      </div>
                      <div
                        className={cn(
                          "mt-0.5 inline-flex items-center justify-center min-w-[36px] h-6 px-1.5 rounded-md text-[11px] font-extrabold tabular",
                          cellTone(score),
                        )}
                      >
                        {score.toFixed(1)}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {/* Desktop heatmap table — dense matrix with short column labels. */}
      <div className="hidden md:block overflow-x-auto -mx-1 px-1">
        <table className="w-full">
          <thead>
            <tr>
              <th
                scope="col"
                className="text-left text-[10px] muted font-bold uppercase tracking-wide pl-1.5 pr-2 pb-1.5"
              >
                District
              </th>
              {SSA_EIGHT.map((label) => (
                <th
                  key={label}
                  className="px-1 pb-1.5 text-center text-[9.5px] muted font-bold align-bottom"
                  title={label}
                >
                  <span className="inline-block max-w-[72px] leading-tight">
                    {SHORT_LABEL[label]}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {interventionHeatmap.map((row) => (
              <tr key={row.district}>
                <td className="text-[12px] font-semibold pl-1.5 pr-2 py-1">{row.district}</td>
                {row.scores.map((s, i) => (
                  <td key={i} className="px-1 py-1">
                    <div
                      className={cn(
                        "h-9 rounded-md grid place-items-center text-[11.5px] font-bold tabular",
                        cellTone(s),
                      )}
                    >
                      {s.toFixed(1)}
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}
