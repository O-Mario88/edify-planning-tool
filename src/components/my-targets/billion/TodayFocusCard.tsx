"use client";

import {
  Bell,
  Calendar,
  CheckCircle2,
  Eye,
  RefreshCw,
  Route,
  Target,
  type LucideIcon,
} from "lucide-react";
import { ProgressRing, SectionCard } from "@/components/ui/primitives";
import {
  todayFocus,
  type TodayCategoryRow,
} from "@/lib/my-targets-billion-mock";
import { cn } from "@/lib/utils";

// Today Focus — the dense right rail. Four sub-sections stacked in
// one card: snapshot KPIs · today's targets by category · urgent
// blockers · quick actions. The daily-debrief input + blocker chips
// used to live here too but were promoted into DailyDebriefCard so
// the end-of-day reflection has its own surface under Recovery
// Actions.
export function TodayFocusCard() {
  const f = todayFocus;

  return (
    <SectionCard
      icon={<Target size={13} />}
      title="Today Focus"
      actions={
        <span className="inline-flex items-center gap-1 px-2 py-[2px] rounded-md text-[10px] font-extrabold bg-rose-50 text-rose-700 border border-rose-200">
          ⚠ {f.status}
        </span>
      }
    >
      {/* KPI strip — adaptive.
          Mobile (<sm): completion ring on the LEFT, 4 mini KPIs in a
                        2×2 grid on the RIGHT so each tile has room
                        to breathe instead of 5 cells crammed into
                        ~300px.
          sm+:          5 columns in one row as the reference shows. */}
      <div className="sm:hidden grid grid-cols-[auto_1fr] gap-3 items-center mb-3">
        <div className="flex flex-col items-center justify-center">
          <ProgressRing
            pct={f.kpis.completionPct}
            size={56}
            stroke={5}
            color="#ef4444"
            label={`${f.kpis.completionPct}%`}
            animate={false}
          />
          <div className="text-[9px] uppercase tracking-wide muted font-bold mt-1">Completion</div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <FocusKpi label="Planned"    value={f.kpis.planned}     unit="tasks" />
          <FocusKpi label="Completed"  value={f.kpis.completed}   unit="tasks" tone="good" />
          <FocusKpi label="In Progress" value={f.kpis.inProgress} unit="tasks" tone="neutral" />
          <FocusKpi label="Pending"    value={f.kpis.pending}     unit="tasks" tone="warn" />
        </div>
      </div>

      <div className="hidden sm:grid grid-cols-5 gap-1.5 mb-3">
        <FocusKpi label="Planned"    value={f.kpis.planned}     unit="tasks" />
        <FocusKpi label="Completed"  value={f.kpis.completed}   unit="tasks" tone="good" />
        <FocusKpi label="In Progress" value={f.kpis.inProgress} unit="tasks" tone="neutral" />
        <FocusKpi label="Pending"    value={f.kpis.pending}     unit="tasks" tone="warn" />
        <div className="flex flex-col items-center justify-center">
          <ProgressRing
            pct={f.kpis.completionPct}
            size={48}
            stroke={5}
            color="#ef4444"
            label={`${f.kpis.completionPct}%`}
            animate={false}
          />
          <div className="text-[9px] uppercase tracking-wide muted font-bold mt-0.5">Completion</div>
        </div>
      </div>

      {/* Today's Targets by Category */}
      <SectionLabel>Today&apos;s Targets by Category</SectionLabel>
      <ul className="space-y-1 mb-3">
        {f.categories.map((c) => (
          <CategoryItem key={c.key} c={c} />
        ))}
      </ul>

      {/* Urgent Blockers */}
      <SectionLabel>Urgent Blockers</SectionLabel>
      <ul className="space-y-1 mb-2">
        {f.blockers.map((b) => (
          <li key={b.key} className="flex items-center gap-2 text-[11px]">
            <span className={cn(
              "w-5 h-5 rounded-md grid place-items-center text-[9.5px] font-extrabold shrink-0",
              b.count === 0 ? "bg-slate-100 text-slate-500" : "bg-rose-100 text-rose-700",
            )}>
              {b.letter}
            </span>
            <span className="text-[11px] tabular font-extrabold shrink-0 w-[14px] text-right">{b.count}</span>
            <span className="text-[11px] font-semibold text-slate-700 leading-tight truncate flex-1">{b.text}</span>
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="inline-flex items-center gap-1 text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline mb-3"
      >
        <Eye size={11} />
        View All Blockers
      </button>

      {/* Quick Actions — the last section. Daily Debrief + Quick
          Blockers used to live below this; they were extracted into
          DailyDebriefCard so the end-of-day reflection has its own
          surface next to Recovery Actions. */}
      <SectionLabel>Quick Actions</SectionLabel>
      <div className="grid grid-cols-2 gap-1.5">
        {f.quickActions.map((a) => (
          <QuickActionButton key={a.key} label={a.label} icon={a.icon} />
        ))}
      </div>
    </SectionCard>
  );
}

// ───────────── FocusKpi ─────────────

function FocusKpi({
  label,
  value,
  unit,
  tone = "neutral",
}: {
  label: string;
  value: number;
  unit: string;
  tone?: "good" | "warn" | "neutral";
}) {
  const valueColor =
    tone === "good"  ? "text-emerald-700"
    : tone === "warn" ? "text-rose-700"
    : "text-slate-900";
  return (
    <div className="flex flex-col items-center text-center">
      <div className="text-[9px] uppercase tracking-wide muted font-bold leading-tight">{label}</div>
      <div className={cn("text-[18px] font-extrabold tabular leading-none mt-0.5", valueColor)}>{value}</div>
      <div className="text-[9px] muted font-semibold leading-tight mt-0.5">{unit}</div>
    </div>
  );
}

// ───────────── CategoryItem ─────────────

const CAT_TONE: Record<TodayCategoryRow["tone"], { dot: string; chip: string }> = {
  good:    { dot: "bg-emerald-500", chip: "bg-emerald-50 text-emerald-700" },
  warn:    { dot: "bg-rose-500",    chip: "bg-rose-50    text-rose-700"    },
  neutral: { dot: "bg-slate-300",   chip: "bg-slate-50   text-slate-600"   },
};

function CategoryItem({ c }: { c: TodayCategoryRow }) {
  const t = CAT_TONE[c.tone];
  return (
    <li className="flex items-center gap-2 text-[11px]">
      <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", t.dot)} aria-hidden />
      <span className="text-[11px] font-semibold text-slate-700 leading-tight truncate flex-1">{c.label}</span>
      <span className={cn("inline-flex items-center px-1.5 py-[1px] rounded-md text-[10px] font-extrabold whitespace-nowrap", t.chip)}>
        {c.doneText}
      </span>
    </li>
  );
}

// ───────────── QuickActionButton ─────────────

const QA_ICON: Record<"calendar" | "route" | "bell" | "refresh", LucideIcon> = {
  calendar: Calendar,
  route:    Route,
  bell:     Bell,
  refresh:  RefreshCw,
};

function QuickActionButton({
  label,
  icon,
}: {
  label: string;
  icon: "calendar" | "route" | "bell" | "refresh";
}) {
  const Icon = QA_ICON[icon];
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1.5 h-8 px-2 rounded-lg bg-[var(--color-edify-soft)]/50 border border-[var(--color-edify-border)] text-[11px] font-bold text-slate-700 hover:bg-[var(--color-edify-soft)] transition-colors"
    >
      <Icon size={12} className="text-[var(--color-edify-muted)]" />
      <span className="truncate">{label}</span>
    </button>
  );
}

// ───────────── SectionLabel ─────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[9.5px] uppercase tracking-[0.12em] text-slate-500 font-bold mb-1.5 mt-1 inline-flex items-center gap-1.5">
      <CheckCircle2 size={9} className="opacity-50" />
      {children}
    </div>
  );
}
