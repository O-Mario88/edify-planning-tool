"use client";

// Activity × Week summary view.
//
// The executive cash-flow lens on the Monthly Fund Request. Rows are
// the activity categories that carry value this month (StaffVisits,
// PartnerVisits, SSA, ClusterTraining, GroupTrainings, Meals, Transport,
// Accommodation, Admin); columns are W1-W5 + Monthly total. Bottom row
// rolls up the weekly totals.
//
// Each non-zero cell is clickable — drills into the source records
// that produced the number. Empty cells render as a muted dash so the
// eye skims to the cells that carry weight.

import {
  Bus,
  Calendar,
  CheckCircle2,
  GraduationCap,
  Hotel,
  Settings,
  School,
  Sparkles,
  Users,
  Utensils,
  type LucideIcon,
} from "lucide-react";
import type {
  ActivityWeekMatrix,
  ActivityWeekRow,
} from "@/lib/funds/mfr-activity-week";
import type { MfrActivityCategory } from "@/lib/funds/monthly-fund-request-types";
import type { MfrCellTarget } from "./MonthlyFundRequestMatrix";
import { cn } from "@/lib/utils";

const CATEGORY_ICON: Record<MfrActivityCategory, LucideIcon> = {
  StaffVisits:     School,
  PartnerVisits:   Users,
  SSA:             Calendar,
  ClusterTraining: GraduationCap,
  GroupTrainings:  GraduationCap,
  Meals:           Utensils,
  Transport:       Bus,
  Accommodation:   Hotel,
  Admin:           Settings,
};

const CATEGORY_TONE: Record<MfrActivityCategory, string> = {
  StaffVisits:     "mfr-cat-staff",
  PartnerVisits:   "mfr-cat-partner",
  SSA:             "mfr-cat-ssa",
  ClusterTraining: "mfr-cat-cluster",
  GroupTrainings:  "mfr-cat-group",
  Meals:           "mfr-cat-meals",
  Transport:       "mfr-cat-transport",
  Accommodation:   "mfr-cat-accommodation",
  Admin:           "mfr-cat-admin",
};

export function ActivityWeekSummary({
  matrix,
  selectedWeek,
  onCellClick,
}: {
  matrix: ActivityWeekMatrix;
  selectedWeek: 1 | 2 | 3 | 4 | 5 | null;
  onCellClick?: (target: MfrCellTarget) => void;
}) {
  // Filter columns when a week is pinned via the weekly strip — the
  // user gets a one-week zoom that still preserves the activity row
  // layout, just with the other weeks dimmed.
  return (
    <article className="card overflow-hidden">
      <header className="px-4 py-3 lg:px-5 lg:py-4 border-b border-[var(--color-edify-divider)] flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.1em] text-[var(--text-muted)] inline-flex items-center gap-1.5">
            <span className="status-indicator status-approved" aria-hidden />
            Cash-flow summary
          </div>
          <h3 className="text-[16px] font-extrabold tracking-tight mt-0.5">
            By Activity × Week
          </h3>
          <p className="text-[11.5px] text-[var(--text-muted)] mt-1 max-w-xl">
            Where the country&apos;s money flows this month — {matrix.rows.length} active categories, distributed by planned schedule and field-day shape.
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <div className="text-[10px] font-bold uppercase tracking-[0.1em] text-[var(--text-muted)]">
            Monthly Total
          </div>
          <div className="currency-display currency-display-lg">
            <span className="currency-unit">UGX</span>
            <span className="currency-value">{matrix.monthlyTotal.toLocaleString()}</span>
          </div>
        </div>
      </header>

      <div className="overflow-x-auto">
        <table className="w-full mfr-aw-table">
          <colgroup>
            <col className="w-[240px]" />
            <col />
            <col />
            <col />
            <col />
            <col />
            <col />
          </colgroup>
          <thead>
            <tr>
              <th className="mfr-aw-th-activity">Activity</th>
              <ColHeader week={1} dimmed={selectedWeek != null && selectedWeek !== 1} />
              <ColHeader week={2} dimmed={selectedWeek != null && selectedWeek !== 2} />
              <ColHeader week={3} dimmed={selectedWeek != null && selectedWeek !== 3} />
              <ColHeader week={4} dimmed={selectedWeek != null && selectedWeek !== 4} />
              <ColHeader week={5} dimmed={selectedWeek != null && selectedWeek !== 5} />
              <th className="mfr-aw-th-total">Monthly</th>
            </tr>
          </thead>
          <tbody>
            {matrix.rows.map((row) => (
              <ActivityRow
                key={row.category}
                row={row}
                selectedWeek={selectedWeek}
                count={matrix.categoryCounts[row.category]}
                onCellClick={onCellClick}
              />
            ))}
            <tr className="mfr-aw-totals">
              <td className="mfr-aw-totals-label">
                <div className="font-extrabold text-[12.5px] text-[var(--text-primary)]">Weekly cash needed</div>
                <div className="text-[10.5px] text-[var(--text-muted)] mt-0.5">Disburse to staff/partner accounts before week start</div>
              </td>
              <WeekTotal n={matrix.weekTotals.w1} dimmed={selectedWeek != null && selectedWeek !== 1} />
              <WeekTotal n={matrix.weekTotals.w2} dimmed={selectedWeek != null && selectedWeek !== 2} />
              <WeekTotal n={matrix.weekTotals.w3} dimmed={selectedWeek != null && selectedWeek !== 3} />
              <WeekTotal n={matrix.weekTotals.w4} dimmed={selectedWeek != null && selectedWeek !== 4} />
              <WeekTotal n={matrix.weekTotals.w5} dimmed={selectedWeek != null && selectedWeek !== 5} />
              <td className="mfr-aw-cell mfr-aw-grand">
                <div className="text-[14px] currency-inline text-[var(--text-primary)]">
                  {fmtCompact(matrix.monthlyTotal)}
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <footer className="px-4 py-3 lg:px-5 border-t border-[var(--color-edify-divider)] text-[11px] muted flex items-center gap-2 flex-wrap">
        <CheckCircle2 size={11} className="text-emerald-600 shrink-0" />
        <span>
          Distribution: meals + cluster/group trainings use explicit planned dates; staff visits, partner visits, SSA, transport, and accommodation are spread proportionally to each staff member's field-day shape. Click any cell to inspect the source activities.
        </span>
      </footer>
    </article>
  );
}

