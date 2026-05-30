"use client";

import {
  categoryDisbursedTotal,
  categoryShares,
} from "@/lib/accountant-console-mock";

// ── Donut geometry ────────────────────────────────────────────────────
const SIZE = 176;
const CENTER = SIZE / 2;
const RADIUS = 66;
const THICKNESS = 22;
const CIRC = 2 * Math.PI * RADIUS;
const GAP = 4; // arc-length gap between segments (px)

// Disbursements by Category — refined donut + clean ranked legend.
//
// The donut is hand-drawn SVG (one stroked <circle> per category) so it
// renders deterministically with no chart-library measure timing.
//
// The legend is a divided list whose rows flex to fill the card height —
// so it stays organised whatever the card grows to. Every row uses the
// same fixed column grid (chip · name · amount · share) so the numbers
// line up in clean columns.
export function DisbursementsByCategory() {
  // Build one stroked-arc segment per category. Prefix-sum the cursor
  // via slice/reduce so the .map is pure — a `let cursor += arc`
  // inside .map() trips React Compiler's cannot-reassign rule.
  const arcs = categoryShares.map((s) => (s.pct / 100) * CIRC);
  const segments = categoryShares.map((s, i) => {
    const arc = arcs[i];
    const dash = Math.max(arc - GAP, 2);
    const startCursor = arcs.slice(0, i).reduce((a, b) => a + b, 0);
    const rotation = (startCursor / CIRC) * 360 - 90;
    return { color: s.color, dash, rotation };
  });

  return (
    <article className="card p-5 lg:p-6 flex flex-col h-full overflow-hidden">
      <header className="mb-2">
        <h3 className="text-[14.5px] font-extrabold tracking-tight text-slate-900 leading-tight">
          Disbursements by Category
        </h3>
        <p className="text-caption text-slate-500 font-semibold mt-0.5">
          This Month
        </p>
      </header>

      {/* Donut */}
      <div
        className="relative mx-auto shrink-0"
        style={{ width: SIZE, height: SIZE }}
      >
        <svg
          width={SIZE}
          height={SIZE}
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          className="block"
          aria-hidden
        >
          {/* Soft track ring */}
          <circle
            cx={CENTER}
            cy={CENTER}
            r={RADIUS}
            fill="none"
            stroke="#F1F5F8"
            strokeWidth={THICKNESS}
          />
          {/* Category segments */}
          {segments.map((seg, i) => (
            <circle
              key={i}
              cx={CENTER}
              cy={CENTER}
              r={RADIUS}
              fill="none"
              stroke={seg.color}
              strokeWidth={THICKNESS}
              strokeDasharray={`${seg.dash} ${CIRC - seg.dash}`}
              transform={`rotate(${seg.rotation} ${CENTER} ${CENTER})`}
            />
          ))}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none">
          <span className="text-[8.5px] text-slate-400 font-extrabold uppercase tracking-[0.14em]">
            Total Disbursed
          </span>
          <span className="text-[21px] xl:text-[22px] font-extrabold tabular leading-none num-hero glow-emerald text-slate-900 mt-1">
            {categoryDisbursedTotal}
          </span>
          <span className="text-[9px] text-slate-500 font-semibold mt-1">
            across {categoryShares.length} categories
          </span>
        </div>
      </div>

      {/* Ranked legend — rows flex to fill remaining card height */}
      <ul className="flex-1 flex flex-col mt-3 border-t border-[var(--color-edify-divider)]">
        {categoryShares.map((s, i) => (
          <li
            key={s.label}
            className={`flex-1 flex items-center gap-2 min-w-0 border-b border-[var(--color-edify-divider)] tile-in stagger-${
              (i % 6) + 1
            }`}
          >
            <span
              className="w-2.5 h-2.5 rounded-[3px] shrink-0"
              style={{ backgroundColor: s.color }}
            />
            <span className="flex-1 text-[11.5px] font-semibold text-slate-700 truncate">
              {s.label}
            </span>
            <span className="w-[66px] text-right text-[11.5px] font-extrabold tabular num-hero text-slate-900 shrink-0 whitespace-nowrap">
              {s.amount}
            </span>
            <span className="w-[30px] text-right text-caption font-extrabold tabular text-slate-400 shrink-0 whitespace-nowrap">
              {s.pct}%
            </span>
          </li>
        ))}
      </ul>

      <a
        href="#category-details"
        className="mt-3 self-start inline-flex items-center gap-1 text-[11.5px] font-extrabold text-sky-700 hover:text-sky-800"
      >
        View category details →
      </a>
    </article>
  );
}
