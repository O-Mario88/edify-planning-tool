"use client";

import { useMemo, useState } from "react";
import {
  Search,
  AlertTriangle,
  ChevronRight,
  Building2,
  GraduationCap,
  ShieldCheck,
  Users,
  Check,
  type LucideIcon,
} from "lucide-react";
import { MobileShell } from "@/components/mobile/MobileShell";
import { MobileBottomNav } from "@/components/mobile/MobileBottomNav";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import {
  planBuilderHeader,
  priorityPlanCandidates,
  type PlanActivityType,
  type PriorityPlanCandidate,
  type PriorityIssue,
} from "@/lib/mobile-mock";
import { cn } from "@/lib/utils";

const ACTIVITY_FILTERS: { key: "all" | PlanActivityType; label: string }[] = [
  { key: "all",            label: "All" },
  { key: "School Visit",   label: "Visits" },
  { key: "Training",       label: "Trainings" },
  { key: "SSA Follow-Up",  label: "SSA" },
];

const ACTIVITY_ICON: Record<PlanActivityType, LucideIcon> = {
  "School Visit":    Building2,
  "Training":        GraduationCap,
  "SSA Follow-Up":   ShieldCheck,
  "Cluster Meeting": Users,
};

const ACTIVITY_TONE: Record<PlanActivityType, string> = {
  "School Visit":    "bg-sky-100     text-sky-700",
  "Training":        "bg-violet-100  text-violet-700",
  "SSA Follow-Up":   "bg-amber-100   text-amber-700",
  "Cluster Meeting": "bg-emerald-100 text-emerald-700",
};

const ISSUE_TONE: Record<PriorityIssue, string> = {
  "Low SSA Performance":          "bg-rose-100   text-rose-700",
  "No Visit":                     "bg-amber-100  text-amber-700",
  "No Training":                  "bg-violet-100 text-violet-700",
  "Neither Training nor Visit":   "bg-blue-100   text-blue-700",
  "Inactive":                     "bg-slate-200  text-slate-700",
};

export function PlanBuilderView() {
  const [filter, setFilter] = useState<"all" | PlanActivityType>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return priorityPlanCandidates.filter((c) => {
      if (filter !== "all" && c.recommended !== filter) return false;
      if (!q) return true;
      return (
        c.schoolName.toLowerCase().includes(q) ||
        c.cluster.toLowerCase().includes(q) ||
        c.district.toLowerCase().includes(q)
      );
    });
  }, [filter, query]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const selectedCount = selected.size;

  return (
    <MobileShell>
      <MobileTopBar
        title={planBuilderHeader.title}
        backHref="/dashboard"
        monthLabel={planBuilderHeader.monthLabel}
      />
      <p className="px-4 pt-2 pb-1 text-[11.5px] muted">
        {planBuilderHeader.subtitle}
      </p>

      <main className="flex-1 px-3 pt-3 pb-28 space-y-3 bg-[var(--color-page)]">
        {/* Priority banner */}
        <div className="rounded-2xl bg-rose-50 border border-rose-200 p-3 flex items-center gap-3">
          <span className="h-9 w-9 rounded-md bg-white text-rose-600 grid place-items-center shrink-0 border border-rose-200">
            <AlertTriangle size={16} />
          </span>
          <div className="flex-1 min-w-0">
            <div className="text-body font-extrabold tracking-tight">
              High Priority Schools
            </div>
            <div className="text-caption text-rose-700/80 leading-snug">
              Ranked by SSA + visit & training gaps. Pick schools to add to your plan.
            </div>
          </div>
          <span className="text-[20px] font-extrabold tabular text-rose-700 shrink-0">
            {planBuilderHeader.totalCandidates}
          </span>
        </div>

        {/* Search */}
        <div className="relative">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)]"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search school, cluster, district"
            aria-label="Search high priority schools"
            className="w-full pl-9 pr-3 h-10 rounded-xl border border-[var(--color-edify-border)] bg-white text-body placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          />
        </div>

        {/* Activity filter chips */}
        <div className="flex items-center gap-1.5 overflow-x-auto -mx-1 px-1">
          {ACTIVITY_FILTERS.map((f) => {
            const active = f.key === filter;
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={cn(
                  "shrink-0 h-8 px-3 rounded-full text-[11.5px] font-extrabold tracking-tight border",
                  active
                    ? "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)]"
                    : "bg-white text-[var(--color-edify-text)] border-[var(--color-edify-border)]",
                )}
              >
                {f.label}
              </button>
            );
          })}
        </div>

        {/* Candidates list */}
        <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] divide-y divide-[var(--color-edify-divider)] shadow-sm">
          {filtered.length === 0 && (
            <div className="px-3 py-6 text-[12px] muted text-center">
              No matching schools.
            </div>
          )}
          {filtered.map((c) => (
            <CandidateRow
              key={c.id}
              c={c}
              checked={selected.has(c.id)}
              onToggle={() => toggle(c.id)}
            />
          ))}
        </section>
      </main>

      {/* Sticky CTA above the bottom nav */}
      <div className="fixed bottom-16 left-0 right-0 md:hidden z-20 px-3 pb-2 pointer-events-none">
        <div className="max-w-[480px] mx-auto pointer-events-auto">
          <div className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-lg p-2.5 flex items-center gap-3">
            <div className="text-[12px] font-extrabold tracking-tight">
              <span className="tabular text-body-lg">{selectedCount}</span>{" "}
              {selectedCount === 1 ? "school selected" : "schools selected"}
            </div>
            <button
              type="button"
              disabled={selectedCount === 0}
              className={cn(
                "ml-auto h-10 px-4 rounded-xl text-body font-extrabold tracking-tight inline-flex items-center gap-1.5",
                selectedCount === 0
                  ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)]"
                  : "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white shadow-md shadow-emerald-500/30",
              )}
            >
              Continue
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </div>

      <MobileBottomNav />
    </MobileShell>
  );
}

