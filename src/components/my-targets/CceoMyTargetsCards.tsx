// Larger card components extracted from CceoMyTargetsView. None of these
// hold state — they receive everything via props. They share a small set
// of internal helpers (FEASIBILITY_TONE, TARGET_STATUS_TONE, buildClusterPlan)
// that aren't useful outside this module.

import Link from "next/link";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  Eye,
  Lock,
  Map as MapIcon,
  Network,
  Plus,
  Sparkles,
  Trophy,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  MonthlyKpis,
  PlannedActivity,
  SupportSignal,
  TargetCategory,
  TargetStatus,
  WeekBreakdown,
  WeekRoutePreview,
} from "@/lib/cceo-my-targets-engine";
import { Fact, Strong, formatM, isToday } from "@/components/my-targets/CceoMyTargetsParts";

// ────────── Shared tones (private to this module) ──────────

const FEASIBILITY_TONE: Record<WeekRoutePreview["feasibility"], string> = {
  "Good Route":          "bg-emerald-50 text-emerald-700 border-emerald-200",
  "Manageable":          "bg-blue-50    text-blue-700    border-blue-200",
  "Heavy Travel":        "bg-amber-50   text-amber-800   border-amber-200",
  "Unrealistic":         "bg-rose-50    text-rose-700    border-rose-200",
  "Missing Coordinates": "bg-rose-50    text-rose-700    border-rose-200",
};

export { FEASIBILITY_TONE };

const TARGET_STATUS_TONE: Record<TargetStatus, { bar: string; chip: string; label: string; full: string }> = {
  "On Track":        { bar: "bg-emerald-500", chip: "bg-emerald-100 text-emerald-700", label: "On Track",      full: "On track for the period." },
  "Needs Attention": { bar: "bg-amber-500",   chip: "bg-amber-100   text-amber-800",   label: "Watch",          full: "Needs attention — falling behind expected pace." },
  "Critical":        { bar: "bg-rose-500",    chip: "bg-rose-100    text-rose-700",    label: "Critical",       full: "Critical — supervisor support flagged for this target." },
};

// ────────── Cluster route plan ──────────

type ClusterPlan = {
  cluster:    string;
  district:   string;
  schools:    PlannedActivity[];
  completed:  number;
  total:      number;
  pct:        number;
  hasCritical:boolean;
  hasOverdue: boolean;
  daysNeeded: number;
  dayRange:   string;
  priority:   number;
};

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri"] as const;

function buildClusterPlan(schools: PlannedActivity[]): ClusterPlan[] {
  const byCluster = new Map<string, PlannedActivity[]>();
  for (const a of schools) {
    if (!byCluster.has(a.cluster)) byCluster.set(a.cluster, []);
    byCluster.get(a.cluster)!.push(a);
  }

  const rows: ClusterPlan[] = Array.from(byCluster.entries()).map(([cluster, rs]) => {
    const completed = rs.filter(
      (a) =>
        a.status === "Completed" ||
        a.status === "Verified" ||
        a.status === "Submitted for Verification" ||
        a.status === "Salesforce ID Pending",
    ).length;
    const hasOverdue = rs.some((a) => a.status === "Overdue");
    const hasCritical = rs.some((a) => a.priority === "Critical");
    const priority = (hasOverdue ? 100 : 0) + (hasCritical ? 50 : 0) + rs.length;
    return {
      cluster,
      district: rs[0]?.district ?? "—",
      schools: rs,
      completed,
      total: rs.length,
      pct: rs.length === 0 ? 0 : Math.round((completed / rs.length) * 100),
      hasCritical,
      hasOverdue,
      daysNeeded: Math.max(1, Math.ceil(rs.length / 5)),
      dayRange: "",
      priority,
    };
  });

  rows.sort((a, b) => b.priority - a.priority);

  let cursor = 0;
  for (const r of rows) {
    const start = Math.min(cursor, 4);
    const end = Math.min(cursor + r.daysNeeded - 1, 4);
    r.dayRange = start === end ? DAY_NAMES[start] : `${DAY_NAMES[start]}–${DAY_NAMES[end]}`;
    cursor = end + 1;
  }
  return rows;
}

