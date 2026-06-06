"use client";

// SsaPerformanceDrawer — answers a single question for the CCEO / PL /
// IA / CD: "How is this school performing on the SSA interventions,
// and is it improving compared to previous operational years?"
//
// The drawer adapts based on how many completed SSAs the school has:
//
//   0 SSAs          → "Schedule SSA" empty state (planning locked)
//   1 SSA           → horizontal bar chart of current intervention scores
//   2 SSAs          → grouped bar chart current vs last FY + change badges
//   3+ SSAs         → three-year grouped bars + trend summary
//
// Charts are inline SVG so the drawer doesn't pull in a chart library
// for what is effectively static, low-density bar marks.

import { useMemo } from "react";
import { formatHumanDate } from "@/lib/format-utils";
import {
  BookOpen, CalendarCheck, ChevronRight, TrendingUp, TrendingDown, Minus,
  AlertTriangle, Lock, Sparkles, GraduationCap, Footprints, RotateCw,
  Award, type LucideIcon,
} from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import type { SchoolGap, SchoolGapAction, SsaInterventionArea } from "@/lib/planning/planning-gaps-mock";
import {
  historyFor,
  snapshotFor,
  compareSsa,
  compareSsaThreeYear,
  recommendActions,
  statusFor,
  type SsaPerformanceRecord,
  type SsaStatus,
  type SsaTrend,
  type SsaComparisonRow,
} from "@/lib/planning/ssa-performance-mock";

// ────────── Performance tone ──────────

const STATUS_TONE: Record<SsaStatus, { bg: string; text: string; ring: string; bar: string }> = {
  "Critical":      { bg: "bg-rose-50",    text: "text-rose-700",    ring: "ring-rose-200",    bar: "fill-rose-500"    },
  "Needs Support": { bg: "bg-amber-50",   text: "text-amber-700",   ring: "ring-amber-200",   bar: "fill-amber-500"   },
  "Good":          { bg: "bg-emerald-50", text: "text-emerald-700", ring: "ring-emerald-200", bar: "fill-emerald-500" },
  "Strong":        { bg: "bg-emerald-100",text: "text-emerald-800", ring: "ring-emerald-300", bar: "fill-emerald-700" },
};

const TREND_TONE: Record<SsaTrend, { bg: string; text: string; Icon: LucideIcon; label: string }> = {
  strong_improvement: { bg: "bg-emerald-100", text: "text-emerald-800", Icon: TrendingUp,   label: "Strong improvement" },
  small_improvement:  { bg: "bg-emerald-50",  text: "text-emerald-700", Icon: TrendingUp,   label: "Small improvement"  },
  no_change:          { bg: "bg-slate-100",   text: "text-slate-600",   Icon: Minus,        label: "No change"          },
  decline:            { bg: "bg-orange-50",   text: "text-orange-700",  Icon: TrendingDown, label: "Decline"            },
  serious_decline:    { bg: "bg-rose-50",     text: "text-rose-700",    Icon: TrendingDown, label: "Serious decline"    },
};

const RECOMMENDED_ICON: Record<string, LucideIcon> = {
  schedule_ssa:           CalendarCheck,
  schedule_support_visit: Footprints,
  schedule_training:      GraduationCap,
  schedule_coaching:      RotateCw,
};

// ────────── Types ──────────

export type SsaPerformanceContext = {
  /** The school whose history to render. Comes from the planning
   *  surface that opened the drawer. */
  school: SchoolGap;
  /** Current operational cycle label, e.g. "FY2027". The drawer uses
   *  it to label the empty state when only historical SSA exists. */
  currentCycle?: string;
};

// ────────── Component ──────────