function CandidateRow({
  c,
  checked,
  onToggle,
}: {
  c: PriorityPlanCandidate;
  checked: boolean;
  onToggle: () => void;
}) {
  const Icon = ACTIVITY_ICON[c.recommended];
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={checked ? "true" : "false"}
      className="w-full flex items-start gap-3 px-3 py-3 text-left active:bg-[var(--color-edify-soft)]/40"
    >
      {/* Rank chip */}
      <div className="flex flex-col items-center shrink-0 w-8 pt-0.5">
        <div className="h-6 w-6 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center text-[10px] font-extrabold">
          #{c.rank}
        </div>
        <div className="text-[9px] muted mt-1">{c.distanceKm} km</div>
      </div>

      {/* Activity icon */}
      <span className={cn("h-9 w-9 rounded-md grid place-items-center shrink-0 mt-0.5", ACTIVITY_TONE[c.recommended])}>
        <Icon size={15} />
      </span>

      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <div className="text-body font-extrabold tracking-tight leading-tight">
            {c.schoolName}
          </div>
          <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap shrink-0", ISSUE_TONE[c.issue])}>
            {c.issue}
          </span>
        </div>
        <div className="text-caption muted truncate">
          {c.cluster} · {c.district}
        </div>
        <div className="text-caption muted truncate">{c.reason}</div>
        <div className="mt-1 flex items-center justify-between">
          <span className="text-[10px] font-semibold text-[var(--color-edify-primary)]">
            SSA {c.ssaPercent}%
          </span>
          <span className="text-[10px] muted">{c.suggestedWeek}</span>
        </div>
      </div>

      {/* Checkbox */}
      <span
        className={cn(
          "h-6 w-6 rounded-md border-2 grid place-items-center shrink-0 mt-1 transition-colors",
          checked
            ? "bg-emerald-500 border-emerald-500 text-white"
            : "bg-white border-[var(--color-edify-border)] text-transparent",
        )}
        aria-hidden
      >
        <Check size={14} />
      </span>
    </button>
  );
}
