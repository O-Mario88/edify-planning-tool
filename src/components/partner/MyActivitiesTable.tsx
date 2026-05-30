"use client";

// MyActivitiesTable — the deep activity list under
// /partner/activities. Built on the same data layer as
// the Command Center's Action Inbox but with broader columns and a
// status filter strip so the partner can pivot through all 47 items.

import { useMemo } from "react";
import Link from "next/link";
import { ArrowRight, Building2, Filter, Download } from "lucide-react";
import { cn } from "@/lib/utils";
import { partnerInboxRows } from "@/lib/partner/partner-dashboard-mock";
import {
  evidenceSummaries,
} from "@/lib/partner/partner-evidence-mock";
import { useUrlState } from "@/hooks/use-url-state";

type FilterKey = "all" | "scheduled" | "evidence" | "returned" | "awaiting" | "completed";
type ActionLabel = (typeof partnerInboxRows)[number]["actionLabel"];

// Single source of truth for filter → matching action labels. The
// counts + the visible rows both read from this map, so the badge
// can never disagree with the table.
const ACTION_LABELS_BY_FILTER: Record<FilterKey, ActionLabel[]> = {
  all:        [],
  scheduled:  ["Start Visit"],
  evidence:   ["Upload Evidence"],
  returned:   ["Correct Report"],
  awaiting:   ["View Status"],
  completed:  ["View Details"],
};

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all",        label: "All" },
  { key: "scheduled",  label: "Scheduled" },
  { key: "evidence",   label: "Needs evidence" },
  { key: "returned",   label: "Returned" },
  { key: "awaiting",   label: "Awaiting CCEO" },
  { key: "completed",  label: "Completed" },
];
const FILTER_KEYS = FILTERS.map((f) => f.key) as readonly FilterKey[];

const PRIORITY_TONE = {
  High:   { dot: "bg-rose-500",    text: "text-rose-700" },
  Medium: { dot: "bg-amber-500",   text: "text-amber-700" },
  Low:    { dot: "bg-emerald-500", text: "text-emerald-700" },
} as const;

export function MyActivitiesTable() {
  const [active, setActive] = useUrlState<FilterKey>({
    key: "filter",
    defaultValue: "all",
    allowed: FILTER_KEYS,
  });

  // "My Plan" excludes Schedule-Activity rows by design — those are
  // assignments still waiting for the partner to place them in a
  // delivery week. They live on /partner/schedule until scheduled,
  // then flow back into the plan here.
  const planRows = useMemo(
    () => partnerInboxRows.filter((r) => r.actionLabel !== "Schedule Activity"),
    [],
  );

  const rows = useMemo(() => {
    if (active === "all") return planRows;
    const targets = ACTION_LABELS_BY_FILTER[active];
    return planRows.filter((r) => targets.includes(r.actionLabel));
  }, [active, planRows]);

  // Compute counts once from the same map, so a count badge can never
  // drift from the filtered rows it advertises.
  const counts = useMemo(() => {
    const out = {} as Record<FilterKey, number>;
    for (const f of FILTER_KEYS) {
      out[f] = f === "all"
        ? planRows.length
        : planRows.filter((r) => ACTION_LABELS_BY_FILTER[f].includes(r.actionLabel)).length;
    }
    return out;
  }, [planRows]);

  // Join in the evidence completeness for each row by school name
  // match (mock — production wires by activityId).
  const evidenceByName = useMemo(() => {
    const m: Record<string, number> = {};
    for (const s of evidenceSummaries) m[s.schoolName] = s.completenessScore;
    return m;
  }, []);

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-3 flex-wrap mb-3">
        <div className="flex items-center gap-1 flex-wrap">
          {FILTERS.map((f) => {
            const isActive = active === f.key;
            const count = counts[f.key];
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setActive(f.key)}
                aria-pressed={isActive}
                className={cn(
                  "inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-[11.5px] font-semibold whitespace-nowrap transition-colors",
                  isActive
                    ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] border border-[var(--color-edify-border)]"
                    : "text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/50",
                )}
              >
                {f.label}
                {count > 0 && (
                  <span className={cn(
                    "inline-flex items-center justify-center min-w-[18px] h-[16px] px-1 rounded-md text-[9.5px] font-extrabold",
                    isActive ? "bg-[var(--color-edify-primary)] text-white" : "bg-slate-100 text-slate-700",
                  )}>
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2">
          <button className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)]/60">
            <Filter size={12} /> Filters
          </button>
          <button className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)]/60">
            <Download size={12} /> Export
          </button>
        </div>
      </header>

      <div className="overflow-auto scrollbar -mx-1 px-1 max-h-[560px] rounded-md">
        <table className="w-full dtable">
          <thead className="sticky top-0 z-10 bg-white">
            <tr>
              <th className="text-left text-[11px] font-semibold muted">Priority</th>
              <th className="text-left text-[11px] font-semibold muted">School</th>
              <th className="text-left text-[11px] font-semibold muted">Activity</th>
              {/* Secondary columns hidden below lg so the action button
                  isn't clipped at tablet widths. Facilitator + evidence
                  remain visible via the expanded school detail page. */}
              <th className="hidden lg:table-cell text-left text-[11px] font-semibold muted">Facilitator</th>
              <th className="hidden lg:table-cell text-left text-[11px] font-semibold muted">Evidence</th>
              <th className="text-left text-[11px] font-semibold muted">Due</th>
              <th className="text-right text-[11px] font-semibold muted">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const p = PRIORITY_TONE[r.priority];
              const evidence = evidenceByName[r.school];
              return (
                <tr key={r.id} className="hover:bg-[var(--color-edify-soft)]/40 transition-colors">
                  <td>
                    <span className={cn("inline-flex items-center gap-1.5 text-[12px] font-semibold", p.text)}>
                      <span className={cn("w-1.5 h-1.5 rounded-full", p.dot)} />
                      {r.priority}
                    </span>
                  </td>
                  <td>
                    <div className="flex items-center gap-2">
                      <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
                        <Building2 size={11} />
                      </span>
                      <div className="min-w-0">
                        <div className="text-body font-semibold leading-tight truncate">{r.school}</div>
                        <div className="text-caption muted leading-tight">{r.district}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <div className="text-[12px] font-semibold leading-tight">{r.activity}</div>
                    <div className="text-caption muted leading-tight mt-0.5">{r.activitySub}</div>
                  </td>
                  <td className="hidden lg:table-cell text-[12px]">{r.facilitator}</td>
                  <td className="hidden lg:table-cell">
                    {evidence != null ? (
                      <span className={cn(
                        "inline-flex items-center px-2 py-[3px] rounded-md text-caption font-bold tabular",
                        evidence >= 80 ? "bg-emerald-50 text-emerald-700" :
                        evidence >= 50 ? "bg-amber-50 text-amber-700" :
                        "bg-rose-50 text-rose-700",
                      )}>
                        {evidence}%
                      </span>
                    ) : (
                      <span className="text-[11px] muted">—</span>
                    )}
                  </td>
                  <td className="text-[12px] whitespace-nowrap">
                    <div className="font-semibold">{r.dueDateLabel}</div>
                    <div className="text-[10px] muted">{r.dueDateSub}</div>
                  </td>
                  <td className="text-right">
                    <Link
                      href="/dashboards/partner"
                      className="inline-flex items-center gap-1 h-8 px-3 rounded-md text-[11.5px] font-semibold border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/60"
                    >
                      Open <ArrowRight size={11} />
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[12px] muted text-center">
        Showing all <span className="font-semibold text-[var(--color-edify-text)]">{rows.length}</span> activities · scroll inside the card to see more.
      </div>
    </section>
  );
}