export function SsaPerformanceDrawer({
  open, context, onClose, onAction,
}: {
  open: boolean;
  context: SsaPerformanceContext | null;
  onClose: () => void;
  /** Wired so the recommended-action CTAs route back through the
   *  parent's normal action handler (Schedule SSA → owner picker,
   *  Schedule Training → activity drawer, etc.). */
  onAction?: (action: SchoolGapAction, school: SchoolGap) => void;
}) {
  const school   = context?.school ?? null;
  const history  = useMemo(() => (school ? historyFor(school.id) : []), [school]);
  const current  = history[0];
  const previous = history[1];

  // No context yet — render nothing rather than an empty Modal
  // (Modal primitive requires children). The parent gates `open` on
  // context presence, so this branch only runs in the brief frame
  // between context becoming null and the drawer closing.
  if (!context || !school) return null;

  const currentCycle = context.currentCycle ?? "FY2027"; // matches mock cycle anchor

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="SSA Performance"
      description="View completed SSA results, yearly comparison, and intervention improvement trends."
      variant="drawer-right"
      size="lg"
      footer={
        <div className="flex items-center justify-end gap-2 w-full">
          <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
        </div>
      }
    >
      <div className="space-y-5">

        {/* 1. School summary */}
        <SchoolSummary school={school} currentCycle={currentCycle} current={current} />

        {/* 2. Empty states OR full body */}
        {history.length === 0 ? (
          <EmptyStateNoSsa onAction={onAction ? () => onAction("schedule_ssa", school) : undefined} />
        ) : !isCurrentCycle(current, currentCycle) ? (
          <EmptyStateHistoricalOnly
            previous={current}
            onAction={onAction ? () => onAction("schedule_ssa", school) : undefined}
          />
        ) : (
          <SsaBody
            history={history}
            current={current}
            previous={previous}
            school={school}
            onAction={onAction}
          />
        )}
      </div>
    </Modal>
  );
}

// ────────── School summary card ──────────