export function ThisWeekClusterRoutePlanCard({ preview }: { preview: WeekRoutePreview }) {
  if (preview.totalSchools === 0) {
    return (
      <div className="card p-3.5 h-full flex flex-col">
        <h3 className="text-caption font-extrabold tracking-[0.14em] uppercase muted mb-2 inline-flex items-center gap-2">
          <Network size={11} />
          Week {preview.week} cluster plan
        </h3>
        <div className="rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 p-4 text-[12px] muted leading-snug flex-1 grid place-items-center text-center">
          No schools scheduled for this week. Add schools from your monthly plan to generate a cluster route plan.
        </div>
      </div>
    );
  }
  const clusters = buildClusterPlan(preview.schools);
  const daysUsed = clusters.reduce((a, c) => a + c.daysNeeded, 0);
  return (
    <div className="card p-3.5 h-full flex flex-col gap-3">
      <header className="flex items-baseline justify-between gap-2 flex-wrap">
        <div>
          <h3 className="text-caption font-extrabold tracking-[0.14em] uppercase muted inline-flex items-center gap-2">
            <Network size={11} />
            Week {preview.week} cluster plan
          </h3>
          <p className="text-[10px] muted mt-0.5">Finish every visit in a cluster before moving to the next.</p>
        </div>
        <span
          className={cn(
            "inline-flex items-center px-2.5 h-7 rounded-md text-caption font-extrabold whitespace-nowrap border",
            FEASIBILITY_TONE[preview.feasibility],
          )}
        >
          {preview.feasibility}
        </span>
      </header>

      <ul className="grid grid-cols-3 gap-2 text-caption">
        <Fact label="Clusters this week" value={`${clusters.length}`} />
        <Fact label="Schools planned" value={`${preview.totalSchools}`} />
        <Fact label="Days needed" value={`${Math.min(5, daysUsed)}`} />
      </ul>

      <div className="rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 p-3">
        <div className="text-[10px] font-extrabold uppercase tracking-[0.12em] muted mb-1.5">Suggested order</div>
        <ol className="space-y-0.5 text-[12px] leading-snug">
          {clusters.map((c, i) => (
            <li key={c.cluster} className="flex items-baseline justify-between gap-2 min-w-0">
              <span className="min-w-0 flex-1 truncate">
                <span className="font-extrabold tabular text-[var(--color-edify-primary)] mr-1.5">{i + 1}.</span>
                <span className="font-extrabold">{c.cluster}</span>
                <span className="muted"> · {c.district}</span>
              </span>
              <span className="text-caption muted whitespace-nowrap font-extrabold tabular">
                {c.total} visit{c.total === 1 ? "" : "s"} · {c.dayRange}
              </span>
            </li>
          ))}
        </ol>
      </div>

      <ul className="flex-1 space-y-2 overflow-y-auto pr-1 -mr-1 max-h-[360px]">
        {clusters.map((c) => (
          <ClusterBlock key={c.cluster} c={c} />
        ))}
      </ul>
    </div>
  );
}

function ClusterBlock({ c }: { c: ClusterPlan }) {
  const tone =
    c.hasOverdue
      ? "border-rose-200  bg-rose-50/40"
      : c.hasCritical
        ? "border-amber-200 bg-amber-50/40"
        : c.pct === 100
          ? "border-emerald-200 bg-emerald-50/40"
          : "border-[var(--color-edify-border)] bg-white";
  return (
    <li className={cn("rounded-xl border p-3 space-y-2", tone)}>
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="text-body font-extrabold tracking-tight truncate inline-flex items-center gap-2">
            <Network size={11} className="text-[var(--color-edify-primary)]" />
            {c.cluster}
          </div>
          <div className="text-caption muted truncate">
            {c.district} · {c.total} school{c.total === 1 ? "" : "s"} · suggested {c.dayRange}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-body-lg font-extrabold tabular leading-none tracking-tight">{c.pct}%</div>
          <div className="text-[10px] muted mt-0.5">
            {c.completed}/{c.total} done
          </div>
        </div>
      </div>
      <div className="h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            c.pct === 100 ? "bg-emerald-500" : c.hasOverdue ? "bg-rose-500" : "bg-[var(--color-edify-primary)]",
          )}
          style={{ width: `${c.pct}%` }}
        />
      </div>
      <ul className="space-y-0.5">
        {c.schools.map((a) => (
          <SchoolMiniRow key={a.id} a={a} />
        ))}
      </ul>
    </li>
  );
}

