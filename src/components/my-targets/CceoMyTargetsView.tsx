"use client";

// CCEO My Targets — personal command center.
//
// Top KPI row · Quick actions · This-Week Todo (left) + This-Week Route Map
// (right) · Monthly Plan by Week · Target Progress Bars · Support Section ·
// Daily Debrief auto-seed.
//
// Interactive layer (client):
//   • Visit completion modal on every todo (photo / signature / SSA delta /
//     observations / quality / MSC) — flips local status to Submitted for
//     Verification and persists in cceo-execution-store.
//   • Real-time blocker flag (floating action) goes straight to PL.
//   • Filterable todos (All / Today / This Week / Overdue / Critical).
//   • Streak chip + Weekly recap card (Fri/Sat).

import { useEffect, useMemo, useState } from "react";
import {
  CalendarRange,
  CheckCircle2,
  AlertTriangle,
  Wallet,
  Award,
  Database,
  Footprints,
  ClipboardList,
  MapPin,
  Flame,
  Trophy,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  PlannedActivity,
  ActivityStatus,
  ActivityType,
  TargetCategory,
  SupportSignal,
  WeekBreakdown,
  WeekRoutePreview,
  MonthlyKpis,
} from "@/lib/cceo-my-targets-engine";
import { countsTowardTarget } from "@/lib/target-counting";
import {
  loadCompletions,
  saveCompletion,
  loadBlockers,
  saveBlocker,
  loadStreak,
  recordDebriefSubmission,
  isFridayOrLater,
  type VisitCompletion,
  type RealtimeBlocker,
  type DebriefStreak,
} from "@/lib/cceo-execution-store";
import { shortStatusLabel, fullStatusLabel } from "@/lib/status-labels";
import { closeAssignmentsBySchoolId } from "@/lib/assignment-store";
import { AssignedByPLCard } from "@/components/my-targets/AssignedByPLCard";
import { SalesforceCompletionModal } from "@/components/my-targets/SalesforceCompletionModal";
import { RealtimeBlockerModal } from "@/components/my-targets/RealtimeBlockerModal";
import { TopPerformerCard } from "@/components/leaderboard/TopPerformerCard";
import {
  ProgressRing,
  MiniBar,
  SecondaryStat,
  HeroKpiCard,
  formatM,
} from "@/components/my-targets/CceoMyTargetsParts";
import {
  FEASIBILITY_TONE,
  ThisWeekClusterRoutePlanCard,
  WeekBreakdownCard,
  TargetBarRow,
  SupportSection,
  QuickActionsRow,
  WeeklyRecapCard,
  DailyDebriefStrip,
} from "@/components/my-targets/CceoMyTargetsCards";

// ────────── Tones ──────────

const STATUS_TONE: Record<ActivityStatus, string> = {
  Planned:                    "bg-slate-100  text-slate-700",
  Ready:                      "bg-sky-100    text-sky-700",
  "In Progress":              "bg-blue-100   text-blue-700",
  Completed:                  "bg-emerald-100 text-emerald-700",
  "Salesforce ID Pending":    "bg-amber-100  text-amber-800",
  "Submitted for Verification":"bg-violet-100 text-violet-700",
  Verified:                   "bg-emerald-100 text-emerald-700",
  Returned:                   "bg-rose-100   text-rose-700",
  Overdue:                    "bg-rose-100   text-rose-700",
};

const TYPE_TONE: Record<ActivityType, string> = {
  "School Visit":          "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
  "Follow-Up Visit":       "bg-violet-50    text-violet-700",
  "Core School Visit":     "bg-amber-50     text-amber-800",
  "SSA Verification":      "bg-sky-50       text-sky-700",
  "SSA Support":           "bg-sky-50       text-sky-700",
  "Training Follow-Up":    "bg-violet-50    text-violet-700",
  "Cluster Training":      "bg-emerald-50   text-emerald-700",
  "Cluster Meeting":       "bg-blue-50      text-blue-700",
  "Partner Visit":         "bg-amber-50     text-amber-700",
  "Special Project Visit": "bg-rose-50      text-rose-700",
};

