"use client";

import Link from "next/link";
import { ArrowUpRight, Grid3x3, MapPin, TrendingDown } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { cceoHeatmap } from "@/lib/cceo-mock";

// Color ramp keyed to the SSA score (0–10).
// Lighter for lower scores, darker emerald for higher.
function cellTone(score: number): { bg: string; text: string } {
  if (score >= 8.0)  return { bg: "#10b981",  text: "#ffffff" }; // emerald-500
  if (score >= 7.5)  return { bg: "#34d399",  text: "#0f3a2c" }; // emerald-400
  if (score >= 7.0)  return { bg: "#a7f3d0",  text: "#065f46" }; // emerald-200
  if (score >= 6.5)  return { bg: "#fef3c7",  text: "#92400e" }; // amber-100
  if (score >= 6.0)  return { bg: "#fde68a",  text: "#78350f" }; // amber-200
  return                       { bg: "#fecaca",  text: "#991b1b" }; // rose-200
}

// The official 8 SSA interventions — display order matches the canonical list.
// Average is a SEPARATE column (below), never a replacement for an intervention.
const COLUMNS: { key: keyof (typeof cceoHeatmap)[number]["scores"]; label: string; short: string; abbr: string }[] = [
  { key: "christlike",  label: "Christ-like Behavior",        short: "Christ-like", abbr: "CB" },
  { key: "word",        label: "Exposure to the Word of God", short: "Word of God", abbr: "WG" },
  { key: "leadership",  label: "Leadership Best Practice",    short: "Leadership",  abbr: "LP" },
  { key: "teaching",    label: "Teaching Environment",        short: "Teaching",    abbr: "TE" },
  { key: "learning",    label: "Learning Environment",        short: "Learning",    abbr: "LE" },
  { key: "government",  label: "Government Requirements",      short: "Gov't Req.",  abbr: "GR" },
  { key: "fees",        label: "Fees / Budget / Accounts",    short: "Fees/Budget", abbr: "FB" },
  { key: "enrollment",  label: "Enrollment",                  short: "Enrollment",  abbr: "EN" },
];

// SSA average is computed from all 8 intervention scores (never a partial set).
function avgOf(scores: (typeof cceoHeatmap)[number]["scores"]): number {
  const vals = COLUMNS.map((c) => scores[c.key]);
  return +(vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(1);
}

export function CoreSsaHeatmapCard() {
  // Headline computations — pick the brightest + darkest cells in the
  // matrix, plus the weakest column averaged across districts.
  // Average is always derived from all 8 interventions, so the heatmap can never
  // drift from a stale partial average.
  const rows = cceoHeatmap.map((r) => ({ ...r, avg: avgOf(r.scores) }));
  const sortedByAvg = [...rows].sort((a, b) => b.avg - a.avg);
  const bestDistrict  = sortedByAvg[0];
  const worstDistrict = sortedByAvg[sortedByAvg.length - 1];

  const colAverages = COLUMNS.map((c) => {
    const sum = cceoHeatmap.reduce((a, r) => a + r.scores[c.key], 0);
    return { key: c.key, label: c.short, avg: +(sum / cceoHeatmap.length).toFixed(1) };
  });
  const weakestCol = colAverages.reduce((w, c) => (c.avg < w.avg ? c : w));
  const strongestCol = colAverages.reduce((s, c) => (c.avg > s.avg ? c : s));

  const headline = `${bestDistrict.district} leads at ${bestDistrict.avg.toFixed(1)} — ${worstDistrict.district} trails at ${worstDistrict.avg.toFixed(1)}. ${weakestCol.label} is the weakest column (${weakestCol.avg}).`;

  return (
    <SectionCard
      id="needs-attention"
      icon={<Grid3x3 size={13} />}
      title="Core SSA Heatmap"
      subtitle={headline}
      actions={
        <Link
          href="/map"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View Map
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      <div className="overflow-x-auto -mx-1 sm:-mx-2 rounded-lg">
        <table className="w-full border-separate border-spacing-x-0.5 sm:border-spacing-x-1 border-spacing-y-1 px-1 sm:px-2">
          <thead>
            <tr>
              <th scope="col" className="text-left text-[9px] sm:text-[10px] muted font-bold uppercase tracking-wide pb-1.5">
                District
              </th>
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  className="text-center text-[9px] sm:text-[9.5px] muted font-bold leading-tight pb-1.5"
                  title={c.label}
                >
                  {/* Abbreviated on phones so all 8 interventions fit; full label on ≥sm. */}
                  <span className="sm:hidden">{c.abbr}</span>
                  <span className="hidden sm:inline">{c.short}</span>
                </th>
              ))}
              <th scope="col" className="text-center text-[9px] sm:text-[9.5px] muted font-bold uppercase tracking-wide pb-1.5">
                Avg
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.district}>
                <td className="text-[10px] sm:text-[11.5px] font-semibold whitespace-nowrap pr-1 sm:pr-2">
                  {row.district}
                </td>
                {COLUMNS.map((c) => {
                  const score = row.scores[c.key];
                  const tone = cellTone(score);
                  return (
                    <td key={c.key} className="text-center">
                      <span
                        className="inline-block w-full min-w-0 sm:min-w-[44px] py-1 sm:py-1.5 rounded sm:rounded-md text-[10px] sm:text-[11px] font-extrabold tabular"
                        style={{ backgroundColor: tone.bg, color: tone.text }}
                      >
                        {score.toFixed(1)}
                      </span>
                    </td>
                  );
                })}
                <td className="text-center">
                  <span
                    className="inline-block w-full min-w-0 sm:min-w-[44px] py-1 sm:py-1.5 rounded sm:rounded-md text-[10px] sm:text-[11px] font-extrabold tabular ring-1 ring-black/5"
                    style={{
                      backgroundColor: cellTone(row.avg).bg,
                      color: cellTone(row.avg).text,
                    }}
                  >
                    {row.avg.toFixed(1)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <MapPin size={12} className="text-emerald-600" />
          <span className="font-bold">Top district:</span>
          <span className="muted">{bestDistrict.district} ({bestDistrict.avg.toFixed(1)}) · {strongestCol.label} ({strongestCol.avg}) leads the columns</span>
        </span>
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <TrendingDown size={12} className="text-rose-600" />
          <span className="font-bold">Push next:</span>
          <span className="muted">{weakestCol.label} ({weakestCol.avg}) — weakest in every district</span>
        </span>
      </div>
    </SectionCard>
  );
}
