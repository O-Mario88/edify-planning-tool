import { cn } from "@/lib/utils";
import type { PeriodPaceStatus } from "@/lib/pace-status";

// Targets by Time Period — the cumulative FY schedule, against the staff's
// portfolio (which INCLUDES schools delivered by partners — partner work counts
// toward the owner's targets; ownership never moves).
//
// FY runs Oct→Sep. Cumulative expectation by the END of each quarter:
//   Q1 (Oct–Dec) 25% · Q2 (Jan–Mar) 50% / Mid-Year · Q3 (Apr–Jun) 75% ·
//   Q4 (Jul–Sep) 100%.

type QuarterId = "Q1" | "Q2" | "Q3" | "Q4";

const QUARTERS: { id: QuarterId; months: string; pct: number; midYear?: boolean }[] = [
  { id: "Q1", months: "Oct – Dec", pct: 0.25 },
  { id: "Q2", months: "Jan – Mar", pct: 0.5, midYear: true },
  { id: "Q3", months: "Apr – Jun", pct: 0.75 },
  { id: "Q4", months: "Jul – Sep", pct: 1.0 },
];

const PACE_TONE: Record<PeriodPaceStatus, { text: string; bg: string }> = {
  "Ahead":           { text: "text-emerald-700", bg: "bg-emerald-100" },
  "On Track":        { text: "text-emerald-700", bg: "bg-emerald-100" },
  "Slightly Behind": { text: "text-amber-700",   bg: "bg-amber-100" },
  "Behind":          { text: "text-amber-800",   bg: "bg-amber-100" },
  "Critical":        { text: "text-rose-700",    bg: "bg-rose-100" },
};

export function TargetsByTimePeriodCard({
  fyLabel,
  fyTarget,
  achieved,
  partnerSupported,
  currentQuarter,
  expectedCumulative,
  paceStatus,
}: {
  fyLabel: string;
  fyTarget: number;
  achieved: number;
  partnerSupported: number;
  currentQuarter: QuarterId;
  expectedCumulative: number;
  paceStatus: PeriodPaceStatus;
}) {
  const achievedPct = fyTarget > 0 ? Math.min(100, Math.round((achieved / fyTarget) * 100)) : 0;
  const expectedPct = fyTarget > 0 ? Math.min(100, Math.round((expectedCumulative / fyTarget) * 100)) : 0;
  const tone = PACE_TONE[paceStatus];

  return (
    <section className="card p-3.5">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <h2 className="text-[12.5px] font-extrabold tracking-tight">Targets by Time Period</h2>
          <p className="text-[11px] muted mt-0.5">
            Cumulative against your {fyTarget} portfolio school{fyTarget === 1 ? "" : "s"} · {fyLabel}
          </p>
        </div>
        <span className={cn("inline-flex items-center px-2 py-[3px] rounded-md text-[11px] font-extrabold shrink-0", tone.bg, tone.text)}>
          {paceStatus}
        </span>
      </div>

      {/* Cumulative progress vs the expected line for the current quarter. */}
      <div className="mt-3">
        <div className="flex items-baseline justify-between gap-2 text-[11.5px]">
          <span className="font-semibold">
            Supported <span className="tabular font-extrabold text-[var(--color-edify-text)]">{achieved}</span> of {fyTarget}
          </span>
          <span className="muted">
            Expected {expectedCumulative} by end of {currentQuarter} ({Math.round(QUARTERS.find((q) => q.id === currentQuarter)!.pct * 100)}%)
          </span>
        </div>
        <div className="relative mt-1.5 h-2 rounded-full bg-[var(--color-edify-soft)]/70 overflow-hidden">
          <div className="h-full rounded-full bg-[var(--color-edify-primary)] transition-[width] duration-500" style={{ width: `${achievedPct}%` }} />
          {/* expected-cumulative marker */}
          <span className="absolute top-1/2 -translate-y-1/2 w-0.5 h-3 bg-[var(--color-edify-text)]/70 rounded" style={{ left: `calc(${expectedPct}% - 1px)` }} aria-hidden />
        </div>
      </div>

      {/* Quarter ladder. */}
      <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2">
        {QUARTERS.map((q) => {
          const expected = Math.round(fyTarget * q.pct);
          const isCurrent = q.id === currentQuarter;
          const reached = achieved >= expected;
          return (
            <div
              key={q.id}
              className={cn(
                "rounded-lg border p-2.5",
                isCurrent
                  ? "border-[var(--color-edify-primary)]/50 bg-[var(--color-edify-soft)]/50"
                  : "border-[var(--color-edify-divider)]",
              )}
            >
              <div className="flex items-center justify-between gap-1">
                <span className="text-[12px] font-extrabold tracking-tight">{q.id}</span>
                <span className={cn("text-[10px] font-extrabold tabular", reached ? "text-emerald-600" : "muted")}>
                  {Math.round(q.pct * 100)}%
                </span>
              </div>
              <div className="text-[10px] muted">{q.months}</div>
              <div className="mt-1 text-[13px] font-extrabold tabular leading-none">{expected}</div>
              <div className="mt-0.5 flex items-center gap-1 flex-wrap">
                <span className="text-[9.5px] muted">schools</span>
                {q.midYear && (
                  <span className="text-[9px] font-extrabold uppercase tracking-wide px-1 rounded bg-violet-100 text-violet-700">Mid-year</span>
                )}
                {isCurrent && (
                  <span className="text-[9px] font-extrabold uppercase tracking-wide px-1 rounded bg-[var(--color-edify-primary)]/15 text-[var(--color-edify-primary)]">Now</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <p className="mt-3 text-[10.5px] muted leading-relaxed">
        Includes {partnerSupported} school{partnerSupported === 1 ? "" : "s"} delivered by partners — partner-supported
        schools stay in your portfolio and count toward your targets. Ownership never transfers.
      </p>
    </section>
  );
}
