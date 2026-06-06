"use client";

// ClusterActivityProfileDrawer — answers a single question for the
// CCEO / PL: "What has happened in this cluster, how are the schools
// performing, what has been delivered, which schools are ready to
// grow into core/champion status, and how much has been spent?"
//
// Compact (size="md") tabbed drawer matching the SchoolActivityProfile
// pattern. Tabs: Overview · Meetings · Trainings · SSA · School
// Potential · Costs · Evidence · Next Actions.

import { useMemo, useState } from "react";
import { formatUgxCompact as formatUgx, formatHumanDate } from "@/lib/format-utils";
import {
  Users, GraduationCap, ClipboardList, Sparkles, MapPin, Receipt,
  ShieldCheck, ListTree, ChevronRight, Wallet, Award, AlertTriangle,
  Calendar, CheckCircle2, CalendarCheck,
  type LucideIcon,
} from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import type { ClusterGap, ClusterMeetingStatus, ClusterMeetingSlot, SchoolGap } from "@/lib/planning/planning-gaps-mock";
import {
  buildClusterActivitySummary,
  ssaStatusFor,
  type ClusterActivityInvestmentSummary,
  type ClusterMeetingSummary,
  type ClusterTrainingSummary,
  type ClusterNextAction,
} from "@/lib/planning/cluster-activity-mock";
import { CURRENT_CYCLE, EVIDENCE_LABEL, type SummaryScope, type EvidenceStatus } from "@/lib/planning/school-activity-mock";
import type { SsaStatus } from "@/lib/planning/ssa-performance-mock";

// ────────── Types ──────────

export type ClusterActivityProfileContext = {
  cluster: ClusterGap;
};

const TABS = ["overview", "meetings", "trainings", "ssa", "potential", "costs", "evidence", "next"] as const;
type TabKey = typeof TABS[number];
const TAB_LABEL: Record<TabKey, string> = {
  overview:  "Overview",
  meetings:  "Meetings",
  trainings: "Trainings",
  ssa:       "SSA",
  potential: "Potential",
  costs:     "Costs",
  evidence:  "Evidence",
  next:      "Next",
};
const TAB_ICON: Record<TabKey, LucideIcon> = {
  overview:  Sparkles,
  meetings:  Calendar,
  trainings: GraduationCap,
  ssa:       ClipboardList,
  potential: Award,
  costs:     Receipt,
  evidence:  ShieldCheck,
  next:      ListTree,
};

// ────────── Visual tokens ──────────

const STATUS_TONE: Record<SsaStatus, { bg: string; text: string }> = {
  "Critical":      { bg: "bg-rose-50",    text: "text-rose-700"    },
  "Needs Support": { bg: "bg-amber-50",   text: "text-amber-700"   },
  "Good":          { bg: "bg-emerald-50", text: "text-emerald-700" },
  "Strong":        { bg: "bg-emerald-100",text: "text-emerald-800" },
};
const MEETING_TONE: Record<ClusterMeetingStatus, { bg: string; text: string }> = {
  Completed:    { bg: "bg-emerald-100", text: "text-emerald-800" },
  Scheduled:    { bg: "bg-sky-50",      text: "text-sky-700"     },
  Rescheduled:  { bg: "bg-amber-50",    text: "text-amber-700"   },
  Missing:      { bg: "bg-rose-50",     text: "text-rose-700"    },
  "Not Yet Due":{ bg: "bg-slate-100",   text: "text-slate-600"   },
};

// ────────── Component ──────────