function SchoolMiniRow({ a }: { a: PlannedActivity }) {
  const done =
    a.status === "Completed" ||
    a.status === "Verified" ||
    a.status === "Submitted for Verification" ||
    a.status === "Salesforce ID Pending";
  const overdue = a.status === "Overdue";
  return (
    <li className="flex items-center gap-2 text-[11px] py-0.5 min-w-0">
      <span
        className={cn(
          "h-4 w-4 rounded-full grid place-items-center text-white shrink-0",
          done
            ? "bg-emerald-500"
            : overdue
              ? "bg-rose-500"
              : "bg-[var(--color-edify-soft)]/80 ring-1 ring-[var(--color-edify-border)] text-[var(--color-edify-primary)]",
        )}
      >
        {done ? <CheckCircle2 size={9} /> : overdue ? <AlertTriangle size={9} /> : <span className="w-1 h-1 rounded-full bg-current" />}
      </span>
      <span className={cn("min-w-0 flex-1 truncate", done && "line-through muted")}>
        <span className="font-extrabold">{a.schoolName}</span>
        <span className="muted text-[10px]"> · {a.purpose}</span>
      </span>
      <span className="text-[9.5px] muted font-extrabold uppercase tracking-wide whitespace-nowrap shrink-0">
        {a.scheduledDay}
      </span>
    </li>
  );
}

// ────────── Week breakdown card ──────────

export function WeekBreakdownCard({ w }: { w: WeekBreakdown }) {
  const entries = Object.entries(w.byType).sort((a, b) => b[1] - a[1]);
  const pct = w.totalActivities === 0 ? 0 : Math.round((w.completed / w.totalActivities) * 100);
  return (
    <div
      className={cn(
        "rounded-2xl border p-4 h-full flex flex-col gap-2.5 transition-colors",
        w.isCurrent
          ? "border-[var(--color-edify-primary)] ring-2 ring-[var(--color-edify-primary)]/30 bg-gradient-to-br from-[var(--color-edify-soft)]/60 to-white shadow-sm shadow-[var(--color-edify-primary)]/5"
          : "border-[var(--color-edify-border)] bg-white",
      )}
    >
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-caption muted font-extrabold uppercase tracking-[0.14em]">Week {w.week}</div>
        {w.isCurrent && (
          <span className="text-[10px] font-extrabold uppercase tracking-wide px-2 py-[2px] rounded-md bg-[var(--color-edify-primary)] text-white">
            This Week
          </span>
        )}
      </div>
      <div className="flex items-end justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[22px] font-extrabold tabular leading-none tracking-tight">{w.totalActivities}</div>
          <div className="text-caption muted truncate mt-1">activities · UGX {formatM(w.estimatedCost)}</div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-body-lg font-extrabold tabular leading-none tracking-tight text-emerald-700">{pct}%</div>
          <div className="text-[10px] muted mt-1">
            {w.completed}/{w.totalActivities} done
          </div>
        </div>
      </div>
      <div className="h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
        <div className="h-full rounded-full bg-emerald-500" style={{ width: `${pct}%` }} />
      </div>
      <ul className="space-y-0.5 text-[11px] pt-1 mt-auto border-t border-[var(--color-edify-border)]/60">
        {entries.length === 0 && <li className="muted pt-1">Nothing planned</li>}
        {entries.slice(0, 5).map(([type, n]) => (
          <li key={type} className="flex items-baseline justify-between gap-2 pt-1">
            <span className="truncate">{type}</span>
            <span className="font-extrabold tabular shrink-0">{n}</span>
          </li>
        ))}
        {entries.length > 5 && <li className="muted text-[10px] pt-1">+ {entries.length - 5} more</li>}
      </ul>
    </div>
  );
}

// ────────── Target progress bar ──────────

