// PlanningCategorySummary — the CCEO's recommendation-led planning rollup
// (spec §9). Eight expandable category cards (Schools Needing SSA/SIT →
// Special Project Activities), each folding a detail-heavy list per the
// collapsible-card rule. Collapsed: count, red-alert badge, estimated cost,
// priority pill. Expanded: the unscheduled recommended rows, each with the
// two weakest interventions, the recommendation, the delivery route, and a
// Schedule button to the same destination the gap boards use.
//
// Server component — collapse behaviour lives in CollapsibleCard's client
// island. All 8 categories render (a "clear" card is the good news).

import Link from "next/link";
import { CalendarPlus, ClipboardList, CheckCircle2 } from "lucide-react";
import { CollapsibleCard } from "@/components/ui/CollapsibleCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Pill, type PillTone } from "@/components/ui/Pill";
import {
  formatUgx,
  type PlanningCategory,
  type PlanningCategoryPriority,
  type PlanningCategoryRow,
} from "@/lib/planning/planning-categories";

const PRIORITY: Record<PlanningCategoryPriority, { label: string; tone: PillTone }> = {
  high:   { label: "High priority", tone: "danger" },
  medium: { label: "Open",          tone: "info" },
  clear:  { label: "Clear",         tone: "success" },
};

export function PlanningCategorySummary({ categories }: { categories: PlanningCategory[] }) {
  const totalOpen = categories.reduce((a, c) => a + c.count, 0);
  const totalRed = categories.reduce((a, c) => a + c.redAlertCount, 0);

  return (
    <section className="space-y-2.5" aria-label="Recommended planning categories">
      <SectionHeader
        eyebrow="Planning summary"
        title="Recommended to plan"
        description="Unscheduled recommended work across your portfolio, grouped the way you plan it. Expand a category and schedule row by row."
        icon={<ClipboardList size={14} />}
        meta={
          <span className="inline-flex items-center gap-1.5">
            <Pill tone={totalRed > 0 ? "danger" : "neutral"} size="sm" dot>
              {totalRed} red alert{totalRed === 1 ? "" : "s"}
            </Pill>
            <Pill tone="neutral" size="sm">{totalOpen} open</Pill>
          </span>
        }
      />

      {categories.map((cat) => {
        const priority = PRIORITY[cat.priority];
        return (
          <CollapsibleCard
            key={cat.key}
            id={`planning-category-${cat.key}`}
            tier="operational"
            title={cat.label}
            defaultCollapsed
            meta={
              <span className="inline-flex flex-wrap items-center gap-1.5 text-[11px] font-bold">
                <span className="px-1.5 py-[1px] rounded bg-[var(--color-edify-primary)]/10 text-[var(--color-edify-primary)] tabular">
                  {cat.count}
                </span>
                {cat.redAlertCount > 0 && (
                  <Pill tone="danger" size="xs" dot>
                    {cat.redAlertCount} red
                  </Pill>
                )}
                {cat.estimatedCost > 0 && (
                  <span className="muted tabular">~{formatUgx(cat.estimatedCost)}</span>
                )}
                <Pill tone={priority.tone} size="xs">{priority.label}</Pill>
              </span>
            }
          >
            {cat.rows.length === 0 ? (
              <div className="py-3 text-center">
                <CheckCircle2 size={16} className="mx-auto text-emerald-600" />
                <p className="mt-1 text-[11.5px] muted">Nothing unscheduled here — this category is clear.</p>
              </div>
            ) : (
              <ul className="divide-y divide-[var(--color-edify-divider)]">
                {cat.rows.map((row) => (
                  <CategoryRow key={row.key} row={row} />
                ))}
              </ul>
            )}
          </CollapsibleCard>
        );
      })}
    </section>
  );
}

function CategoryRow({ row }: { row: PlanningCategoryRow }) {
  return (
    <li className="py-2.5 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-[12.5px] font-bold">{row.name}</span>
          <span className="muted text-[11px]">{row.district}</span>
          {row.redAlert && <Pill tone="danger" size="xs" dot>Red alert</Pill>}
          <Pill tone={row.delivery === "partner" ? "violet" : "info"} size="xs" subtle>
            {row.delivery === "partner" ? "Partner" : "Staff"}
          </Pill>
        </div>
        {(row.weakest || row.secondWeak) && (
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {[row.weakest, row.secondWeak].filter(Boolean).map((w) => (
              <span
                key={w!.area}
                className="inline-flex items-center gap-1 px-1.5 py-[1px] rounded border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/50 text-[10.5px] font-semibold"
              >
                {w!.area} <span className="tabular muted">{w!.score}/10</span>
              </span>
            ))}
          </div>
        )}
        <p className="mt-1 text-[11.5px] muted">{row.recommendation}</p>
      </div>
      <div className="shrink-0 flex flex-col items-end gap-1">
        <Link
          href={row.scheduleHref}
          className="inline-flex items-center gap-1 h-7 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)]/60"
        >
          <CalendarPlus size={11} /> Schedule
        </Link>
        {row.costUgx != null && row.costUgx > 0 && (
          <span className="text-[10.5px] muted tabular">~{formatUgx(row.costUgx)}</span>
        )}
      </div>
    </li>
  );
}