export function ClusterActivityProfileDrawer({
  open, context, onClose, onAction,
}: {
  open: boolean;
  context: ClusterActivityProfileContext | null;
  onClose: () => void;
  onAction?: (action: ClusterNextAction["action"], schoolId?: string) => void;
}) {
  const [scope, setScope] = useState<SummaryScope>("current_cycle");
  const [tab, setTab]     = useState<TabKey>("overview");

  const cluster = context?.cluster ?? null;
  const summary = useMemo<ClusterActivityInvestmentSummary | null>(() => {
    if (!cluster) return null;
    return buildClusterActivitySummary(cluster, scope);
  }, [cluster, scope]);

  if (!context || !cluster || !summary) return null;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Cluster Activity & Investment"
      description="Meetings, trainings, SSA, school growth, evidence, and cost."
      variant="drawer-right"
      size="md"
      footer={
        <div className="flex items-center justify-between gap-2 w-full">
          <ScopeToggle scope={scope} onChange={setScope} />
          <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
        </div>
      }
    >
      <div className="space-y-2.5">

        {/* Cluster identity card */}
        <section className="rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 px-2.5 py-2 flex items-start gap-2">
          <span className="grid place-items-center h-7 w-7 rounded-md bg-white text-[var(--color-edify-primary)] shrink-0 border border-[var(--color-edify-border)]">
            <Users size={12} />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="text-body font-extrabold tracking-tight truncate">{cluster.clusterName}</h3>
            <div className="text-caption muted leading-tight inline-flex items-center gap-1 flex-wrap">
              <MapPin size={9} className="text-[var(--color-edify-primary)]" />
              {cluster.district}
              <span className="opacity-50">·</span>
              CCEO {cluster.assignedCceo}
              {cluster.partnerFacilitator && (
                <>
                  <span className="opacity-50">·</span>
                  Partner {cluster.partnerFacilitator}
                </>
              )}
            </div>
            <div className="text-caption muted mt-0.5 inline-flex items-center gap-2 flex-wrap">
              <span>{summary.memberSchools.length} schools</span>
              <span className="opacity-40">·</span>
              <span>{summary.operationalCycle}</span>
              <span className="opacity-40">·</span>
              <span>Health <span className={cn("font-extrabold tabular", healthColor(summary.healthScore))}>{summary.healthScore}%</span></span>
            </div>
          </div>
        </section>

        {/* Tab nav */}
        <nav role="tablist" className="flex items-center gap-0.5 border-b border-[var(--color-edify-divider)] overflow-x-auto -mx-1 px-1">
          {TABS.map((t) => {
            const Icon = TAB_ICON[t];
            const isActive = t === tab;
            return (
              <button
                key={t}
                role="tab"
                aria-selected={isActive}
                type="button"
                onClick={() => setTab(t)}
                className={cn(
                  "inline-flex items-center gap-1 px-2 h-7 text-[11px] font-extrabold tracking-tight whitespace-nowrap border-b-2 -mb-px transition-colors",
                  isActive
                    ? "border-[var(--color-edify-primary)] text-[var(--color-edify-text)]"
                    : "border-transparent text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]",
                )}
              >
                <Icon size={10} />
                {TAB_LABEL[t]}
              </button>
            );
          })}
        </nav>

        {/* Tab body */}
        {tab === "overview"  && <OverviewTab summary={summary} />}
        {tab === "meetings"  && <MeetingsTab summary={summary} onAction={onAction} />}
        {tab === "trainings" && <TrainingsTab summary={summary} />}
        {tab === "ssa"       && <SsaTab summary={summary} />}
        {tab === "potential" && <PotentialTab summary={summary} onAction={onAction} />}
        {tab === "costs"     && <CostsTab summary={summary} />}
        {tab === "evidence"  && <EvidenceTab summary={summary} />}
        {tab === "next"      && <NextActionsTab summary={summary} onAction={onAction} />}
      </div>
    </Modal>
  );
}

// ────────── Scope toggle ──────────

function ScopeToggle({ scope, onChange }: { scope: SummaryScope; onChange: (s: SummaryScope) => void }) {
  return (
    <div className="inline-flex items-center rounded-md border border-[var(--color-edify-border)] bg-white p-0.5 text-[11px] font-semibold">
      {(["current_cycle", "all_time"] as const).map((s) => (
        <button
          key={s}
          type="button"
          onClick={() => onChange(s)}
          className={cn(
            "h-7 px-2.5 rounded transition-colors",
            scope === s
              ? "bg-[var(--color-edify-primary)] text-white"
              : "text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60",
          )}
        >
          {s === "current_cycle" ? `Current cycle (${CURRENT_CYCLE})` : "All time"}
        </button>
      ))}
    </div>
  );
}

// ────────── OVERVIEW TAB ──────────