export function TargetBarRow({ t }: { t: TargetCategory }) {
  const tone = TARGET_STATUS_TONE[t.status];
  return (
    <li className="rounded-xl border border-[var(--color-edify-border)] p-3.5 space-y-2 hover:border-[var(--color-edify-primary)]/40 transition-colors">
      <div className="flex items-baseline justify-between gap-2 min-w-0">
        <div className="min-w-0 flex-1">
          <div className="text-body font-extrabold tracking-tight truncate">{t.label}</div>
          <div className="text-caption muted">
            <span className="font-extrabold text-[var(--color-edify-text)] tabular">{t.completed}</span>
            <span className="muted">
              {" "}
              / {t.target} · expected {t.expectedPct}%
            </span>
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[18px] font-extrabold tabular leading-none tracking-tight">{t.pct}%</div>
          <span
            title={tone.full}
            className={cn(
              "inline-flex items-center mt-1 px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap",
              tone.chip,
            )}
          >
            {tone.label}
          </span>
        </div>
      </div>
      <div className="relative h-2 rounded-full bg-[#eef2f4] overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", tone.bar)} style={{ width: `${t.pct}%` }} />
        <div
          className="absolute top-[-3px] bottom-[-3px] w-[2px] bg-slate-700 rounded-full"
          style={{ left: `${t.expectedPct}%` }}
          title={`Expected ~${t.expectedPct}%`}
        />
      </div>
      <div className="text-[10px] muted text-right tabular">{t.trend}</div>
    </li>
  );
}

// ────────── Support row + section ──────────

function SupportRow({ signal }: { signal: SupportSignal }) {
  return (
    <li
      className={cn(
        "rounded-xl border p-3 flex items-start gap-2",
        signal.severity === "critical" ? "border-rose-200 bg-rose-50/60" : "border-amber-200 bg-amber-50/60",
      )}
    >
      {signal.severity === "critical" ? (
        <Lock size={12} className="text-rose-700 mt-0.5 shrink-0" />
      ) : (
        <AlertTriangle size={12} className="text-amber-700 mt-0.5 shrink-0" />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span
            className={cn(
              "text-[12px] font-extrabold tracking-tight",
              signal.severity === "critical" ? "text-rose-800" : "text-amber-900",
            )}
          >
            {signal.reason}
          </span>
          <span className="text-[10px] muted uppercase font-bold tracking-wide">{signal.severity}</span>
        </div>
        <p className="text-[11px] muted leading-snug mt-0.5">{signal.detail}</p>
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-caption">
          <button
            type="button"
            className="h-7 px-2 rounded-md bg-white border border-[var(--color-edify-border)] font-extrabold hover:bg-[var(--color-edify-soft)]/40"
          >
            Open in My Plan
          </button>
          <button
            type="button"
            className="h-7 px-2 rounded-md bg-white border border-[var(--color-edify-border)] font-extrabold hover:bg-[var(--color-edify-soft)]/40"
          >
            Notify Program Lead
          </button>
        </div>
      </div>
    </li>
  );
}

export function SupportSection({ support }: { support: SupportSignal[] }) {
  const hasCritical = support.some((s) => s.severity === "critical");
  return (
    <section
      className={cn(
        "card p-3.5 h-full flex flex-col gap-3",
        hasCritical && "border-rose-200 bg-rose-50/30",
      )}
    >
      <header className="flex items-baseline justify-between gap-2 flex-wrap">
        <div>
          <h2 className="text-[15px] font-extrabold tracking-tight inline-flex items-center gap-2">
            <Eye size={15} className="text-[var(--color-edify-primary)]" />
            Needs attention
          </h2>
          <p className="text-caption muted mt-0.5">Supervisor-visible signals from your week.</p>
        </div>
        <span
          className={cn(
            "inline-flex items-center px-2 h-7 rounded-md text-caption font-extrabold whitespace-nowrap border",
            support.length === 0
              ? "bg-emerald-50 text-emerald-700 border-emerald-200"
              : hasCritical
                ? "bg-rose-50 text-rose-700 border-rose-200"
                : "bg-amber-50 text-amber-800 border-amber-200",
          )}
        >
          {support.length === 0 ? "All clear" : `${support.length} signal${support.length === 1 ? "" : "s"}`}
        </span>
      </header>
      {support.length === 0 ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-4 flex items-start gap-2 flex-1">
          <CheckCircle2 size={16} className="text-emerald-600 mt-0.5 shrink-0" />
          <div className="text-body text-emerald-900 leading-snug">
            <div className="font-extrabold">No supervisor flags right now.</div>
            <div className="text-caption muted mt-0.5">
              Progress is on pace, evidence is flowing, no blockers reported.
            </div>
          </div>
        </div>
      ) : (
        <ul className="space-y-2 flex-1">
          {support.map((s) => (
            <SupportRow key={s.id} signal={s} />
          ))}
        </ul>
      )}
    </section>
  );
}

// ────────── Quick actions row ──────────

export function QuickActionsRow({
  onOpenRoute,
  onFlagBlocker,
  onSubmitDebrief,
  verifiedToday,
}: {
  onOpenRoute: () => void;
  onFlagBlocker: () => void;
  onSubmitDebrief: () => void;
  verifiedToday: number;
}) {
  return (
    <section className="card rounded-2xl p-3 flex items-center gap-2 flex-wrap">
      <span className="text-[10px] muted font-extrabold uppercase tracking-[0.14em] mr-1 hidden sm:inline">
        Right now
      </span>
      <span aria-hidden className="hidden sm:inline h-5 w-px bg-[var(--color-edify-border)] mr-1" />
      <Link
        href="/plans/new"
        className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] text-white text-[12px] font-extrabold inline-flex items-center gap-1.5 hover:brightness-110 shadow-sm shadow-[var(--color-edify-primary)]/20"
      >
        <Plus size={13} />
        Plan a visit
      </Link>
      <button
        type="button"
        onClick={onOpenRoute}
        className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white text-[12px] font-extrabold inline-flex items-center gap-1.5 hover:bg-[var(--color-edify-soft)]/40 hover:border-[var(--color-edify-primary)]/40 transition-colors"
      >
        <MapIcon size={13} className="text-[var(--color-edify-primary)]" />
        Open today&apos;s route
      </button>
      <button
        type="button"
        onClick={onSubmitDebrief}
        className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white text-[12px] font-extrabold inline-flex items-center gap-1.5 hover:bg-[var(--color-edify-soft)]/40 hover:border-[var(--color-edify-primary)]/40 transition-colors"
      >
        <Brain size={13} className="text-[var(--color-edify-primary)]" />
        Submit Debrief
      </button>
      <button
        type="button"
        onClick={onFlagBlocker}
        className="h-9 px-3 rounded-xl border border-amber-300 bg-amber-50/60 text-amber-800 text-[12px] font-extrabold inline-flex items-center gap-1.5 hover:bg-amber-50 transition-colors"
      >
        <AlertTriangle size={13} />
        Flag a blocker
      </button>
      <span className="ml-auto inline-flex items-center gap-1.5 text-[11px] font-extrabold">
        {verifiedToday > 0 ? (
          <span className="inline-flex items-center gap-1.5 px-2.5 h-7 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
            <Trophy size={11} className="text-amber-500" />
            {verifiedToday} completed today
          </span>
        ) : (
          <span className="muted">0 completed today</span>
        )}
      </span>
    </section>
  );
}