function ColHeader({ week, dimmed }: { week: 1 | 2 | 3 | 4 | 5; dimmed?: boolean }) {
  return (
    <th className={cn("mfr-aw-th-week", dimmed && "mfr-aw-dimmed")}>
      W{week}
    </th>
  );
}

function ActivityRow({
  row,
  selectedWeek,
  count,
  onCellClick,
}: {
  row: ActivityWeekRow;
  selectedWeek: 1 | 2 | 3 | 4 | 5 | null;
  count: number;
  onCellClick?: (target: MfrCellTarget) => void;
}) {
  const Icon = CATEGORY_ICON[row.category];
  const tone = CATEGORY_TONE[row.category];
  const click = (week: 1 | 2 | 3 | 4 | 5) =>
    onCellClick ? () => onCellClick({ category: row.category, week }) : undefined;
  const clickTotal = onCellClick ? () => onCellClick({ category: row.category }) : undefined;
  return (
    <tr className="mfr-aw-row">
      <td className="mfr-aw-activity-cell">
        <div className={cn("mfr-aw-cat-chip", tone)}>
          <Icon size={13} />
        </div>
        <div className="min-w-0">
          <div className="text-[12.5px] font-extrabold tracking-tight">{row.label}</div>
          <div className="text-[10px] muted font-semibold">
            {count} {count === 1 ? "line" : "lines"} contributing
          </div>
        </div>
      </td>
      <Cell n={row.w1} dimmed={selectedWeek != null && selectedWeek !== 1} onClick={row.w1 > 0 ? click(1) : undefined} />
      <Cell n={row.w2} dimmed={selectedWeek != null && selectedWeek !== 2} onClick={row.w2 > 0 ? click(2) : undefined} />
      <Cell n={row.w3} dimmed={selectedWeek != null && selectedWeek !== 3} onClick={row.w3 > 0 ? click(3) : undefined} />
      <Cell n={row.w4} dimmed={selectedWeek != null && selectedWeek !== 4} onClick={row.w4 > 0 ? click(4) : undefined} />
      <Cell n={row.w5} dimmed={selectedWeek != null && selectedWeek !== 5} onClick={row.w5 > 0 ? click(5) : undefined} />
      <td
        className={cn(
          "mfr-aw-cell mfr-aw-total",
          row.total > 0 && onCellClick && "mfr-aw-clickable",
        )}
        onClick={clickTotal}
      >
        <span className="text-[13px] currency-inline text-[var(--text-primary)]">
          {fmtCompact(row.total)}
        </span>
      </td>
    </tr>
  );
}

function Cell({
  n,
  dimmed,
  onClick,
}: {
  n: number;
  dimmed?: boolean;
  onClick?: () => void;
}) {
  return (
    <td
      className={cn(
        "mfr-aw-cell",
        n === 0 && "mfr-aw-zero",
        dimmed && "mfr-aw-dimmed",
        n > 0 && onClick && "mfr-aw-clickable",
      )}
      onClick={onClick}
    >
      {n > 0 ? (
        <span className="text-[12px] currency-inline text-[var(--text-primary)]">
          {fmtCompact(n)}
        </span>
      ) : (
        <span className="mfr-aw-em-dash">—</span>
      )}
    </td>
  );
}

function WeekTotal({ n, dimmed }: { n: number; dimmed?: boolean }) {
  return (
    <td className={cn("mfr-aw-cell mfr-aw-week-total", dimmed && "mfr-aw-dimmed")}>
      <span className="text-[13px] currency-inline text-[var(--text-primary)]">
        {n > 0 ? fmtCompact(n) : "—"}
      </span>
    </td>
  );
}

function fmtCompact(n: number): string {
  if (n >= 1_000_000) return `UGX ${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `UGX ${(n / 1_000).toFixed(0)}k`;
  return `UGX ${n.toLocaleString()}`;
}