function OverviewTab({ summary }: { summary: ClusterActivityInvestmentSummary }) {
  const t = summary.totals;
  const nextAction = summary.nextActions[0];
  return (
    <div className="space-y-2.5">
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-1.5">
        <Kpi label="Schools"            value={String(t.schoolsInCluster)} />
        <Kpi label="Meetings"           value={`${t.meetingsHeld} held`} sub={t.meetingsScheduled > 0 ? `${t.meetingsScheduled} scheduled` : undefined} />
        <Kpi label="Trainings"          value={String(t.trainingsHeld)} />
        <Kpi label="SSA"                value={`${t.ssaCompleted}/${t.schoolsInCluster}`} sub="completed" />
        <Kpi label="Core potential"     value={String(t.corePotentialSchools)} tone={t.corePotentialSchools > 0 ? "good" : "neutral"} />
        <Kpi label="Champion potential" value={String(t.championPotentialSchools)} tone={t.championPotentialSchools > 0 ? "good" : "neutral"} />
        <Kpi label="Total spent"        value={formatUgx(t.totalSpent)} tone="primary" />
        <Kpi label="Health"             value={`${summary.healthScore}%`} tone={summary.healthScore >= 70 ? "good" : summary.healthScore >= 50 ? "warn" : "warn"} />
      </section>

      {/* Cluster health breakdown */}
      <section className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <HealthList title="Strong"          tone="good" items={summary.healthBreakdown.strong} fallback="No strengths recorded yet." />
        <HealthList title="Needs attention" tone="warn" items={summary.healthBreakdown.needsAttention} fallback="No issues flagged." />
      </section>

      {nextAction && (
        <section className="rounded-md border border-[var(--color-edify-divider)] bg-white px-2.5 py-2 flex items-center gap-2">
          <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
            <Sparkles size={11} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[9.5px] uppercase tracking-wider font-bold muted">Next recommended action</div>
            <p className="text-[11.5px] font-extrabold tracking-tight leading-tight mt-0.5">{nextAction.title}</p>
          </div>
        </section>
      )}
    </div>
  );
}