// ────────── Weekly recap card (Fri/Sat only) ──────────

export function WeeklyRecapCard({
  kpis,
  thisWeek,
  topBarriersCount,
}: {
  kpis: MonthlyKpis;
  thisWeek: PlannedActivity[];
  topBarriersCount: number;
}) {
  const planned = thisWeek.length;
  const completed = thisWeek.filter(
    (a) =>
      a.status === "Completed" ||
      a.status === "Verified" ||
      a.status === "Submitted for Verification" ||
      a.status === "Salesforce ID Pending",
  ).length;
  const verified = thisWeek.filter((a) => a.status === "Verified").length;
  const carryOver = thisWeek.filter(
    (a) => a.status === "Planned" || a.status === "Ready" || a.status === "Overdue" || a.status === "Returned",
  ).length;
  const pct = planned === 0 ? 0 : Math.round((completed / planned) * 100);

  return (
    <section className="card p-3.5 space-y-3 border-[var(--color-edify-primary)]/30 bg-[var(--color-edify-soft)]/20">
      <header className="flex items-baseline justify-between gap-2 flex-wrap">
        <div>
          <div className="text-caption muted font-bold uppercase tracking-wider">Weekly recap</div>
          <h2 className="text-[15px] font-extrabold tracking-tight">Your week, in one read</h2>
        </div>
        <span className="text-caption muted">
          Auto-generated for Fri / Sat · feeds your Program Lead&apos;s weekly report
        </span>
      </header>
      <p className="text-[13px] leading-relaxed">
        You planned <Strong>{planned}</Strong> activit{planned === 1 ? "y" : "ies"} this week and completed{" "}
        <Strong>{completed}</Strong> ({pct}%). Verified so far: <Strong>{verified}</Strong>.
        {kpis.pendingSalesforceCount > 0 && (
          <>
            {" "}
            Pending Salesforce: <Strong className="text-amber-700">{kpis.pendingSalesforceCount}</Strong>.
          </>
        )}
        {topBarriersCount > 0 && (
          <>
            {" "}
            Blockers raised this week: <Strong className="text-rose-700">{topBarriersCount}</Strong>.
          </>
        )}
      </p>
      {carryOver > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-3 flex items-start gap-2 text-[12px] text-amber-900">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          <div className="leading-snug">
            <span className="font-extrabold">
              {carryOver} activit{carryOver === 1 ? "y" : "ies"} will carry over to next week
            </span>{" "}
            if not completed by end of Saturday. Open Plan a Visit to confirm or reschedule them now.
          </div>
        </div>
      )}
    </section>
  );
}

