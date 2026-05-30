"use client";

import Link from "next/link";
import { ArrowUpRight, CheckCircle2, Sparkles, Star } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { championPipeline } from "@/lib/cceo-mock";

// Build a stroke-based donut chart from the segment list.
function donutSegments(total: number) {
  const r = 36;
  const c = 2 * Math.PI * r;

  let cumulative = 0;
  return championPipeline.segments.map((seg) => {
    const length = (seg.count / total) * c;
    const offset = -cumulative;
    cumulative += length;
    return {
      ...seg,
      strokeDasharray: `${length} ${c - length}`,
      strokeDashoffset: offset,
      circumference: c,
      r,
    };
  });
}

export function ChampionSchoolPipelineCard() {
  const segs = donutSegments(championPipeline.total);
  const size = 160;

  // Headline: surface the most-actionable segment (Champion Review)
  // and the funnel shape.
  const review    = championPipeline.segments.find((s) => s.key === "review");
  const potential = championPipeline.segments.find((s) => s.key === "potential");
  const ineligible = championPipeline.segments.find((s) => s.key === "ineligible");

  const headline = `${championPipeline.total} schools in the pipeline · ${review?.count ?? 0} ready for Champion Review (${review?.pct ?? 0}%) · ${potential?.count ?? 0} on deck.`;

  return (
    <SectionCard
      id="champion-pipeline"
      icon={<Star size={13} className="text-yellow-500" />}
      title="Champion School Pipeline"
      subtitle={headline}
      actions={
        <Link
          href="/ssa/core-candidates"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View All
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      <div className="flex items-center gap-4 flex-wrap">
        {/* Donut */}
        <div className="relative shrink-0" style={{ width: size, height: size }}>
          <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size}>
            <circle cx={size / 2} cy={size / 2} r={36} fill="none" stroke="#eef2f4" strokeWidth={14} />
            {segs.map((s) => (
              <circle
                key={s.key}
                cx={size / 2}
                cy={size / 2}
                r={s.r}
                fill="none"
                stroke={s.color}
                strokeWidth={14}
                strokeDasharray={s.strokeDasharray}
                strokeDashoffset={s.strokeDashoffset}
                transform={`rotate(-90 ${size / 2} ${size / 2})`}
                strokeLinecap="butt"
              />
            ))}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
            <div className="text-[28px] font-extrabold tabular leading-none">
              {championPipeline.total}
            </div>
            <div className="text-caption muted mt-0.5">{championPipeline.totalLabel}</div>
          </div>
        </div>

        {/* Legend */}
        <ul className="flex-1 min-w-[180px] space-y-1.5 text-[11.5px]">
          {championPipeline.segments.map((s) => (
            <li key={s.key} className="flex items-center gap-2">
              <span
                className="w-2.5 h-2.5 rounded-sm shrink-0"
                style={{ backgroundColor: s.color }}
              />
              <span className="flex-1 truncate font-semibold">{s.label}</span>
              <span className="font-extrabold tabular shrink-0">{s.count}</span>
              <span className="muted tabular shrink-0 w-[40px] text-right">({s.pct}%)</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <CheckCircle2 size={12} className="text-emerald-600" />
          <span className="font-bold">Promote next:</span>
          <span className="muted">{review?.count ?? 0} schools ready — schedule formal Champion reviews this month</span>
        </span>
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <Sparkles size={12} className="text-amber-500" />
          <span className="font-bold">Build the bench:</span>
          <span className="muted">{potential?.count ?? 0} Potential Champions · {ineligible?.count ?? 0} not yet eligible</span>
        </span>
      </div>
    </SectionCard>
  );
}
