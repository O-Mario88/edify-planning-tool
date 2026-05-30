"use client";

import Link from "next/link";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { interventionYoy } from "@/lib/core-schools-mock";
import { cn } from "@/lib/utils";

function deltaTone(change: number) {
  if (change > 0) return "text-emerald-700";
  if (change < 0) return "text-rose-700";
  return "text-[var(--color-edify-muted)]";
}

export function CoreSsaPerformanceCard() {
  // Editorial computations — surface the strongest mover and the
  // weakest dimension so the subtitle answers "what changed?" not
  // "here is a table."
  const sortedByChange = [...interventionYoy].sort((a, b) => b.change - a.change);
  const biggestMover = sortedByChange[0];
  const sortedByCurrent = [...interventionYoy].sort((a, b) => b.current - a.current);
  const strongest = sortedByCurrent[0];
  const weakest   = sortedByCurrent[sortedByCurrent.length - 1];
  const avgChange = +(
    interventionYoy.reduce((a, r) => a + r.change, 0) / interventionYoy.length
  ).toFixed(2);
  const positive = avgChange >= 0;

  const headline = `${strongest.intervention} leads at ${strongest.current.toFixed(1)} · ${weakest.intervention} trails at ${weakest.current.toFixed(1)}. Cohort moved ${positive ? "+" : ""}${avgChange} avg vs prior FY.`;

  return (
    <SectionCard
      icon={<Activity size={13} />}
      title="Yearly Core Performance"
      subtitle={headline}
      actions={
        <Link
          href="/ssa"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View All
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      {/* Premium YoY table — gradient header, hover row, and a true
          trend cell rendering prior→current as two dots connected by
          a tone-colored chord so the eye reads the delta direction
          instantly. */}
      <div className="overflow-x-auto -mx-1 px-1 rounded-xl border border-[var(--color-edify-border)] bg-white">
        <table className="w-full text-[11.5px]">
          <thead>
            <tr className="bg-gradient-to-r from-[var(--color-edify-soft)] to-[var(--color-edify-soft)]/40 text-[9.5px] uppercase tracking-wide text-slate-600">
              <th scope="col" className="text-left font-bold py-2.5 px-3">Intervention</th>
              <th scope="col" className="text-right font-bold py-2.5 px-2">FY 23/24</th>
              <th scope="col" className="text-right font-bold py-2.5 px-2">FY 24/25</th>
              <th scope="col" className="text-right font-bold py-2.5 px-2">Δ</th>
              <th scope="col" className="text-left font-bold py-2.5 px-3 min-w-[140px]">Trend</th>
            </tr>
          </thead>
          <tbody>
            {interventionYoy.map((r, idx) => {
              const last = idx === interventionYoy.length - 1;
              const up = r.change > 0;
              const Arrow = up ? ArrowUpRight : r.change < 0 ? ArrowDownRight : ArrowUpRight;
              return (
                <tr
                  key={r.intervention}
                  className={cn("transition-colors hover:bg-[var(--color-edify-soft)]/40", !last && "border-b border-[#eef2f4]")}
                >
                  <td className="py-2 px-3 font-semibold text-slate-900">{r.intervention}</td>
                  <td className="py-2 px-2 text-right tabular muted">{r.prior.toFixed(1)}</td>
                  <td className="py-2 px-2 text-right tabular font-bold">{r.current.toFixed(1)}</td>
                  <td className={cn("py-2 px-2 text-right tabular font-extrabold inline-flex items-center justify-end gap-0.5 w-full", deltaTone(r.change))}>
                    <Arrow size={11} />
                    {up ? "+" : ""}{r.change.toFixed(1)}
                  </td>
                  <td className="py-2 px-3">
                    <TrendDots prior={r.prior} current={r.current} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <TrendingUp size={12} className="text-emerald-600" />
          <span className="font-bold">Biggest mover:</span>
          <span className="muted">{biggestMover.intervention} (+{biggestMover.change.toFixed(1)})</span>
        </span>
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <TrendingDown size={12} className="text-rose-600" />
          <span className="font-bold">Push next:</span>
          <span className="muted">{weakest.intervention} ({weakest.current.toFixed(1)}) · still the lowest dimension</span>
        </span>
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <Sparkles size={12} className="text-amber-500" />
          <span className="font-bold">Cohort:</span>
          <span className="muted">improving across all 8 interventions</span>
        </span>
      </div>
    </SectionCard>
  );
}

// ───────────── TrendDots — prior → current as a 2-point spark ─────────────

function TrendDots({ prior, current }: { prior: number; current: number }) {
  // Two dots on a 0-10 scale with a chord between them. Direction
  // (up vs down) drives the chord color so the trend reads at a
  // glance without a chart library.
  const max = 10;
  const priorPct   = Math.min(100, Math.max(0, (prior / max) * 100));
  const currentPct = Math.min(100, Math.max(0, (current / max) * 100));
  const up = current >= prior;
  const lineColor = up ? "#10b981" : "#ef4444";
  const startPct = Math.min(priorPct, currentPct);
  const endPct   = Math.max(priorPct, currentPct);

  return (
    <div className="relative h-3 w-full" role="img" aria-label={`Prior ${prior.toFixed(1)} → Current ${current.toFixed(1)}`}>
      {/* Track */}
      <div className="absolute inset-y-1/2 -translate-y-1/2 left-0 right-0 h-px bg-[#eef2f4]" />
      {/* Chord */}
      <div
        className="absolute inset-y-1/2 -translate-y-1/2 h-[2px] rounded-full"
        style={{
          left:  `${startPct}%`,
          width: `${Math.max(endPct - startPct, 0)}%`,
          backgroundColor: lineColor,
        }}
      />
      {/* Prior dot */}
      <span
        className="absolute top-1/2 -translate-y-1/2 w-2 h-2 rounded-full bg-slate-300 ring-1 ring-white"
        style={{ left: `calc(${priorPct}% - 4px)` }}
        title={`Prior FY: ${prior.toFixed(1)}`}
      />
      {/* Current dot */}
      <span
        className="absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full ring-2 ring-white"
        style={{
          left: `calc(${currentPct}% - 5px)`,
          backgroundColor: lineColor,
        }}
        title={`Current FY: ${current.toFixed(1)}`}
      />
    </div>
  );
}