// ────────── Daily debrief reminder strip ──────────

export function DailyDebriefStrip({
  activities,
  onSubmit,
}: {
  activities: PlannedActivity[];
  onSubmit: () => void;
}) {
  const todays = activities.filter((a) => isToday(a));
  const completed = todays.filter(
    (a) =>
      a.status === "Completed" ||
      a.status === "Verified" ||
      a.status === "Submitted for Verification" ||
      a.status === "Salesforce ID Pending",
  );
  const incomplete = todays.filter((a) => !completed.includes(a));
  const overdue = todays.filter((a) => a.status === "Overdue");

  const seed =
    todays.length === 0
      ? "No activities were planned for today."
      : `I planned ${todays.length} activit${todays.length === 1 ? "y" : "ies"} today and completed ${completed.length}.${
          incomplete.length === 0
            ? " All visits closed out on time."
            : ` ${incomplete.length} did not complete${overdue.length > 0 ? ` (${overdue.length} overdue)` : ""} because…\n` +
              `\nIncomplete:\n` +
              incomplete.map((a) => `• ${a.schoolName} — ${a.activityType} (${a.status})`).join("\n")
        }`;

  return (
    <section className="card p-3.5 bg-gradient-to-br from-[var(--color-edify-soft)]/40 to-white border-[var(--color-edify-primary)]/25 h-full flex flex-col gap-3">
      <header className="flex items-start gap-3 flex-wrap">
        <div className="h-11 w-11 rounded-xl bg-[var(--color-edify-primary)]/10 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
          <Brain size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-extrabold tracking-tight">Daily Field Debrief</h2>
          <p className="text-[11px] muted leading-snug mt-0.5">
            Pre-filled from your todo list — finish the sentence so your Program Lead understands the field context.
            Voice-to-text supported.
          </p>
        </div>
        <button
          type="button"
          onClick={onSubmit}
          className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] text-white text-[12px] font-extrabold inline-flex items-center gap-1.5 hover:brightness-110 shrink-0 shadow-sm shadow-[var(--color-edify-primary)]/20"
        >
          <Sparkles size={13} />
          Submit Debrief
        </button>
      </header>
      <textarea
        aria-label="Daily field debrief"
        defaultValue={seed}
        rows={Math.min(8, Math.max(4, seed.split("\n").length))}
        className="w-full flex-1 min-h-[120px] rounded-xl border border-[var(--color-edify-border)] bg-white px-3 py-2.5 text-[12px] leading-relaxed focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30 resize-none"
      />
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[10px] muted font-extrabold uppercase tracking-[0.12em] mr-1">Quick blockers:</span>
        {["School closed", "Funding delay", "Route impassable", "Partner no-show", "Salesforce backlog", "Leave / holiday"].map(
          (b) => (
            <button
              key={b}
              type="button"
              className="h-7 px-2.5 rounded-full border border-[var(--color-edify-border)] bg-white text-caption font-extrabold hover:bg-[var(--color-edify-soft)]/40 hover:border-[var(--color-edify-primary)]/40 transition-colors"
            >
              + {b}
            </button>
          ),
        )}
      </div>
    </section>
  );
}
