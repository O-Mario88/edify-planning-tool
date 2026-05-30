"use client";

// Weekly Totals Strip — premium design pass.
//
// Six cards: W1-W5 + Monthly. Each renders the currency-display
// primitive (UGX label + giant tabular figure) and a width-only emerald
// heat bar. The Monthly card uses the same shell as W1-W5 plus a 2px
// emerald left rail (.mfr-week-hero override in globals) — quiet
// distinction by structure, not gradient.

import { cn } from "@/lib/utils";

export type WeekSelection = 1 | 2 | 3 | 4 | 5 | null;

export function WeeklyTotalsStrip({
  weekTotals,
  monthlyTotal,
  selected,
  onSelectWeek,
}: {
  weekTotals: { w1: number; w2: number; w3: number; w4: number; w5: number };
  monthlyTotal: number;
  selected: WeekSelection;
  onSelectWeek?: (w: WeekSelection) => void;
}) {
  const cards: { week: 1 | 2 | 3 | 4 | 5; amount: number }[] = [
    { week: 1, amount: weekTotals.w1 },
    { week: 2, amount: weekTotals.w2 },
    { week: 3, amount: weekTotals.w3 },
    { week: 4, amount: weekTotals.w4 },
    { week: 5, amount: weekTotals.w5 },
  ];
  const maxWeek = Math.max(...cards.map((c) => c.amount));

  return (
    <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
      {cards.map(({ week, amount }) => {
        const pct = monthlyTotal > 0 ? (amount / monthlyTotal) * 100 : 0;
        const heat = maxWeek > 0 ? amount / maxWeek : 0;
        const isSelected = selected === week;
        const isEmpty = amount === 0;
        return (
          <button
            key={week}
            type="button"
            disabled={isEmpty}
            onClick={() => onSelectWeek?.(isSelected ? null : week)}
            aria-pressed={isSelected}
            className={cn(
              "card mfr-week-card text-left p-3.5 rounded-xl flex flex-col gap-2 transition-colors",
              isSelected && "row-active-glow border-transparent",
              isEmpty   && "opacity-50 cursor-default",
              !isEmpty && !isSelected && "cursor-pointer hover:bg-[var(--card-hover)]",
            )}
          >
            <div className="flex items-center justify-between gap-1">
              <div className="text-[9.5px] font-bold uppercase tracking-[0.1em] text-[var(--text-muted)]">
                Week {week}
              </div>
              <span className="text-[10px] font-semibold tabular text-[var(--text-muted)]">
                {pct.toFixed(0)}%
              </span>
            </div>
            <CompactMoney amount={amount} empty={isEmpty} />
            {!isEmpty && (
              <div className="mt-1 h-[2px] rounded-full bg-[var(--border-subtle)] overflow-hidden">
                <div
                  className="mfr-week-heat h-full"
                  style={{ width: `${Math.max(8, heat * 100)}%` }}
                />
              </div>
            )}
            {isEmpty && (
              <div className="text-[10px] text-[var(--text-muted)] italic">No allocation</div>
            )}
          </button>
        );
      })}

      {/* Monthly card — identical shell, emerald left rail */}
      <article className="card mfr-week-hero rounded-xl p-3.5 flex flex-col gap-2 lg:col-span-1">
        <div className="flex items-center justify-between gap-1">
          <div className="text-[9.5px] font-bold uppercase tracking-[0.1em] text-[var(--text-muted)]">
            Monthly
          </div>
          <span className="text-[10px] font-semibold text-emerald-700 dark:text-emerald-300 glass:text-emerald-300">
            Σ
          </span>
        </div>
        <CompactMoney amount={monthlyTotal} />
        <div className="text-[10px] text-[var(--text-muted)] mt-1">
          Across W1–W5
        </div>
      </article>
    </section>
  );
}

// CompactMoney — currency-display in display size. Uses the abbreviated
// form (M / k) for at-a-glance scanning, full digits available via title.
function CompactMoney({ amount, empty }: { amount: number; empty?: boolean }) {
  if (empty) {
    return (
      <div className="currency-display currency-display-md">
        <span className="currency-unit">UGX</span>
        <span className="currency-value text-[var(--text-disabled)]">0</span>
      </div>
    );
  }
  const compact = formatCompact(amount);
  return (
    <div
      className="currency-display currency-display-md"
      title={`UGX ${amount.toLocaleString()}`}
    >
      <span className="currency-unit">UGX</span>
      <span className="currency-value">{compact}</span>
    </div>
  );
}

function formatCompact(n: number): string {
  if (n >= 1_000_000) {
    const m = n / 1_000_000;
    return m >= 100 ? m.toFixed(0) + "M" : m.toFixed(1) + "M";
  }
  if (n >= 1_000) return (n / 1_000).toFixed(0) + "k";
  return n.toLocaleString();
}