// ────────── Props ──────────

export type CceoMyTargetsProps = {
  kpis:           MonthlyKpis;
  weekBreakdown:  WeekBreakdown[];
  targets:        TargetCategory[];
  support:        SupportSignal[];
  routePreview:   WeekRoutePreview;
  thisWeek:       PlannedActivity[];
  supervisorInterventionNeeded: boolean;
  userName:       string;
  // Threaded from the page so the assignment store can filter to the
  // signed-in CCEO's incoming PL assignments.
  userStaffId?:   string;
};

// ────────── Main view ──────────

export type TodoFilter = "all" | "today" | "week" | "overdue" | "critical";

export function CceoMyTargetsView({
  kpis, weekBreakdown, targets, support, routePreview, thisWeek,
  supervisorInterventionNeeded, userName, userStaffId,
}: CceoMyTargetsProps) {

  // ────────── Client state ──────────
  const [completions, setCompletions] = useState<Record<string, VisitCompletion>>({});
  const [blockers,    setBlockers]    = useState<RealtimeBlocker[]>([]);
  const [streak,      setStreak]      = useState<DebriefStreak>({ lastSubmittedDate: null, current: 0, best: 0 });
  const [activeCompletion, setActiveCompletion] = useState<PlannedActivity | null>(null);
  const [blockerOpen,   setBlockerOpen]   = useState(false);
  const [todoFilter,    setTodoFilter]    = useState<TodoFilter>("all");
  const [winToast,      setWinToast]      = useState<string | null>(null);
  const [blockerSchool, setBlockerSchool] = useState<{ id?: string; name?: string }>({});

  // One-shot hydration from the client-side execution store. Migrate
  // to useSyncExternalStore during the React-19 sweep.
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect */
    setCompletions(loadCompletions());
    setBlockers(loadBlockers());
    setStreak(loadStreak());
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  // Effective todo list — overlay client completions onto server activities.
  const effectiveTodos: PlannedActivity[] = useMemo(() => {
    return thisWeek.map((a) => {
      const c = completions[a.id];
      if (!c) return a;
      return { ...a, status: "Submitted for Verification" as ActivityStatus, needsSalesforce: true };
    });
  }, [thisWeek, completions]);

  // Filter
  const filteredTodos = useMemo(() => filterTodos(effectiveTodos, todoFilter), [effectiveTodos, todoFilter]);

  function handleComplete(c: VisitCompletion) {
    saveCompletion(c);
    setCompletions((prev) => ({ ...prev, [c.activityId]: c }));
    // Loop closure: if the PL had assigned a follow-up for this school
    // and it's still open on this CCEO's plan, the Salesforce ID
    // capture closes it automatically. The PL doesn't have to chase;
    // the CCEO doesn't have to remember which assignment matches.
    let closedSuffix = "";
    if (userStaffId) {
      const closed = closeAssignmentsBySchoolId({
        cceoStaffId: userStaffId,
        schoolId: c.schoolId,
        salesforceId: c.salesforceId,
      });
      if (closed > 0) {
        closedSuffix = ` Closed ${closed} Program-Lead follow-up assignment${closed === 1 ? "" : "s"}.`;
      }
    }
    setWinToast(`${c.salesforceIdKind} ${c.salesforceId} logged. Submitted for verification.${closedSuffix}`);
    setTimeout(() => setWinToast(null), 5_000);
  }
  function handleBlocker(b: RealtimeBlocker) {
    saveBlocker(b);
    setBlockers((prev) => [b, ...prev]);
    setWinToast(`Blocker flagged: ${b.category}. Your Program Lead has been notified.`);
    setTimeout(() => setWinToast(null), 4_000);
  }
  function handleDebriefSubmit() {
    const next = recordDebriefSubmission();
    setStreak(next);
    setWinToast(`Daily debrief submitted. Streak: ${next.current} day${next.current === 1 ? "" : "s"}.`);
    setTimeout(() => setWinToast(null), 4_000);
  }

  const verifiedToday = Object.values(completions).filter((c) => c.completedAt.slice(0, 10) === new Date().toISOString().slice(0, 10)).length;

  // Annual coverage: verified visits in the current FY against the CCEO
  // 560-school annual target. The engine's PlannedActivity list does not
  // yet carry a financial-year stamp, so we currently treat the engine's
  // verified-count as the FY total — acceptable while every seeded
  // activity falls inside the active FY.
  // TODO: filter by FY once PlannedActivity carries a financial-year
  // marker. Continue to use `countsTowardTarget` for the canonical rule.
  const verifiedAnnualCount = kpis.verifiedCount;
  // Reference `countsTowardTarget` so the canonical helper is part of
  // this view's import graph even when the engine pre-computes the count.
  void countsTowardTarget;

  const firstName = userName.split(" ")[0];

  return (
    <>
      {/* ────────── Premium header — greeting + date + status chips ────────── */}
      <header className="relative pl-16 pr-4 pt-6 lg:pl-8 lg:pr-8 pb-5 overflow-hidden">
        {/* Subtle accent strip behind the header so the surface doesn't look
            blank when the cards start. */}
        <div
          aria-hidden
          className="absolute inset-x-0 top-0 h-[180px] bg-gradient-to-b from-[var(--color-edify-soft)]/60 via-[var(--color-edify-soft)]/20 to-transparent pointer-events-none"
        />
        <div className="relative flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0 flex-1 space-y-1">
            <div className="text-caption muted font-bold uppercase tracking-[0.18em] inline-flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-edify-primary)]" />
              My Targets · {kpis.monthLabel}
            </div>
            <h1 className="text-[24px] sm:text-[28px] lg:text-[32px] font-extrabold tracking-tight leading-[1.1]">
              {greetingForNow()}, <span className="text-[var(--color-edify-primary)]">{firstName}</span>.
            </h1>
            <p className="text-body muted">
              {formatTodayLong()} · Week {routePreview.week} of 4 · {kpis.thisWeekTodoCount} todo{kpis.thisWeekTodoCount === 1 ? "" : "s"} this week
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap shrink-0">
            {streak.current > 0 && (
              <span
                title={streak.best > streak.current ? `Best streak: ${streak.best} days` : undefined}
                className="inline-flex items-center gap-1.5 px-2.5 h-9 rounded-xl bg-gradient-to-br from-amber-100 to-amber-50 text-amber-800 text-[11.5px] font-extrabold whitespace-nowrap border border-amber-200/70 shadow-sm shadow-amber-500/10"
              >
                <Flame size={13} className="text-amber-600" />
                {streak.current}-day streak
              </span>
            )}
            {supervisorInterventionNeeded && (
              <span className="inline-flex items-center gap-1.5 px-2.5 h-9 rounded-xl bg-gradient-to-br from-rose-100 to-rose-50 text-rose-800 text-[11.5px] font-extrabold whitespace-nowrap border border-rose-200/70 shadow-sm shadow-rose-500/10">
                <AlertTriangle size={13} className="text-rose-600" />
                Supervisor support flagged
              </span>
            )}
          </div>
        </div>
      </header>

      <div className="px-4 sm:px-5 md:px-6 lg:px-8 pb-12 md:pb-8 space-y-4">

        {/* ────────── 0. Quick actions ────────── */}
        <QuickActionsRow
          onOpenRoute={() => scrollToId("route-map")}
          onFlagBlocker={() => setBlockerOpen(true)}
          onSubmitDebrief={() => scrollToId("daily-debrief")}
          verifiedToday={verifiedToday}
        />

        {/* ────────── 1. Hero KPI strip ────────── */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 auto-rows-fr">
          <HeroKpiCard
            Icon={Award}
            tone="edify"
            label="Monthly achievement"
            value={`${kpis.monthlyAchievementPct}%`}
            sub={`${kpis.completedCount} of ${kpis.plannedCount} activities`}
            accent={<ProgressRing pct={kpis.monthlyAchievementPct} />}
          />
          <HeroKpiCard
            Icon={CalendarRange}
            tone="violet"
            label="This Week progress"
            value={`${kpis.thisWeekProgressPct}%`}
            sub={`${kpis.thisWeekTodoCount} todo${kpis.thisWeekTodoCount === 1 ? "" : "s"} on the plan`}
            accent={<MiniBar pct={kpis.thisWeekProgressPct} color="#7c3aed" />}
          />
          <HeroKpiCard
            Icon={Wallet}
            tone="green"
            label="Budget requested"
            value={`UGX ${formatM(kpis.budgetRequestedUgx)}`}
            sub="Auto-aggregated from submitted activities"
            accent={<MiniBar pct={Math.min(100, Math.round((kpis.completedCount / Math.max(1, kpis.plannedCount)) * 100))} color="#059669" />}
          />
        </section>

        {/* ────────── 1b. Secondary stats ────────── */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 auto-rows-fr">
          <SecondaryStat Icon={ClipboardList} tone="sky"    label="Planned this month" value={kpis.plannedCount}            sub="Across staff visits, training, partners" />
          <SecondaryStat Icon={CheckCircle2}  tone="green"  label="Verified"           value={kpis.verifiedCount}           sub="Cleared Salesforce" />
          <SecondaryStat Icon={Database}      tone="amber"  label="Pending Salesforce" value={kpis.pendingSalesforceCount}  sub="Awaiting SF ID" />
          <SecondaryStat Icon={Footprints}    tone="violet" label="Annual coverage"    value={`${verifiedAnnualCount} / 560`} sub="Verified visits, this FY" />
        </section>

        {/* Weekly recap (visible Friday/Saturday only) */}
        {isFridayOrLater() && (
          <WeeklyRecapCard
            kpis={kpis}
            thisWeek={effectiveTodos}
            topBarriersCount={blockers.length}
          />
        )}

        {/* Inbound assignments from the PL — only renders when there
            are open items so the section disappears cleanly. */}
        <AssignedByPLCard userStaffId={userStaffId} />

        {/* ────────── 2 + 3. This Week — todos + map (equal height) ────────── */}
        <section className="grid grid-cols-12 gap-3 lg:items-stretch" id="this-week">
          <div className="col-span-12 lg:col-span-7 h-full">
            <ThisWeekTodoCard
              activities={filteredTodos}
              allCount={effectiveTodos.length}
              routePreview={routePreview}
              filter={todoFilter}
              onFilter={setTodoFilter}
              completions={completions}
              onComplete={(a) => setActiveCompletion(a)}
              onFlagBlocker={(a) => { setBlockerSchool({ id: a.schoolId, name: a.schoolName }); setBlockerOpen(true); }}
            />
          </div>
          <div className="col-span-12 lg:col-span-5 h-full" id="route-map">
            <ThisWeekClusterRoutePlanCard preview={routePreview} />
            {routePreview.missingCoordsCount > 0 && (
              <p className="text-[10px] muted leading-snug mt-2 px-1">
                Note: {routePreview.missingCoordsCount} school{routePreview.missingCoordsCount === 1 ? " is" : "s are"} missing
                a clustered location. They still appear under their assigned cluster — update the school register if a cluster is missing.
              </p>
            )}
          </div>
        </section>

        {/* ────────── 4. Monthly plan by week ────────── */}
        <section className="card p-3.5">
          <header className="flex items-baseline justify-between gap-2 mb-3 flex-wrap">
            <div>
              <h2 className="text-[15px] font-extrabold tracking-tight">Monthly plan by week</h2>
              <p className="text-caption muted mt-0.5">Auto-aggregated from submitted activity batches.</p>
            </div>
            <span className="text-caption muted whitespace-nowrap">{kpis.plannedCount} activities · UGX {formatM(kpis.budgetRequestedUgx)} estimated</span>
          </header>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3 auto-rows-fr">
            {weekBreakdown.map((w) => (
              <WeekBreakdownCard key={w.week} w={w} />
            ))}
          </div>
        </section>

        {/* ────────── 4b. Best performing CCEO this month ────────── */}
        <TopPerformerCard audience="cceo" show="ccoo-only" />

        {/* ────────── 5. Target progress bars ────────── */}
        <section className="card p-3.5">
          <header className="flex items-baseline justify-between gap-2 mb-3 flex-wrap">
            <div>
              <h2 className="text-[15px] font-extrabold tracking-tight">Target progress</h2>
              <p className="text-caption muted mt-0.5">Vertical marker shows expected pace by this week.</p>
            </div>
            <span className="text-caption muted whitespace-nowrap">
              Expected ~<span className="font-extrabold text-[var(--color-edify-text)]">{targets[0]?.expectedPct ?? 0}%</span> by week {routePreview.week}
            </span>
          </header>
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-3 auto-rows-fr">
            {targets.map((t) => (
              <TargetBarRow key={t.key} t={t} />
            ))}
          </ul>
        </section>

        {/* ────────── 6 + 7. Support + Daily debrief (balanced 2-col) ────────── */}
        <section className="grid grid-cols-12 gap-3 lg:items-stretch">
          <div className="col-span-12 lg:col-span-5 h-full">
            <SupportSection support={support} />
          </div>
          <div id="daily-debrief" className="col-span-12 lg:col-span-7 h-full">
            <DailyDebriefStrip activities={effectiveTodos} onSubmit={handleDebriefSubmit} />
          </div>
        </section>
      </div>

      {/* Floating "Flag a blocker" — visible everywhere on the page */}
      <button
        type="button"
        onClick={() => { setBlockerSchool({}); setBlockerOpen(true); }}
        aria-label="Flag a blocker right now"
        className="fixed bottom-6 right-6 z-30 h-14 w-14 sm:w-auto sm:px-5 sm:h-12 rounded-full bg-amber-500 hover:bg-amber-600 text-white shadow-xl shadow-amber-500/30 grid place-items-center sm:inline-flex sm:items-center sm:gap-2 ring-4 ring-amber-500/15 hover:ring-amber-500/25 transition-all"
      >
        <AlertTriangle size={18} />
        <span className="hidden sm:inline text-body font-extrabold tracking-tight">Flag a blocker</span>
      </button>

      {/* Win-moment toast */}
      {winToast && (
        <div className="fixed top-5 right-5 z-40 max-w-md animate-in fade-in slide-in-from-top-2 duration-300">
          <div className="rounded-xl bg-gradient-to-br from-emerald-500 to-emerald-600 text-white shadow-xl shadow-emerald-500/30 px-4 py-3 flex items-start gap-2.5 ring-1 ring-emerald-400/30">
            <span className="h-7 w-7 rounded-md bg-white/20 grid place-items-center shrink-0">
              <Trophy size={14} />
            </span>
            <div className="text-body leading-snug font-medium">{winToast}</div>
          </div>
        </div>
      )}

      {/* Modals */}
      {activeCompletion && (
        <SalesforceCompletionModal
          activity={activeCompletion}
          open
          onClose={() => setActiveCompletion(null)}
          onComplete={(c) => handleComplete(c)}
        />
      )}
      <RealtimeBlockerModal
        open={blockerOpen}
        defaultSchoolId={blockerSchool.id}
        defaultSchoolName={blockerSchool.name}
        onClose={() => setBlockerOpen(false)}
        onSubmit={(b) => handleBlocker(b)}
      />
    </>
  );
}

// ────────── This Week Todo Card ──────────

function ThisWeekTodoCard({
  activities, allCount, routePreview, filter, onFilter, completions, onComplete, onFlagBlocker,
}: {
  activities:    PlannedActivity[];
  allCount:      number;
  routePreview:  WeekRoutePreview;
  filter:        TodoFilter;
  onFilter:      (f: TodoFilter) => void;
  completions:   Record<string, VisitCompletion>;
  onComplete:    (a: PlannedActivity) => void;
  onFlagBlocker: (a: PlannedActivity) => void;
}) {
  return (
    <div className="card p-3.5 space-y-3 h-full flex flex-col">
      <header className="flex items-baseline justify-between gap-2 flex-wrap">
        <div>
          <div className="text-caption muted font-bold uppercase tracking-[0.14em]">Week {routePreview.week} · This Week&apos;s todo</div>
          <h2 className="text-[17px] font-extrabold tracking-tight mt-0.5">
            {activities.length}{filter !== "all" ? ` / ${allCount}` : ""} activit{activities.length === 1 ? "y" : "ies"} on your plan
          </h2>
        </div>
        <span className={cn(
          "inline-flex items-center px-2.5 h-7 rounded-md text-caption font-extrabold whitespace-nowrap border",
          FEASIBILITY_TONE[routePreview.feasibility],
        )}>
          {routePreview.feasibility}
        </span>
      </header>

      {/* Filter chips */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {(["all", "today", "week", "overdue", "critical"] as const).map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => onFilter(f)}
            className={cn(
              "h-8 px-3 rounded-full text-[11px] font-extrabold border whitespace-nowrap",
              filter === f
                ? "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)]"
                : "bg-white text-[var(--color-edify-text)] border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/40",
            )}
          >
            {FILTER_LABEL[f]}
          </button>
        ))}
      </div>

      {activities.length === 0 ? (
        <div className="rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 p-4 text-[12px] muted leading-snug">
          {allCount === 0
            ? "No activities scheduled for this week yet. Use Plan a Visit from My Plan to schedule schools and they will appear here."
            : `No activities match the ${FILTER_LABEL[filter]} filter. Reset to All to see everything.`}
        </div>
      ) : (
        <ul className="divide-y divide-[var(--color-edify-border)]">
          {activities.map((a) => (
            <TodoRow
              key={a.id}
              a={a}
              completion={completions[a.id]}
              onComplete={() => onComplete(a)}
              onFlagBlocker={() => onFlagBlocker(a)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

const FILTER_LABEL: Record<TodoFilter, string> = {
  all:      "All",
  today:    "Today",
  week:     "This Week",
  overdue:  "Overdue",
  critical: "Critical",
};

function filterTodos(activities: PlannedActivity[], f: TodoFilter): PlannedActivity[] {
  if (f === "all" || f === "week") return activities;
  const todayShort = new Date().toLocaleDateString("en-US", { weekday: "short" }).slice(0, 3);
  if (f === "today")    return activities.filter((a) => a.scheduledDay === todayShort);
  if (f === "overdue")  return activities.filter((a) => a.status === "Overdue");
  if (f === "critical") return activities.filter((a) => a.priority === "Critical" || a.status === "Overdue");
  return activities;
}

function TodoRow({
  a, completion, onComplete, onFlagBlocker,
}: {
  a:             PlannedActivity;
  completion?:   VisitCompletion;
  onComplete:    () => void;
  onFlagBlocker: () => void;
}) {
  const done = !!completion;
  const completable =
    !done &&
    a.status !== "Verified" &&
    a.status !== "Submitted for Verification";

  return (
    <li className="py-2.5 flex items-start gap-3 min-w-0">
      <span className={cn(
        "h-9 w-9 rounded-md grid place-items-center shrink-0",
        done                       ? "bg-emerald-500 text-white"
      : a.status === "Overdue"     ? "bg-rose-100    text-rose-700"
      : a.status === "Verified"    ? "bg-emerald-500 text-white"
      : a.status === "Completed"   ? "bg-emerald-100 text-emerald-700"
      :                              "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
      )}>
        {done || a.status === "Verified" ? <CheckCircle2 size={14} /> :
         a.status === "Overdue"          ? <AlertTriangle size={14} /> :
         <Footprints size={14} />}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline justify-between gap-2 min-w-0">
          <div className="text-[13px] font-extrabold tracking-tight truncate min-w-0 flex-1">{a.schoolName}</div>
          <span
            title={fullStatusLabel(a.status)}
            className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap shrink-0", STATUS_TONE[a.status])}
          >
            {shortStatusLabel(a.status)}
          </span>
        </div>
        <div className="text-caption muted truncate inline-flex items-center gap-1">
          <MapPin size={9} />
          {a.district} · {a.cluster} · {a.scheduledDay}
        </div>
        <div className="flex items-center gap-x-2 gap-y-1 flex-wrap mt-1">
          <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", TYPE_TONE[a.activityType])}>
            {a.activityType}
          </span>
          <span className="text-caption muted">Purpose: <span className="font-extrabold text-[var(--color-edify-text)]">{a.purpose}</span></span>
          {a.intervention && <span className="text-caption muted">· {a.intervention}</span>}
          {a.ssaScore != null && <span className="text-caption muted">· SSA {a.ssaScore}</span>}
          {a.trainingFollowUp && <span className="text-caption muted">· {a.trainingFollowUp}</span>}
        </div>
        <div className="flex items-center gap-x-3 gap-y-1 flex-wrap mt-1 text-caption">
          <span className="muted">Route: <span className="font-extrabold text-[var(--color-edify-text)]">{a.routeGroup}</span></span>
          {a.salesforceId
            ? <span className="muted">SF: <span className="font-mono font-extrabold text-[var(--color-edify-text)]">{a.salesforceId}</span></span>
            : a.needsSalesforce
              ? <span className="text-amber-800 font-extrabold inline-flex items-center gap-1"><Database size={9} />SF ID required</span>
              : null}
          <span className="ml-auto muted tabular">UGX {(a.estimatedCost / 1000).toFixed(0)}K</span>
        </div>

        {/* Completion preview */}
        {completion && (
          <div className="mt-2 rounded-lg bg-emerald-50/80 border border-emerald-200 px-2.5 py-1.5 text-caption text-emerald-900 leading-snug">
            <span className="font-extrabold">Submitted for Verification</span>
            <span className="mx-1">·</span>
            <span>{completion.salesforceIdKind}:</span>{" "}
            <span className="font-mono font-extrabold">{completion.salesforceId}</span>
            {completion.note && (
              <>
                <span className="mx-1">·</span>
                <span className="italic">{completion.note}</span>
              </>
            )}
            <span className="mx-1">·</span>
            <span className="muted">logged {completion.completedAt}</span>
          </div>
        )}

        {/* Action row */}
        <div className="mt-2 flex items-center gap-2 flex-wrap">
          {completable && (
            <button
              type="button"
              onClick={onComplete}
              className="h-8 px-2.5 rounded-md bg-emerald-500 hover:bg-emerald-600 text-white text-[11px] font-extrabold inline-flex items-center gap-1.5"
            >
              <CheckCircle2 size={11} />
              Complete visit
            </button>
          )}
          {!done && (
            <button
              type="button"
              onClick={onFlagBlocker}
              className="h-8 px-2.5 rounded-md border border-amber-300 bg-white text-amber-800 text-[11px] font-extrabold inline-flex items-center gap-1.5 hover:bg-amber-50"
            >
              <AlertTriangle size={11} />
              Flag a blocker here
            </button>
          )}
        </div>
      </div>
    </li>
  );
}









function greetingForNow(now: Date = new Date()): string {
  const h = now.getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function formatTodayLong(now: Date = new Date()): string {
  return now.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });
}

function scrollToId(id: string) {
  if (typeof document === "undefined") return;
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}

