import Link from "next/link";
import { ArrowUpRight, Grid3x3, MapPin, TrendingDown } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { getCurrentUser } from "@/lib/auth";
import { fetchSsaPerformanceGrouped } from "@/lib/api/surfaces";
import { InsufficientData } from "@/components/ui/InsufficientData";

// Backend-driven SSA heatmap (district × the 8 interventions), scoped to the
// caller. Replaces the old client mock (which shipped Zambian district names in
// production). Every cell is a real average from the backend's grouped SSA
// surface — the same data the /ssa and /analytics district panels use.

function cellTone(score: number | null): { bg: string; text: string } {
  if (score == null) return { bg: "#f1f5f9", text: "#94a3b8" }; // slate — no data
  if (score >= 8.0) return { bg: "#10b981", text: "#ffffff" };
  if (score >= 7.5) return { bg: "#34d399", text: "#0f3a2c" };
  if (score >= 7.0) return { bg: "#a7f3d0", text: "#065f46" };
  if (score >= 6.5) return { bg: "#fef3c7", text: "#92400e" };
  if (score >= 6.0) return { bg: "#fde68a", text: "#78350f" };
  return { bg: "#fecaca", text: "#991b1b" };
}

const fmt = (n: number | null) => (n == null ? "—" : n.toFixed(1));

export async function CoreSsaHeatmapLive() {
  const user = await getCurrentUser();
  const res = await fetchSsaPerformanceGrouped(user, { groupBy: "district", schoolType: "all" });
  if (!res.live) return <InsufficientData surface="the SSA heatmap" />;

  const { interventions, rows } = res.data;
  // Districts with at least one assessed school, strongest first.
  const ranked = [...rows]
    .filter((r) => r.schoolsAssessed > 0)
    .sort((a, b) => (b.overallAverage ?? -1) - (a.overallAverage ?? -1));

  if (ranked.length === 0) {
    return (
      <SectionCard id="needs-attention" icon={<Grid3x3 size={13} />} title="Core SSA Heatmap" subtitle="District × intervention SSA performance">
        <div className="py-8 text-center text-[12px] muted">
          No SSA scores in your scope yet. The heatmap populates once schools in your
          districts have a completed current-FY SSA.
        </div>
      </SectionCard>
    );
  }

  const best = ranked[0];
  const worst = ranked[ranked.length - 1];
  // Weakest intervention column averaged across the ranked districts.
  const colAvg = interventions.map((c) => {
    const vals = ranked.map((r) => r.interventions[c.code]).filter((v): v is number => v != null);
    return { code: c.code, label: c.label, avg: vals.length ? +(vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(1) : null };
  });
  const scored = colAvg.filter((c) => c.avg != null) as { code: string; label: string; avg: number }[];
  const weakest = scored.length ? scored.reduce((w, c) => (c.avg < w.avg ? c : w)) : null;
  const strongest = scored.length ? scored.reduce((s, c) => (c.avg > s.avg ? c : s)) : null;

  const headline =
    `${best.groupName} leads at ${fmt(best.overallAverage)} — ${worst.groupName} trails at ${fmt(worst.overallAverage)}.` +
    (weakest ? ` ${weakest.label} is the weakest column (${weakest.avg}).` : "");

  return (
    <SectionCard
      id="needs-attention"
      icon={<Grid3x3 size={13} />}
      title="Core SSA Heatmap"
      subtitle={headline}
      actions={
        <Link href="/ssa" className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap">
          View SSA <ArrowUpRight size={11} />
        </Link>
      }
    >
      <div className="overflow-x-auto -mx-1 sm:-mx-2 rounded-lg">
        <table className="w-full border-separate border-spacing-x-0.5 sm:border-spacing-x-1 border-spacing-y-1 px-1 sm:px-2">
          <thead>
            <tr>
              <th scope="col" className="text-left text-[9px] sm:text-[10px] muted font-bold uppercase tracking-wide pb-1.5">District</th>
              {interventions.map((c) => (
                <th key={c.code} className="text-center text-[9px] sm:text-[9.5px] muted font-bold leading-tight pb-1.5" title={c.label}>
                  <span className="sm:hidden">{c.label.split(" ").map((w) => w[0]).join("").slice(0, 2)}</span>
                  <span className="hidden sm:inline">{c.label.length > 12 ? c.label.slice(0, 11) + "…" : c.label}</span>
                </th>
              ))}
              <th scope="col" className="text-center text-[9px] sm:text-[9.5px] muted font-bold uppercase tracking-wide pb-1.5">Avg</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((row) => (
              <tr key={row.groupId}>
                <td className="text-[10px] sm:text-[11.5px] font-semibold whitespace-nowrap pr-1 sm:pr-2">{row.groupName}</td>
                {interventions.map((c) => {
                  const score = row.interventions[c.code];
                  const tone = cellTone(score);
                  return (
                    <td key={c.code} className="text-center">
                      <span className="inline-block w-full min-w-0 sm:min-w-[44px] py-1 sm:py-1.5 rounded sm:rounded-md text-[10px] sm:text-[11px] font-extrabold tabular" style={{ backgroundColor: tone.bg, color: tone.text }}>
                        {fmt(score)}
                      </span>
                    </td>
                  );
                })}
                <td className="text-center">
                  <span className="inline-block w-full min-w-0 sm:min-w-[44px] py-1 sm:py-1.5 rounded sm:rounded-md text-[10px] sm:text-[11px] font-extrabold tabular ring-1 ring-black/5" style={{ backgroundColor: cellTone(row.overallAverage).bg, color: cellTone(row.overallAverage).text }}>
                    {fmt(row.overallAverage)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(strongest || weakest) && (
        <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] flex flex-wrap items-center gap-x-4 gap-y-1.5">
          {strongest && (
            <span className="inline-flex items-center gap-1.5 text-slate-700">
              <MapPin size={12} className="text-emerald-600" />
              <span className="font-bold">Top district:</span>
              <span className="muted">{best.groupName} ({fmt(best.overallAverage)}) · {strongest.label} ({strongest.avg}) leads</span>
            </span>
          )}
          {weakest && (
            <span className="inline-flex items-center gap-1.5 text-slate-700">
              <TrendingDown size={12} className="text-rose-600" />
              <span className="font-bold">Push next:</span>
              <span className="muted">{weakest.label} ({weakest.avg}) — weakest column</span>
            </span>
          )}
        </div>
      )}
    </SectionCard>
  );
}