function HealthList({
  title, tone, items, fallback,
}: {
  title: string;
  tone: "good" | "warn";
  items: string[];
  fallback: string;
}) {
  const t = tone === "good"
    ? { bg: "bg-emerald-50", text: "text-emerald-700", Icon: CheckCircle2 }
    : { bg: "bg-amber-50",   text: "text-amber-700",   Icon: AlertTriangle };
  return (
    <section className="rounded-lg border border-[var(--color-edify-divider)] bg-white p-2.5">
      <header className="flex items-center gap-1.5 mb-1">
        <span className={cn("grid place-items-center h-5 w-5 rounded", t.bg, t.text)}>
          <t.Icon size={10} />
        </span>
        <h4 className="text-[11.5px] font-extrabold tracking-tight">{title}</h4>
      </header>
      {items.length === 0 ? (
        <p className="text-caption muted">{fallback}</p>
      ) : (
        <ul className="space-y-0.5 text-caption">
          {items.map((it, i) => (
            <li key={i} className="flex items-start gap-1.5">
              <span className={cn("h-1 w-1 rounded-full mt-1.5 shrink-0", tone === "good" ? "bg-emerald-500" : "bg-amber-500")} />
              <span>{it}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ────────── MEETINGS TAB ──────────

function MeetingsTab({
  summary, onAction,
}: {
  summary: ClusterActivityInvestmentSummary;
  onAction?: (action: ClusterNextAction["action"]) => void;
}) {
  return (
    <div className="space-y-1.5">
      {summary.meetings.map((m) => <MeetingCard key={m.id} meeting={m} onAction={onAction} />)}
    </div>
  );
}

function MeetingCard({
  meeting: m, onAction,
}: {
  meeting: ClusterMeetingSummary;
  onAction?: (action: ClusterNextAction["action"]) => void;
}) {
  const tone = MEETING_TONE[m.status];
  const scheduleAction = scheduleActionFor(m.meetingType);
  return (
    <section className="rounded-md border border-[var(--color-edify-divider)] bg-white px-2.5 py-2">
      <header className="flex items-center justify-between gap-2 mb-1">
        <h5 className="text-[11.5px] font-extrabold tracking-tight">{m.meetingLabel}</h5>
        <span className={cn("inline-flex items-center px-1.5 py-[1px] rounded text-[9.5px] font-extrabold uppercase tracking-wide", tone.bg, tone.text)}>
          {m.status}
        </span>
      </header>
      {m.status === "Missing" ? (
        <div className="flex items-center justify-between gap-2">
          <p className="text-caption muted">Not scheduled.</p>
          {scheduleAction && onAction && (
            <Button size="sm" variant="secondary" onClick={() => onAction(scheduleAction)} Icon={CalendarCheck}>Schedule</Button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-caption">
          {m.scheduledDate && <Field label="Date" value={m.scheduledDate} />}
          {m.facilitator   && <Field label="Facilitator" value={m.facilitator} />}
          {m.participants  !== undefined && <Field label="Participants" value={String(m.participants)} />}
          {m.schoolsRepresented !== undefined && <Field label="Schools" value={String(m.schoolsRepresented)} />}
          <Field label="Evidence" value={EVIDENCE_LABEL[m.evidenceStatus]} />
          <Field label="Cost"     value={formatUgx(m.cost)} />
        </div>
      )}
    </section>
  );
}

function scheduleActionFor(slot: ClusterMeetingSlot): ClusterNextAction["action"] | undefined {
  if (slot === "first")  return "schedule_first";
  if (slot === "second") return "schedule_second";
  if (slot === "third")  return "schedule_third";
  if (slot === "sit")    return "schedule_sit";
  return undefined;
}

// ────────── TRAININGS TAB ──────────

function TrainingsTab({ summary }: { summary: ClusterActivityInvestmentSummary }) {
  return (
    <div className="space-y-2.5">
      {/* Intervention coverage table — quick "where are the gaps?" view */}
      <section className="rounded-lg border border-[var(--color-edify-divider)] bg-white p-2.5">
        <header className="mb-1">
          <h4 className="text-[12px] font-extrabold tracking-tight">Training coverage by intervention</h4>
          <p className="text-[10px] muted mt-0.5 leading-tight">Match trainings to SSA weakness areas.</p>
        </header>
        <div className="overflow-x-auto -mx-2.5">
          <table className="w-full text-caption">
            <thead>
              <tr className="text-left text-[9.5px] uppercase tracking-wider font-bold text-[var(--color-edify-muted)] border-b border-[var(--color-edify-divider)]">
                <th className="px-2.5 py-1">Intervention</th>
                <th className="px-2.5 py-1 text-right">Trainings</th>
                <th className="px-2.5 py-1 text-right">Schools</th>
                <th className="px-2.5 py-1">Latest</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {summary.interventionCoverage.map((row) => (
                <tr key={row.intervention}>
                  <td className="px-2.5 py-1 font-extrabold text-[var(--color-edify-text)]">{row.intervention}</td>
                  <td className="px-2.5 py-1 text-right tabular muted">{row.trainingsHeld}</td>
                  <td className="px-2.5 py-1 text-right tabular muted">{row.schoolsReached}</td>
                  <td className="px-2.5 py-1 tabular muted">{row.latestTraining ? formatHumanDate(row.latestTraining) : <span className="text-rose-600 font-extrabold">Not yet</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Per-training cards */}
      {summary.trainings.length === 0 ? (
        <p className="text-[11px] muted px-1">No trainings recorded in this scope.</p>
      ) : (
        <div className="space-y-1.5">
          {summary.trainings.map((t) => <TrainingCard key={t.id} training={t} />)}
        </div>
      )}
    </div>
  );
}

function TrainingCard({ training: t }: { training: ClusterTrainingSummary }) {
  return (
    <section className="rounded-md border border-[var(--color-edify-divider)] bg-white px-2.5 py-2">
      <header className="flex items-start justify-between gap-2 mb-1">
        <div className="min-w-0">
          <h5 className="text-[11.5px] font-extrabold tracking-tight truncate">{t.trainingTitle}</h5>
          <p className="text-[10px] muted leading-tight mt-0.5">
            {t.intervention} · {formatHumanDate(t.date)}
          </p>
        </div>
        <span className="text-[11.5px] font-extrabold tabular text-[var(--color-edify-text)] shrink-0">{formatUgx(t.cost)}</span>
      </header>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-caption">
        {t.facilitator        && <Field label="Facilitator"   value={t.facilitator} />}
        {t.partnerFacilitator && <Field label="Partner"       value={t.partnerFacilitator} />}
        <Field label="Schools"      value={`${t.schoolsRepresented} of cluster`} />
        <Field label="Participants" value={String(t.participants)} />
        <Field label="Evidence"     value={EVIDENCE_LABEL[t.evidenceStatus]} />
        {t.followUpRequiredSchools && <Field label="Follow-Up" value={`required for ${t.followUpRequiredSchools} school${t.followUpRequiredSchools === 1 ? "" : "s"}`} />}
      </div>
    </section>
  );
}

// ────────── SSA TAB ──────────

function SsaTab({ summary }: { summary: ClusterActivityInvestmentSummary }) {
  const p = summary.ssaPerformance;
  const hasAny = p.averages.some((a) => a.score > 0);

  if (!hasAny) {
    return (
      <section className="rounded-lg border border-rose-200 bg-rose-50/40 p-3 text-center">
        <span className="inline-grid place-items-center h-7 w-7 rounded-md bg-rose-100 text-rose-700 mb-1">
          <ClipboardList size={12} />
        </span>
        <h4 className="text-[12px] font-extrabold tracking-tight">No SSA on record yet for this cluster</h4>
        <p className="text-caption muted mt-1 max-w-md mx-auto leading-snug">
          Cluster trainings stay locked until at least one member school completes a current-cycle SSA.
        </p>
      </section>
    );
  }

  return (
    <div className="space-y-2.5">
      {/* Highlight row */}
      <section className="grid grid-cols-2 gap-1.5">
        {p.weakestIntervention && (
          <Kpi label="Weakest cluster intervention" value={`${p.weakestIntervention.score}/10`} sub={p.weakestIntervention.intervention} tone="warn" />
        )}
        {p.strongestIntervention && (
          <Kpi label="Strongest cluster intervention" value={`${p.strongestIntervention.score}/10`} sub={p.strongestIntervention.intervention} tone="good" />
        )}
      </section>

      {/* Cluster-wide average bars */}
      <section className="rounded-lg border border-[var(--color-edify-divider)] bg-white p-2.5">
        <header className="mb-1.5">
          <h4 className="text-[12px] font-extrabold tracking-tight">Cluster SSA average by intervention</h4>
          <p className="text-[10px] muted mt-0.5 leading-tight">Average across schools with current-cycle SSA, weakest first.</p>
        </header>
        <div className="space-y-1">
          {[...p.averages].sort((a, b) => a.score - b.score).map((row) => (
            <div key={row.intervention} className="grid grid-cols-12 items-center gap-2 text-caption">
              <div className="col-span-5 truncate" title={row.intervention}>{row.intervention}</div>
              <div className="col-span-6 relative h-3.5 rounded bg-[var(--color-edify-soft)]/60 overflow-hidden">
                <div className={cn("absolute inset-y-0 left-0 rounded", barFillFor(row.score))} style={{ width: `${(row.score / 10) * 100}%` }} />
              </div>
              <div className={cn("col-span-1 text-right tabular font-extrabold", STATUS_TONE[row.status].text)}>{row.score || "—"}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Yearly trend */}
      {p.yearlyAverages && p.yearlyAverages.length >= 2 && (
        <section className="rounded-lg border border-[var(--color-edify-divider)] bg-white p-2.5">
          <header className="mb-1.5">
            <h4 className="text-[12px] font-extrabold tracking-tight">Cluster SSA trend</h4>
            <p className="text-[10px] muted mt-0.5 leading-tight">Year-over-year average across all schools.</p>
          </header>
          <div className="grid grid-cols-12 gap-1.5">
            {p.yearlyAverages.map((y, idx) => {
              const isCurrent = idx === p.yearlyAverages!.length - 1;
              return (
                <div key={y.year} className="col-span-4">
                  <div className="text-[9.5px] uppercase tracking-wider font-bold muted tabular mb-0.5">{y.year}</div>
                  <div className="relative h-3 rounded bg-[var(--color-edify-soft)]/60 overflow-hidden">
                    <div className={cn("absolute inset-y-0 left-0 rounded", barFillFor(y.average), isCurrent ? "" : "opacity-60")} style={{ width: `${(y.average / 10) * 100}%` }} />
                  </div>
                  <div className={cn("text-right tabular text-[10px] mt-0.5", isCurrent ? "font-extrabold text-[var(--color-edify-text)]" : "muted")}>
                    {y.average.toFixed(1)}/10
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* School-by-school SSA */}
      <section className="rounded-lg border border-[var(--color-edify-divider)] bg-white p-2.5">
        <header className="mb-1.5">
          <h4 className="text-[12px] font-extrabold tracking-tight">School-by-school SSA</h4>
          <p className="text-[10px] muted mt-0.5 leading-tight">Weakest-performing schools first.</p>
        </header>
        <div className="overflow-x-auto -mx-2.5">
          <table className="w-full text-caption">
            <thead>
              <tr className="text-left text-[9.5px] uppercase tracking-wider font-bold text-[var(--color-edify-muted)] border-b border-[var(--color-edify-divider)]">
                <th className="px-2.5 py-1">School</th>
                <th className="px-2.5 py-1 text-right">Avg</th>
                <th className="px-2.5 py-1">Weakest area</th>
                <th className="px-2.5 py-1">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {p.schools.map((s) => {
                const tone = STATUS_TONE[s.status];
                return (
                  <tr key={s.schoolId}>
                    <td className="px-2.5 py-1 font-extrabold text-[var(--color-edify-text)]">{s.schoolName}</td>
                    <td className="px-2.5 py-1 text-right tabular font-extrabold">{s.averageSsaScore > 0 ? s.averageSsaScore.toFixed(1) : "—"}</td>
                    <td className="px-2.5 py-1 muted">{s.weakestArea ?? "—"}</td>
                    <td className="px-2.5 py-1">
                      <span className={cn("inline-flex items-center px-1.5 py-[1px] rounded text-[9.5px] font-extrabold uppercase tracking-wide", tone.bg, tone.text)}>{s.status}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

// ────────── SCHOOL POTENTIAL TAB ──────────

function PotentialTab({
  summary, onAction,
}: {
  summary: ClusterActivityInvestmentSummary;
  onAction?: (action: ClusterNextAction["action"], schoolId?: string) => void;
}) {
  const { potentialCoreSchools, potentialChampionSchools } = summary.schoolPotential;
  return (
    <div className="space-y-2.5">
      <PotentialCard
        title="Potential Core schools"
        subtitle="Client schools ready to graduate into the Core support tier."
        tone="good"
        emptyText="No client schools meet the Core criteria in this scope."
        items={potentialCoreSchools.map((c) => ({
          schoolId:   c.schoolId,
          schoolName: c.schoolName,
          headline:   `Avg SSA ${c.averageSsaScore.toFixed(1)}${c.improvement ? `, improved +${c.improvement.toFixed(1)}` : ""}`,
          reasons:    c.reasons,
          action:     "review_core" as const,
          ctaLabel:   "Review for Core upgrade",
        }))}
        onAction={onAction}
      />
      <PotentialCard
        title="Potential Champion schools"
        subtitle="Core schools ready to mentor others as a Champion school."
        tone="primary"
        emptyText="No core schools meet the Champion criteria in this scope."
        items={potentialChampionSchools.map((c) => ({
          schoolId:   c.schoolId,
          schoolName: c.schoolName,
          headline:   `Avg SSA ${c.averageSsaScore.toFixed(1)} · lowest intervention ${c.lowestInterventionScore}/10`,
          reasons:    c.reasons,
          action:     "review_champion" as const,
          ctaLabel:   "Review for Champion status",
        }))}
        onAction={onAction}
      />
    </div>
  );
}

function PotentialCard({
  title, subtitle, tone, items, emptyText, onAction,
}: {
  title:    string;
  subtitle: string;
  tone:     "good" | "primary";
  items: { schoolId: string; schoolName: string; headline: string; reasons: string[]; action: ClusterNextAction["action"]; ctaLabel: string }[];
  emptyText: string;
  onAction?: (action: ClusterNextAction["action"], schoolId?: string) => void;
}) {
  const t = tone === "good"
    ? { bg: "bg-emerald-50", text: "text-emerald-700", Icon: Award }
    : { bg: "bg-violet-50",  text: "text-violet-700",  Icon: Award };
  return (
    <section className="rounded-lg border border-[var(--color-edify-divider)] bg-white p-2.5">
      <header className="flex items-start gap-2 mb-1.5">
        <span className={cn("grid place-items-center h-6 w-6 rounded-md shrink-0", t.bg, t.text)}>
          <t.Icon size={11} />
        </span>
        <div className="min-w-0">
          <h4 className="text-[12px] font-extrabold tracking-tight">{title}</h4>
          <p className="text-[10px] muted leading-tight mt-0.5">{subtitle}</p>
        </div>
      </header>
      {items.length === 0 ? (
        <p className="text-caption muted">{emptyText}</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((it) => (
            <li key={it.schoolId} className="rounded-md border border-[var(--color-edify-divider)] px-2.5 py-2 flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <div className="text-[11.5px] font-extrabold tracking-tight truncate">{it.schoolName}</div>
                <div className="text-caption muted">{it.headline}</div>
                <ul className="text-[10px] muted mt-1 space-y-0.5">
                  {it.reasons.map((r, i) => (
                    <li key={i} className="flex items-start gap-1">
                      <ChevronRight size={9} className="mt-0.5 text-[var(--color-edify-primary)] shrink-0" />
                      <span>{r}</span>
                    </li>
                  ))}
                </ul>
              </div>
              {onAction && (
                <Button size="sm" variant="secondary" onClick={() => onAction(it.action, it.schoolId)}>{it.ctaLabel}</Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ────────── COSTS TAB ──────────

function CostsTab({ summary }: { summary: ClusterActivityInvestmentSummary }) {
  const cb = summary.costBreakdown;
  const rows = [
    { label: "Cluster meetings",        value: cb.meetingCost          },
    { label: "Trainings",               value: cb.trainingCost         },
    { label: "Partner facilitation",    value: cb.partnerFacilitationCost },
    { label: "Staff support visits",    value: cb.staffVisitCost       },
    { label: "SSA / assessment",        value: cb.ssaCost              },
    { label: "Resources / projects",    value: cb.resourceProjectCost  },
    { label: "Other",                   value: cb.otherCost            },
  ];

  return (
    <div className="space-y-2.5">
      <section className="rounded-md border border-emerald-200 bg-emerald-50/40 px-2.5 py-2 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h4 className="text-[11px] font-extrabold tracking-tight inline-flex items-center gap-1 text-emerald-800">
            <Wallet size={11} /> Total invested in cluster
          </h4>
          <p className="text-[10px] muted leading-tight mt-0.5">Database-derived. Cluster activities allocated per school.</p>
        </div>
        <span className="text-[16px] font-extrabold tabular text-emerald-700 shrink-0">{formatUgx(cb.totalSpent)}</span>
      </section>

      <section className="rounded-lg border border-[var(--color-edify-divider)] bg-white p-2.5">
        <header className="mb-1.5">
          <h4 className="text-[12px] font-extrabold tracking-tight">Cost breakdown</h4>
          <p className="text-[10px] muted mt-0.5 leading-tight">By source. Cluster activity totals include all participating schools.</p>
        </header>
        <StackedShareBar segments={rows.filter((r) => r.value > 0)} total={cb.totalSpent} />
        <ul className="mt-2 divide-y divide-[var(--color-edify-divider)]">
          {rows.map((r) => (
            <li key={r.label} className="flex items-baseline justify-between gap-2 py-1 text-caption">
              <span className="muted">{r.label}</span>
              <span className="tabular font-extrabold text-[var(--color-edify-text)]">{formatUgx(r.value)}</span>
            </li>
          ))}
          <li className="flex items-baseline justify-between gap-2 pt-1.5 mt-1 border-t border-[var(--color-edify-divider)] text-[11px] font-extrabold">
            <span>Total</span>
            <span className="tabular text-emerald-700">{formatUgx(cb.totalSpent)}</span>
          </li>
        </ul>
      </section>

      <section className="rounded-md border border-sky-200 bg-sky-50/60 px-2.5 py-1.5 text-caption text-sky-800 inline-flex items-start gap-1.5">
        <Sparkles size={11} className="mt-0.5 shrink-0" />
        <span>
          Per-school allocation: <span className="font-extrabold">total cluster cost ÷ participating schools</span>.
          School profile drawer shows the school&apos;s share inline.
        </span>
      </section>
    </div>
  );
}

function StackedShareBar({ segments, total }: { segments: { label: string; value: number }[]; total: number }) {
  if (total === 0) return <p className="text-caption muted">No cost recorded yet.</p>;
  const colors = ["bg-emerald-600","bg-sky-600","bg-amber-500","bg-orange-500","bg-violet-600","bg-rose-500","bg-slate-600"];
  return (
    <div className="space-y-1">
      <div className="h-2 w-full rounded overflow-hidden flex bg-[var(--color-edify-soft)]/60">
        {segments.map((s, i) => (
          <div key={s.label} className={cn("h-full", colors[i % colors.length])} style={{ width: `${(s.value / total) * 100}%` }} title={`${s.label}: ${formatUgx(s.value)}`} />
        ))}
      </div>
      <div className="flex items-center gap-2 flex-wrap text-[10px] muted">
        {segments.map((s, i) => (
          <span key={s.label} className="inline-flex items-center gap-1">
            <span className={cn("h-2 w-2 rounded-sm", colors[i % colors.length])} />
            {s.label} <span className="tabular">{Math.round((s.value / total) * 100)}%</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// ────────── EVIDENCE TAB ──────────

function EvidenceTab({ summary }: { summary: ClusterActivityInvestmentSummary }) {
  const es = summary.evidenceSummary;
  return (
    <div className="space-y-2.5">
      <section className="grid grid-cols-2 lg:grid-cols-5 gap-1.5">
        <Kpi label="Complete"      value={String(es.complete)}                 tone="good" />
        <Kpi label="Missing"       value={String(es.missing)}                  tone={es.missing > 0 ? "warn" : "neutral"} />
        <Kpi label="Awaiting CCEO" value={String(es.awaitingCceoConfirmation)} tone={es.awaitingCceoConfirmation > 0 ? "warn" : "neutral"} />
        <Kpi label="M&E verified"  value={String(es.verifiedByME)}             tone="good" />
        <Kpi label="Returned"      value={String(es.returnedForCorrection)}    tone={es.returnedForCorrection > 0 ? "warn" : "neutral"} />
      </section>

      <section className="rounded-lg border border-[var(--color-edify-divider)] bg-white p-2.5">
        <header className="mb-1.5">
          <h4 className="text-[12px] font-extrabold tracking-tight">Per-activity evidence</h4>
          <p className="text-[10px] muted mt-0.5 leading-tight">Cluster meetings and trainings only.</p>
        </header>
        {es.perActivity.length === 0 ? (
          <p className="text-caption muted">No cluster activities with evidence to track yet.</p>
        ) : (
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {es.perActivity.map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-2 py-1.5 text-caption">
                <span className="min-w-0 flex-1 truncate font-extrabold text-[var(--color-edify-text)]">{a.title}</span>
                <span className={cn("inline-flex items-center px-1.5 py-[1px] rounded text-[9.5px] font-extrabold uppercase tracking-wide shrink-0",
                  toneFor(a.evidenceStatus).bg, toneFor(a.evidenceStatus).text)}>
                  {EVIDENCE_LABEL[a.evidenceStatus]}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function toneFor(s: EvidenceStatus): { bg: string; text: string } {
  if (s === "complete" || s === "verified") return { bg: "bg-emerald-50", text: "text-emerald-700" };
  if (s === "missing" || s === "partial")   return { bg: "bg-rose-50",    text: "text-rose-700"    };
  if (s === "returned")                     return { bg: "bg-orange-50",  text: "text-orange-700"  };
  return { bg: "bg-slate-100", text: "text-slate-600" };
}

// ────────── NEXT ACTIONS TAB ──────────

function NextActionsTab({
  summary, onAction,
}: {
  summary: ClusterActivityInvestmentSummary;
  onAction?: (action: ClusterNextAction["action"], schoolId?: string) => void;
}) {
  if (summary.nextActions.length === 0) {
    return (
      <section className="rounded-lg border border-emerald-200 bg-emerald-50/40 p-3 text-center">
        <span className="inline-grid place-items-center h-7 w-7 rounded-md bg-emerald-100 text-emerald-700 mb-1">
          <CheckCircle2 size={12} />
        </span>
        <h4 className="text-[12px] font-extrabold tracking-tight">Cluster is on track</h4>
        <p className="text-caption muted mt-1">No outstanding actions detected in this scope.</p>
      </section>
    );
  }
  return (
    <ul className="space-y-1.5">
      {summary.nextActions.map((a, i) => (
        <li key={i} className="rounded-md border border-[var(--color-edify-divider)] bg-white px-2.5 py-2 flex items-start gap-2">
          <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
            <ChevronRight size={11} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[11.5px] font-extrabold tracking-tight leading-tight">{a.title}</p>
            <p className="text-caption muted leading-snug mt-0.5">{a.reason}</p>
          </div>
          {a.action && onAction && (
            <Button size="sm" variant="secondary" onClick={() => onAction(a.action, a.schoolId)}>{a.ctaLabel}</Button>
          )}
        </li>
      ))}
    </ul>
  );
}

// ────────── Atoms ──────────

function Kpi({
  label, value, sub, tone = "neutral",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "neutral" | "primary" | "good" | "warn";
}) {
  const t =
    tone === "primary" ? "text-[var(--color-edify-primary)]" :
    tone === "good"    ? "text-emerald-700" :
    tone === "warn"    ? "text-amber-700"   :
                         "text-[var(--color-edify-text)]";
  return (
    <div className="rounded-md border border-[var(--color-edify-divider)] bg-white px-2 py-1.5">
      <div className="text-[9.5px] uppercase tracking-wider font-bold muted truncate" title={label}>{label}</div>
      <div className={cn("text-[13px] font-extrabold tabular leading-tight mt-0.5", t)}>{value}</div>
      {sub && <div className="text-[10px] muted leading-tight truncate" title={sub}>{sub}</div>}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="muted">{label}: </span>
      <span className="font-semibold text-[var(--color-edify-text)]">{value}</span>
    </div>
  );
}

// ────────── Helpers ──────────

function barFillFor(score: number): string {
  if (score <= 4) return "bg-rose-500";
  if (score <= 6) return "bg-amber-500";
  if (score <= 8) return "bg-emerald-500";
  return "bg-emerald-700";
}
function healthColor(score: number): string {
  if (score >= 70) return "text-emerald-700";
  if (score >= 50) return "text-amber-700";
  return "text-rose-700";
}

// Suppress unused-symbol warnings — keeping these exports re-imported
// from the cluster mock so the drawer's API surface is fully typed
// without each consumer chasing a different module.
export type { SchoolGap, ClusterActivityInvestmentSummary };
export { ssaStatusFor };