function SchoolSummary({
  school, currentCycle, current,
}: {
  school: SchoolGap;
  currentCycle: string;
  current?: SsaPerformanceRecord;
}) {
  return (
    <section className="rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 p-3.5">
      <div className="flex items-start gap-3">
        <span className="grid place-items-center h-10 w-10 rounded-lg bg-white text-[var(--color-edify-primary)] shrink-0 border border-[var(--color-edify-border)]">
          <BookOpen size={16} />
        </span>
        <div className="min-w-0">
          <h3 className="text-body-lg font-extrabold tracking-tight">{school.schoolName}</h3>
          <div className="text-[11.5px] muted mt-0.5 leading-tight">
            {school.district}
            {school.subCounty && <> · {school.subCounty}</>}
            {school.parish    && <> · {school.parish}</>}
          </div>
          <div className="text-[11px] muted mt-1.5 inline-flex items-center gap-3 flex-wrap">
            <span>Current operational cycle: <span className="font-extrabold text-[var(--color-edify-text)]">{currentCycle}</span></span>
            {current && (
              <>
                <span className="opacity-40">|</span>
                <span>Latest SSA: <span className="font-extrabold text-[var(--color-edify-text)] tabular">{formatHumanDate(current.ssaDate)}</span></span>
              </>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

// ────────── Full SSA body — snapshot, charts, lists, recs, history ──────────

function SsaBody({
  history, current, previous, school, onAction,
}: {
  history: SsaPerformanceRecord[];
  current: SsaPerformanceRecord;
  previous?: SsaPerformanceRecord;
  school: SchoolGap;
  onAction?: (action: SchoolGapAction, school: SchoolGap) => void;
}) {
  const snap = snapshotFor(current);
  const recs = recommendActions(school, history);

  // Comparison rows pick the right shape based on history length —
  // single record renders as bar chart only (no change badges), 2
  // records get last-vs-current, 3+ records get the three-year view.
  const comparisonRows = useMemo<SsaComparisonRow[]>(() => {
    if (history.length >= 3) return compareSsaThreeYear(history);
    return compareSsa(current, previous);
  }, [history, current, previous]);

  return (
    <>
      {/* 2. Latest SSA snapshot — 4 KPI cards */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        <SnapshotCard label="Average score" value={`${current.averageScore.toFixed(1)}/10`} tone={STATUS_TONE[current.status]} />
        <SnapshotCard label="Weakest"       value={`${snap.weakest.score}/10`} sub={snap.weakest.intervention}  tone={STATUS_TONE[statusFor(snap.weakest.score)]} />
        <SnapshotCard label="Best"          value={`${snap.best.score}/10`}    sub={snap.best.intervention}     tone={STATUS_TONE[statusFor(snap.best.score)]} />
        <SnapshotCard label="Status"        value={current.status}              tone={STATUS_TONE[current.status]} />
      </section>

      {/* 3-4. Performance / comparison / trend graph */}
      <section className="rounded-xl border border-[var(--color-edify-divider)] bg-white p-3.5">
        <header className="flex items-center justify-between mb-2.5">
          <div>
            <h4 className="text-[13px] font-extrabold tracking-tight">
              {history.length >= 3 ? "SSA trend — last 3 operational years"
                : history.length === 2 ? "SSA comparison — current vs last FY"
                : "Current SSA performance"}
            </h4>
            <p className="text-[11px] muted mt-0.5">
              {history.length >= 3 ? `${history[2].operationalCycle} → ${history[0].operationalCycle}, per intervention`
                : history.length === 2 ? `${previous!.operationalCycle} vs ${current.operationalCycle}, per intervention`
                : "Per-intervention score · ranked weakest first"}
            </p>
          </div>
          <Legend variant={history.length >= 3 ? "threeYear" : history.length === 2 ? "twoYear" : "oneYear"} />
        </header>

        {history.length === 1 && <BarChartSingle rows={comparisonRows} />}
        {history.length === 2 && <BarChartTwoYear rows={comparisonRows} currentLabel={current.operationalCycle} previousLabel={previous!.operationalCycle} />}
        {history.length >= 3 && (
          <BarChartThreeYear
            rows={comparisonRows}
            yearLabels={[history[2].operationalCycle, history[1].operationalCycle, history[0].operationalCycle]}
          />
        )}
      </section>

      {/* 5+6. Priority + strength interventions */}
      <section className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <InterventionList
          title="Priority interventions"
          subtitle="Bottom-ranked — feed planning"
          icon={AlertTriangle}
          tone="warn"
          items={snap.priorityAreas.map((s) => ({ area: s.intervention, score: s.score }))}
        />
        <InterventionList
          title="Strength areas"
          subtitle="Top-ranked — celebrate"
          icon={Award}
          tone="good"
          items={snap.strengthAreas.map((s) => ({ area: s.intervention, score: s.score }))}
        />
      </section>

      {/* 7. Improvement summary (only when we have a baseline) */}
      {comparisonRows.some((r) => r.change !== undefined) && (
        <ImprovementSummary rows={comparisonRows} />
      )}

      {/* 8. Recommended planning actions */}
      <section className="rounded-xl border border-[var(--color-edify-divider)] bg-white p-3.5">
        <header className="mb-2">
          <h4 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <Sparkles size={13} className="text-[var(--color-edify-primary)]" />
            Recommended planning actions
          </h4>
          <p className="text-[11px] muted mt-0.5">From the latest SSA, ordered by impact.</p>
        </header>
        <ul className="space-y-2">
          {recs.map((r, i) => {
            const Icon = r.action ? RECOMMENDED_ICON[r.action] : ChevronRight;
            return (
              <li key={i} className="flex items-start gap-2.5 rounded-lg border border-[var(--color-edify-divider)] px-3 py-2.5">
                <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0 mt-0.5">
                  <Icon size={12} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[12px] font-extrabold tracking-tight text-[var(--color-edify-text)]">{r.title}</p>
                  <p className="text-[11px] muted leading-snug mt-0.5">{r.reason}</p>
                </div>
                {r.action && onAction && r.action !== "schedule_coaching" && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => onAction(r.action!, school)}
                    className="shrink-0"
                  >
                    Open
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      {/* 9. SSA history */}
      <section className="rounded-xl border border-[var(--color-edify-divider)] bg-white p-3.5">
        <header className="mb-2">
          <h4 className="text-[13px] font-extrabold tracking-tight">SSA history</h4>
          <p className="text-[11px] muted mt-0.5">Traceability of completed SSAs.</p>
        </header>
        <div className="overflow-x-auto -mx-3.5">
          <table className="w-full text-[11.5px]">
            <thead>
              <tr className="text-left text-caption uppercase tracking-wider font-bold text-[var(--color-edify-muted)] border-b border-[var(--color-edify-divider)]">
                <th className="px-3.5 py-1.5">FY</th>
                <th className="px-3.5 py-1.5">SSA date</th>
                <th className="px-3.5 py-1.5 text-right">Avg score</th>
                <th className="px-3.5 py-1.5">Status</th>
                <th className="px-3.5 py-1.5">Completed by</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {history.map((h) => {
                const tone = STATUS_TONE[h.status];
                return (
                  <tr key={h.id}>
                    <td className="px-3.5 py-2 font-extrabold tabular text-[var(--color-edify-text)]">{h.operationalCycle}</td>
                    <td className="px-3.5 py-2 tabular muted">{formatHumanDate(h.ssaDate)}</td>
                    <td className="px-3.5 py-2 text-right tabular font-extrabold text-[var(--color-edify-text)]">{h.averageScore.toFixed(1)}</td>
                    <td className="px-3.5 py-2">
                      <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-wider", tone.bg, tone.text)}>
                        {h.status}
                      </span>
                    </td>
                    <td className="px-3.5 py-2 muted">{h.completedBy} <span className="opacity-50">({h.completedByRole})</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

// ────────── Snapshot card ──────────

function SnapshotCard({
  label, value, sub, tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone: { bg: string; text: string; ring: string };
}) {
  return (
    <div className={cn("rounded-lg border border-[var(--color-edify-divider)] bg-white p-2.5 ring-1", tone.ring)}>
      <div className="text-[10px] uppercase tracking-wider font-bold muted">{label}</div>
      <div className={cn("text-[16px] font-extrabold tabular mt-0.5", tone.text)}>{value}</div>
      {sub && <div className="text-caption muted leading-tight mt-0.5 truncate" title={sub}>{sub}</div>}
    </div>
  );
}

// ────────── Bar charts ──────────

const CHART_ROW_H        = 28;
const CHART_LABEL_W_PCT  = 38;     // % of width devoted to intervention labels
const SCORE_MAX          = 10;

function BarChartSingle({ rows }: { rows: SsaComparisonRow[] }) {
  const sorted = [...rows].sort((a, b) => a.currentScore - b.currentScore);
  return (
    <div className="space-y-1.5">
      {sorted.map((r) => {
        const tone = STATUS_TONE[statusFor(r.currentScore)];
        return (
          <div key={r.intervention} className="grid grid-cols-12 items-center gap-2 text-[11.5px]">
            <div className="col-span-5 truncate" title={r.intervention}>{r.intervention}</div>
            <div className="col-span-6 relative h-5 rounded bg-[var(--color-edify-soft)]/60 overflow-hidden">
              <div
                className={cn("absolute inset-y-0 left-0 rounded", barFillFor(r.currentScore))}
                style={{ width: `${(r.currentScore / SCORE_MAX) * 100}%` }}
              />
            </div>
            <div className={cn("col-span-1 text-right tabular font-extrabold", tone.text)}>{r.currentScore}</div>
          </div>
        );
      })}
    </div>
  );
}

function BarChartTwoYear({
  rows, currentLabel, previousLabel,
}: {
  rows: SsaComparisonRow[];
  currentLabel: string;
  previousLabel: string;
}) {
  const sorted = [...rows].sort((a, b) => a.currentScore - b.currentScore);
  return (
    <div className="space-y-2.5">
      {sorted.map((r) => {
        const trendTone = r.trend ? TREND_TONE[r.trend] : null;
        return (
          <div key={r.intervention} className="text-[11.5px]">
            <div className="flex items-center justify-between mb-1">
              <span className="font-extrabold truncate" title={r.intervention}>{r.intervention}</span>
              {r.change !== undefined && trendTone && (
                <span className={cn("inline-flex items-center px-1.5 py-[1px] rounded-md text-[10px] font-extrabold gap-1 tabular", trendTone.bg, trendTone.text)}>
                  <trendTone.Icon size={9} />
                  {r.change > 0 ? "+" : ""}{r.change}
                </span>
              )}
            </div>
            {/* Previous bar */}
            {r.previousScore !== undefined && (
              <div className="grid grid-cols-12 items-center gap-2 mb-1">
                <span className="col-span-2 text-[10px] uppercase tracking-wider font-bold muted tabular">{previousLabel}</span>
                <div className="col-span-9 relative h-3.5 rounded bg-[var(--color-edify-soft)]/60 overflow-hidden">
                  <div className={cn("absolute inset-y-0 left-0 rounded opacity-50", barFillFor(r.previousScore))} style={{ width: `${(r.previousScore / SCORE_MAX) * 100}%` }} />
                </div>
                <span className="col-span-1 text-right tabular muted">{r.previousScore}</span>
              </div>
            )}
            {/* Current bar */}
            <div className="grid grid-cols-12 items-center gap-2">
              <span className="col-span-2 text-[10px] uppercase tracking-wider font-bold muted tabular">{currentLabel}</span>
              <div className="col-span-9 relative h-3.5 rounded bg-[var(--color-edify-soft)]/60 overflow-hidden">
                <div className={cn("absolute inset-y-0 left-0 rounded", barFillFor(r.currentScore))} style={{ width: `${(r.currentScore / SCORE_MAX) * 100}%` }} />
              </div>
              <span className="col-span-1 text-right tabular font-extrabold text-[var(--color-edify-text)]">{r.currentScore}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function BarChartThreeYear({
  rows, yearLabels,
}: {
  rows: SsaComparisonRow[];
  yearLabels: [string, string, string]; // oldest → newest
}) {
  // Sort by current (newest) score, weakest first.
  const sorted = [...rows].sort((a, b) => a.currentScore - b.currentScore);
  return (
    <div className="space-y-3">
      {sorted.map((r) => {
        const series = r.threeYearScores ?? [];
        const trendTone = r.trend ? TREND_TONE[r.trend] : null;
        return (
          <div key={r.intervention} className="text-[11.5px]">
            <div className="flex items-center justify-between mb-1.5">
              <span className="font-extrabold truncate" title={r.intervention}>{r.intervention}</span>
              {r.change !== undefined && trendTone && (
                <span className={cn("inline-flex items-center px-1.5 py-[1px] rounded-md text-[10px] font-extrabold gap-1 tabular", trendTone.bg, trendTone.text)}>
                  <trendTone.Icon size={9} />
                  {r.change > 0 ? "+" : ""}{r.change}
                </span>
              )}
            </div>
            <div className="grid grid-cols-12 gap-1.5">
              {yearLabels.map((year, idx) => {
                const point = series.find((p) => p.year === year);
                const isCurrent = idx === yearLabels.length - 1;
                return (
                  <div key={year} className="col-span-4">
                    <div className="text-[10px] uppercase tracking-wider font-bold muted tabular mb-0.5">{year}</div>
                    <div className="relative h-3.5 rounded bg-[var(--color-edify-soft)]/60 overflow-hidden">
                      {point && (
                        <div
                          className={cn("absolute inset-y-0 left-0 rounded", barFillFor(point.score), isCurrent ? "" : "opacity-60")}
                          style={{ width: `${(point.score / SCORE_MAX) * 100}%` }}
                        />
                      )}
                    </div>
                    <div className={cn("text-right tabular text-caption mt-0.5", isCurrent ? "font-extrabold text-[var(--color-edify-text)]" : "muted")}>
                      {point ? `${point.score}/10` : "—"}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Legend({ variant }: { variant: "oneYear" | "twoYear" | "threeYear" }) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap justify-end text-[10px]">
      {variant !== "oneYear" && (
        <span className="inline-flex items-center gap-1 muted">
          <span className="h-2 w-2 rounded-sm bg-slate-300" /> Previous
        </span>
      )}
      <span className="inline-flex items-center gap-1 muted">
        <span className="h-2 w-2 rounded-sm bg-emerald-500" /> Strong
      </span>
      <span className="inline-flex items-center gap-1 muted">
        <span className="h-2 w-2 rounded-sm bg-amber-500" /> Needs support
      </span>
      <span className="inline-flex items-center gap-1 muted">
        <span className="h-2 w-2 rounded-sm bg-rose-500" /> Critical
      </span>
    </div>
  );
}

function barFillFor(score: number): string {
  if (score <= 4) return "bg-rose-500";
  if (score <= 6) return "bg-amber-500";
  if (score <= 8) return "bg-emerald-500";
  return "bg-emerald-700";
}

// ────────── Intervention lists ──────────

function InterventionList({
  title, subtitle, icon: Icon, tone, items,
}: {
  title: string;
  subtitle: string;
  icon: LucideIcon;
  tone: "warn" | "good";
  items: { area: SsaInterventionArea; score: number }[];
}) {
  const headerTone =
    tone === "warn"
      ? { bg: "bg-amber-50",  text: "text-amber-700",  ring: "ring-amber-200" }
      : { bg: "bg-emerald-50", text: "text-emerald-700", ring: "ring-emerald-200" };
  return (
    <section className={cn("rounded-xl border border-[var(--color-edify-divider)] bg-white p-3.5 ring-1", headerTone.ring)}>
      <header className="flex items-start gap-2 mb-2">
        <span className={cn("grid place-items-center h-7 w-7 rounded-md shrink-0", headerTone.bg, headerTone.text)}>
          <Icon size={12} />
        </span>
        <div className="min-w-0">
          <h4 className="text-[13px] font-extrabold tracking-tight">{title}</h4>
          <p className="text-[11px] muted mt-0.5">{subtitle}</p>
        </div>
      </header>
      <ol className="space-y-1">
        {items.map((it, i) => {
          const t = STATUS_TONE[statusFor(it.score)];
          return (
            <li key={it.area} className="flex items-center gap-2 text-[11.5px]">
              <span className="text-[10px] muted tabular w-3.5">{i + 1}.</span>
              <span className="flex-1 truncate" title={it.area}>{it.area}</span>
              <span className={cn("inline-flex items-center px-1.5 py-[1px] rounded-md text-caption font-extrabold tabular", t.bg, t.text)}>
                {it.score}/10
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

// ────────── Improvement summary ──────────

function ImprovementSummary({ rows }: { rows: SsaComparisonRow[] }) {
  const sortedAsc = [...rows].filter((r) => r.change !== undefined).sort((a, b) => (a.change ?? 0) - (b.change ?? 0));
  const biggestDecline     = sortedAsc[0];
  const biggestImprovement = sortedAsc[sortedAsc.length - 1];
  const declined           = sortedAsc.filter((r) => (r.change ?? 0) < 0).length;
  const improved           = sortedAsc.filter((r) => (r.change ?? 0) > 0).length;
  const flat               = sortedAsc.filter((r) => (r.change ?? 0) === 0).length;

  return (
    <section className="rounded-xl border border-[var(--color-edify-divider)] bg-white p-3.5">
      <header className="mb-2">
        <h4 className="text-[13px] font-extrabold tracking-tight">Improvement summary</h4>
        <p className="text-[11px] muted mt-0.5">Year-over-year change across the {rows.length} interventions.</p>
      </header>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {biggestImprovement && (biggestImprovement.change ?? 0) > 0 && (
          <HighlightLine
            tone="good"
            icon={TrendingUp}
            label="Biggest improvement"
            value={`${biggestImprovement.intervention} +${biggestImprovement.change}`}
            sub={`${biggestImprovement.previousScore}/10 → ${biggestImprovement.currentScore}/10`}
          />
        )}
        {biggestDecline && (biggestDecline.change ?? 0) < 0 && (
          <HighlightLine
            tone="warn"
            icon={TrendingDown}
            label="Biggest decline"
            value={`${biggestDecline.intervention} ${biggestDecline.change}`}
            sub={`${biggestDecline.previousScore}/10 → ${biggestDecline.currentScore}/10`}
          />
        )}
      </div>
      <div className="text-[11px] muted mt-2 inline-flex items-center gap-3 flex-wrap">
        <span><span className="font-extrabold text-emerald-700">{improved}</span> improving</span>
        <span><span className="font-extrabold text-slate-600">{flat}</span> stable</span>
        <span><span className="font-extrabold text-rose-700">{declined}</span> declining</span>
      </div>
    </section>
  );
}

function HighlightLine({
  tone, icon: Icon, label, value, sub,
}: {
  tone: "good" | "warn";
  icon: LucideIcon;
  label: string;
  value: string;
  sub: string;
}) {
  const t = tone === "good"
    ? { bg: "bg-emerald-50", text: "text-emerald-700" }
    : { bg: "bg-orange-50",  text: "text-orange-700"  };
  return (
    <div className="rounded-lg border border-[var(--color-edify-divider)] px-3 py-2 flex items-start gap-2">
      <span className={cn("grid place-items-center h-7 w-7 rounded-md shrink-0", t.bg, t.text)}>
        <Icon size={12} />
      </span>
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-wider font-bold muted">{label}</div>
        <div className={cn("text-[12px] font-extrabold tracking-tight mt-0.5 truncate", t.text)} title={value}>{value}</div>
        <div className="text-caption muted tabular">{sub}</div>
      </div>
    </div>
  );
}

// ────────── Empty states ──────────

function EmptyStateNoSsa({ onAction }: { onAction?: () => void }) {
  return (
    <section className="rounded-xl border border-rose-200 bg-rose-50/40 p-4 text-center">
      <span className="inline-grid place-items-center h-9 w-9 rounded-md bg-rose-100 text-rose-700 mb-2">
        <Lock size={14} />
      </span>
      <h4 className="text-[13px] font-extrabold tracking-tight">No completed SSA found</h4>
      <p className="text-[11.5px] muted mt-1 max-w-md mx-auto leading-snug">
        Planning remains locked because all intervention-based activities depend on
        SSA recommendations. Schedule the SSA to unlock visits and trainings.
      </p>
      {onAction && (
        <div className="mt-3">
          <Button size="sm" onClick={onAction} Icon={CalendarCheck}>Schedule SSA</Button>
        </div>
      )}
    </section>
  );
}

function EmptyStateHistoricalOnly({
  previous, onAction,
}: {
  previous: SsaPerformanceRecord;
  onAction?: () => void;
}) {
  const snap = snapshotFor(previous);
  return (
    <>
      <section className="rounded-xl border border-amber-200 bg-amber-50/50 p-4">
        <div className="flex items-start gap-2.5">
          <span className="grid place-items-center h-9 w-9 rounded-md bg-amber-100 text-amber-700 shrink-0">
            <AlertTriangle size={14} />
          </span>
          <div className="min-w-0">
            <h4 className="text-[13px] font-extrabold tracking-tight">Historical SSA found, but current-cycle SSA is missing</h4>
            <p className="text-[11.5px] muted mt-1 leading-snug">
              Planning remains locked until the current-cycle SSA is completed.
              The previous SSA ({previous.operationalCycle} · {formatHumanDate(previous.ssaDate)}) is shown below for reference only.
            </p>
            {onAction && (
              <div className="mt-2.5">
                <Button size="sm" onClick={onAction} Icon={CalendarCheck}>Complete current SSA</Button>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Read-only previous SSA snapshot + chart */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-2 opacity-90">
        <SnapshotCard label={`Avg score (${previous.operationalCycle})`} value={`${previous.averageScore.toFixed(1)}/10`} tone={STATUS_TONE[previous.status]} />
        <SnapshotCard label="Weakest" value={`${snap.weakest.score}/10`} sub={snap.weakest.intervention}  tone={STATUS_TONE[statusFor(snap.weakest.score)]} />
        <SnapshotCard label="Best"    value={`${snap.best.score}/10`}    sub={snap.best.intervention}     tone={STATUS_TONE[statusFor(snap.best.score)]} />
        <SnapshotCard label="Status"  value={previous.status}             tone={STATUS_TONE[previous.status]} />
      </section>
      <section className="rounded-xl border border-[var(--color-edify-divider)] bg-white p-3.5 opacity-90">
        <header className="mb-2">
          <h4 className="text-[13px] font-extrabold tracking-tight">Previous SSA performance · read-only</h4>
          <p className="text-[11px] muted mt-0.5">Last completed in {previous.operationalCycle}.</p>
        </header>
        <BarChartSingle rows={previous.scores.map((s) => ({
          intervention:  s.intervention,
          currentScore:  s.score,
          trend:         "no_change",
        }))} />
      </section>
    </>
  );
}

// ────────── Helpers ──────────


function isCurrentCycle(rec: SsaPerformanceRecord | undefined, currentCycle: string): boolean {
  if (!rec) return false;
  return rec.operationalCycle === currentCycle;
}

// Re-export the row constant to silence unused-vars when the bar
// charts switch to SVG renderers later.
export const __SSA_CHART_ROW_H = CHART_ROW_H;
export const __SSA_CHART_LABEL_W_PCT = CHART_LABEL_W_PCT;
