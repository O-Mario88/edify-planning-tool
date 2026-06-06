"use client";

// SchoolActivityProfileDrawer — answers a single question:
// "What has been done with this school, who did it, when, what's the
//  evidence, what did it cost, and what's needed next?"
//
// Replaces the placeholder behaviour of the View School button. Pulls
// from school-activity-mock + ssa-performance-mock so the drawer
// stays in sync with the SSA performance drawer.
//
// Six tabs (Overview / Timeline / Costs / Evidence / SSA / Next
// Actions). The Overview tab carries the top summary the spec asks
// for; the deeper tabs surface the longer detail without pushing the
// drawer to a giant single scroll.

import { useMemo, useState } from "react";
import { formatUgxCompact as formatUgx, formatHumanDate } from "@/lib/format-utils";
import {
  Building2, Calendar, GraduationCap, Footprints, Users, BookOpen,
  Sparkles, MapPin, Receipt, ShieldCheck, ListTree, AlertTriangle,
  TrendingUp, TrendingDown, Minus, ChevronRight, Wallet, Handshake,
  CheckCircle2, ClipboardList, type LucideIcon,
} from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import type { SchoolGap, SchoolGapAction } from "@/lib/planning/planning-gaps-mock";
import {
  buildSchoolActivitySummary,
  ACTIVITY_TYPE_LABEL,
  EVIDENCE_LABEL,
  VERIFICATION_LABEL,
  PAYMENT_LABEL,
  ssaStatusFor,
  CURRENT_CYCLE,
  type SchoolActivityInvestmentSummary,
  type SchoolActivityTimelineItem,
  type SchoolActivityType,
  type EvidenceStatus,
  type VerificationStatus,
  type PaymentStatus,
  type SummaryScope,
} from "@/lib/planning/school-activity-mock";

// ────────── Visual tokens ──────────

const ACTIVITY_ICON: Record<SchoolActivityType, LucideIcon> = {
  staff_visit:                 Footprints,
  partner_visit:               Handshake,
  training:                    GraduationCap,
  cluster_meeting:             Users,
  school_improvement_training: GraduationCap,
  ssa:                         ClipboardList,
  coaching_visit:              BookOpen,
  follow_up_visit:             Calendar,
  classroom_observation:       BookOpen,
  resource_delivery:           Building2,
  project:                     Building2,
  other:                       ChevronRight,
};

const EVIDENCE_TONE: Record<EvidenceStatus, { bg: string; text: string }> = {
  not_required: { bg: "bg-slate-100",  text: "text-slate-600"  },
  missing:      { bg: "bg-rose-50",    text: "text-rose-700"   },
  partial:      { bg: "bg-amber-50",   text: "text-amber-700"  },
  complete:     { bg: "bg-emerald-50", text: "text-emerald-700"},
  returned:     { bg: "bg-orange-50",  text: "text-orange-700" },
  verified:     { bg: "bg-emerald-100",text: "text-emerald-800"},
};
const VERIFICATION_TONE: Record<VerificationStatus, { bg: string; text: string }> = {
  not_submitted:    { bg: "bg-slate-100",  text: "text-slate-600"   },
  awaiting_review:  { bg: "bg-amber-50",   text: "text-amber-700"   },
  verified:         { bg: "bg-emerald-100",text: "text-emerald-800" },
  rejected:         { bg: "bg-rose-50",    text: "text-rose-700"    },
  counted:          { bg: "bg-sky-50",     text: "text-sky-700"     },
};
const PAYMENT_TONE: Record<PaymentStatus, { bg: string; text: string }> = {
  not_applicable:              { bg: "bg-slate-100",  text: "text-slate-500"   },
  projected:                   { bg: "bg-sky-50",     text: "text-sky-700"     },
  awaiting_cceo_confirmation:  { bg: "bg-amber-50",   text: "text-amber-700"   },
  awaiting_pl_approval:        { bg: "bg-amber-50",   text: "text-amber-800"   },
  sent_to_accountant:          { bg: "bg-sky-50",     text: "text-sky-700"     },
  paid_cleared:                { bg: "bg-emerald-100",text: "text-emerald-800" },
};

// ────────── Types ──────────

export type SchoolActivityProfileContext = {
  school: SchoolGap;
};

const TABS = ["overview", "timeline", "costs", "evidence", "ssa", "next"] as const;
type TabKey = typeof TABS[number];

const TAB_LABEL: Record<TabKey, string> = {
  overview: "Overview",
  timeline: "Timeline",
  costs:    "Costs",
  evidence: "Evidence",
  ssa:      "SSA",
  next:     "Next actions",
};

const TAB_ICON: Record<TabKey, LucideIcon> = {
  overview: Sparkles,
  timeline: ListTree,
  costs:    Receipt,
  evidence: ShieldCheck,
  ssa:      BookOpen,
  next:     ChevronRight,
};

// ────────── Component ──────────

export function SchoolActivityProfileDrawer({
  open, context, onClose, onAction, onViewSsa,
}: {
  open: boolean;
  context: SchoolActivityProfileContext | null;
  onClose: () => void;
  /** Recommended-action CTA hook — same shape as the SSA drawer's so
   *  the parent re-uses its planning machinery. */
  onAction?: (action: SchoolGapAction, school: SchoolGap) => void;
  /** Optional hand-off so the SSA tab's "View full SSA graph" button
   *  can close this drawer and open the SsaPerformanceDrawer. */
  onViewSsa?: (school: SchoolGap) => void;
}) {
  const [scope, setScope]   = useState<SummaryScope>("current_cycle");
  const [tab, setTab]       = useState<TabKey>("overview");

  const school = context?.school ?? null;

  const summary = useMemo<SchoolActivityInvestmentSummary | null>(() => {
    if (!school) return null;
    return buildSchoolActivitySummary(
      {
        schoolId:    school.id,
        schoolName:  school.schoolName,
        district:    school.district,
        subCounty:   school.subCounty,
        parish:      school.parish,
        clusterName: school.clusterName,
      },
      scope,
    );
  }, [school, scope]);

  if (!context || !school || !summary) return null;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="School Activity & Investment"
      description="Visits, trainings, partner activity, evidence, cost, and history."
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

        {/* School identity card */}
        <SchoolIdentityCard school={school} summary={summary} />

        {/* Tab nav */}
        <TabNav active={tab} onChange={setTab} />

        {/* Tab body */}
        <div className="pt-1">
          {tab === "overview" && <OverviewTab summary={summary} scope={scope} />}
          {tab === "timeline" && <TimelineTab summary={summary} />}
          {tab === "costs"    && <CostsTab summary={summary} />}
          {tab === "evidence" && <EvidenceTab summary={summary} />}
          {tab === "ssa"      && (
            <SsaTab
              summary={summary}
              onViewFullSsa={onViewSsa ? () => onViewSsa(school) : undefined}
            />
          )}
          {tab === "next"     && (
            <NextActionsTab
              summary={summary}
              onAction={onAction ? (a) => onAction(a, school) : undefined}
            />
          )}
        </div>
      </div>
    </Modal>
  );
}

// ────────── School identity card ──────────

function SchoolIdentityCard({
  school, summary,
}: {
  school: SchoolGap;
  summary: SchoolActivityInvestmentSummary;
}) {
  return (
    <section className="rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 px-2.5 py-2 flex items-start gap-2">
      <span className="grid place-items-center h-7 w-7 rounded-md bg-white text-[var(--color-edify-primary)] shrink-0 border border-[var(--color-edify-border)]">
        <Building2 size={12} />
      </span>
      <div className="min-w-0 flex-1">
        <h3 className="text-body font-extrabold tracking-tight truncate">{school.schoolName}</h3>
        <div className="text-caption muted leading-tight inline-flex items-center gap-1 flex-wrap">
          <MapPin size={9} className="text-[var(--color-edify-primary)]" />
          {school.district}
          {school.subCounty && <> · {school.subCounty}</>}
          {school.parish    && <> · {school.parish}</>}
        </div>
        <div className="text-caption muted mt-0.5 inline-flex items-center gap-2 flex-wrap">
          <span>{summary.clusterName ?? "No cluster"}</span>
          <span className="opacity-40">·</span>
          <span className="capitalize">{summary.schoolCategory}</span>
          <span className="opacity-40">·</span>
          <span>{summary.operationalCycle}</span>
        </div>
      </div>
    </section>
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

// ────────── Tab nav ──────────

function TabNav({ active, onChange }: { active: TabKey; onChange: (t: TabKey) => void }) {
  return (
    <nav role="tablist" className="flex items-center gap-0.5 border-b border-[var(--color-edify-divider)] overflow-x-auto -mx-1 px-1">
      {TABS.map((t) => {
        const Icon = TAB_ICON[t];
        const isActive = t === active;
        return (
          <button
            key={t}
            role="tab"
            aria-selected={isActive}
            type="button"
            onClick={() => onChange(t)}
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
  );
}

// ────────── OVERVIEW TAB ──────────

function OverviewTab({ summary, scope }: { summary: SchoolActivityInvestmentSummary; scope: SummaryScope }) {
  const t = summary.totals;
  return (
    <div className="space-y-2.5">

      {/* Top KPI cards */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-1.5">
        <Kpi label="Total activities"     value={String(t.totalActivities)} />
        <Kpi label="Total visits"         value={String(t.totalVisits)} sub={`${t.staffVisits} staff · ${t.partnerVisits} partner`} />
        <Kpi label="Trainings"            value={String(t.trainings)} />
        <Kpi label="Cluster activities"   value={String(t.clusterActivities)} />
        <Kpi label="SSA completed"        value={String(t.ssaCompleted)} sub={scope === "current_cycle" ? "current cycle" : "all time"} />
        <Kpi label="Total spent"          value={formatUgx(t.totalSpent)} tone="primary" />
        <Kpi label="Evidence complete"    value={String(summary.evidenceSummary.complete)} sub={`${summary.evidenceSummary.missing} missing`} />
        <Kpi label="M&E verified"         value={String(summary.evidenceSummary.verifiedByME)} sub={`${summary.evidenceSummary.awaitingCceoConfirmation} pending`} />
      </section>

      {/* Activity breakdown table */}
      <section className="rounded-lg border border-[var(--color-edify-divider)] bg-white p-2.5">
        <header className="mb-2">
          <h4 className="text-[12px] font-extrabold tracking-tight">Activity breakdown</h4>
          <p className="text-[10px] muted mt-0.5 leading-tight">Counts, cost, and most-recent date for each activity type.</p>
        </header>
        <div className="overflow-x-auto -mx-2.5">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-left text-caption uppercase tracking-wider font-bold text-[var(--color-edify-muted)] border-b border-[var(--color-edify-divider)]">
                <th className="px-2.5 py-1">Activity</th>
                <th className="px-2.5 py-1 text-right">Count</th>
                <th className="px-2.5 py-1 text-right">Cost</th>
                <th className="px-2.5 py-1">Last done</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {summary.activityBreakdown.map((row) => (
                <tr key={row.activityType}>
                  <td className="px-2.5 py-1.5 font-extrabold text-[var(--color-edify-text)]">{row.activityType}</td>
                  <td className="px-2.5 py-1.5 text-right tabular muted">{row.count}</td>
                  <td className="px-2.5 py-1.5 text-right tabular font-extrabold text-[var(--color-edify-text)]">{formatUgx(row.cost)}</td>
                  <td className="px-2.5 py-1.5 tabular muted">{row.lastDone ? formatHumanDate(row.lastDone) : "—"}</td>
                </tr>
              ))}
              {summary.activityBreakdown.length === 0 && (
                <tr><td colSpan={4} className="px-3.5 py-4 text-center muted">No activity recorded in this scope yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Who supported the school */}
      <ContributorsCard summary={summary} />

    </div>
  );
}

function ContributorsCard({ summary }: { summary: SchoolActivityInvestmentSummary }) {
  return (
    <section className="grid grid-cols-1 md:grid-cols-2 gap-2">
      <div className="rounded-lg border border-[var(--color-edify-divider)] bg-white p-2.5">
        <header className="mb-2">
          <h4 className="text-[12px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <Footprints size={12} className="text-[var(--color-edify-primary)]" />
            Staff support
          </h4>
          <p className="text-[10px] muted mt-0.5 leading-tight">Direct staff contribution to this school.</p>
        </header>
        {summary.contributors.staff.length === 0 ? (
          <p className="text-[11px] muted">No staff activity in this scope.</p>
        ) : (
          <ul className="space-y-1">
            {summary.contributors.staff.map((c) => (
              <li key={c.name} className="flex items-baseline justify-between gap-2 text-[11px]">
                <span className="truncate">
                  <span className="font-extrabold text-[var(--color-edify-text)]">{c.name}</span>
                  <span className="muted"> · {c.visits} visits · {c.trainings} trainings</span>
                </span>
                <span className="tabular font-extrabold text-[var(--color-edify-text)] shrink-0">{formatUgx(c.cost)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="rounded-lg border border-[var(--color-edify-divider)] bg-white p-2.5">
        <header className="mb-2">
          <h4 className="text-[12px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <Handshake size={12} className="text-[var(--color-edify-primary)]" />
            Partner support
          </h4>
          <p className="text-[10px] muted mt-0.5 leading-tight">Partner-delivered visits, trainings, and follow-ups.</p>
        </header>
        {summary.contributors.partner.length === 0 ? (
          <p className="text-[11px] muted">No partner activity in this scope.</p>
        ) : (
          <ul className="space-y-1">
            {summary.contributors.partner.map((c) => (
              <li key={c.name} className="text-[11px]">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate">
                    <span className="font-extrabold text-[var(--color-edify-text)]">{c.name}</span>
                    <span className="muted"> · {c.visits} visits · {c.trainings} trainings</span>
                  </span>
                  <span className="tabular font-extrabold text-[var(--color-edify-text)] shrink-0">{formatUgx(c.cost)}</span>
                </div>
                {c.paymentStatusHint && (
                  <div className="mt-0.5">
                    <span className={cn("inline-flex items-center px-1.5 py-[1px] rounded-md text-[10px] font-extrabold", PAYMENT_TONE[c.paymentStatusHint].bg, PAYMENT_TONE[c.paymentStatusHint].text)}>
                      {PAYMENT_LABEL[c.paymentStatusHint]}
                    </span>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

// ────────── TIMELINE TAB ──────────

function TimelineTab({ summary }: { summary: SchoolActivityInvestmentSummary }) {
  const [filter, setFilter]               = useState<"all" | "visits" | "trainings" | "ssa" | "cluster" | "partner" | "staff" | "evidence_missing" | "verified">("all");

  const filtered = useMemo(() => {
    return summary.timeline.filter((a) => {
      switch (filter) {
        case "all":              return true;
        case "visits":           return ["staff_visit","partner_visit","coaching_visit","follow_up_visit","classroom_observation"].includes(a.activityType);
        case "trainings":        return ["training","school_improvement_training"].includes(a.activityType);
        case "ssa":              return a.activityType === "ssa";
        case "cluster":          return a.activityType === "cluster_meeting";
        case "partner":          return a.deliveredByRole === "Partner";
        case "staff":            return a.deliveredByRole !== "Partner";
        case "evidence_missing": return a.evidenceStatus === "missing" || a.evidenceStatus === "partial";
        case "verified":         return a.verificationStatus === "verified" || a.verificationStatus === "counted";
      }
    });
  }, [summary.timeline, filter]);

  const FILTERS: { key: typeof filter; label: string }[] = [
    { key: "all",              label: "All" },
    { key: "visits",           label: "Visits" },
    { key: "trainings",        label: "Trainings" },
    { key: "ssa",              label: "SSA" },
    { key: "cluster",          label: "Cluster" },
    { key: "partner",          label: "Partner" },
    { key: "staff",            label: "Staff" },
    { key: "evidence_missing", label: "Evidence missing" },
    { key: "verified",         label: "Verified" },
  ];

  return (
    <div className="space-y-2.5">
      <div className="flex items-center gap-1 flex-wrap">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => setFilter(f.key)}
            className={cn(
              "h-6 px-2 rounded text-caption font-semibold border transition-colors",
              filter === f.key
                ? "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)]"
                : "border-[var(--color-edify-border)] bg-white text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60",
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <p className="text-[11px] muted px-1">No activities match this filter.</p>
      ) : (
        <ul className="space-y-1.5">
          {filtered.map((a) => <TimelineItem key={a.id} item={a} />)}
        </ul>
      )}
    </div>
  );
}

function TimelineItem({ item }: { item: SchoolActivityTimelineItem }) {
  const Icon = ACTIVITY_ICON[item.activityType];
  const eTone = EVIDENCE_TONE[item.evidenceStatus];
  const vTone = VERIFICATION_TONE[item.verificationStatus];
  const pTone = item.paymentStatus ? PAYMENT_TONE[item.paymentStatus] : null;

  return (
    <li className="rounded-md border border-[var(--color-edify-divider)] bg-white px-2.5 py-2 flex items-start gap-2">
      <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
        <Icon size={11} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <div className="min-w-0">
            <h5 className="text-[11px] font-extrabold tracking-tight truncate">{item.title}</h5>
            <p className="text-[10px] muted mt-0.5 leading-tight">
              {ACTIVITY_TYPE_LABEL[item.activityType]} · {formatHumanDate(item.date)} · {item.operationalCycle}
            </p>
          </div>
          <span className="text-[11px] font-extrabold tabular text-[var(--color-edify-text)] shrink-0">{formatUgx(item.cost)}</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-0.5 mt-1.5 text-caption">
          <Field label="By" value={`${item.deliveredByName} (${item.deliveredByRole})`} />
          {item.staffMonitorName && <Field label="Monitor" value={item.staffMonitorName} />}
          {item.purpose && <Field label="Purpose" value={item.purpose} fullWidth />}
          {item.ssaInterventionAddressed && <Field label="SSA area" value={item.ssaInterventionAddressed} />}
          {item.costAllocated && item.costAllocationTotal && item.costAllocationSchoolCount && (
            <Field
              label="Allocation"
              value={`${formatUgx(item.costAllocationTotal)} ÷ ${item.costAllocationSchoolCount} = ${formatUgx(item.cost)}`}
              fullWidth
            />
          )}
        </div>

        <div className="flex items-center gap-1 flex-wrap mt-1.5">
          <Pill label={EVIDENCE_LABEL[item.evidenceStatus]}      tone={eTone} />
          <Pill label={VERIFICATION_LABEL[item.verificationStatus]} tone={vTone} />
          {pTone && item.paymentStatus && <Pill label={PAYMENT_LABEL[item.paymentStatus]} tone={pTone} />}
        </div>

        {item.nextAction && (
          <p className="text-caption mt-1.5 px-2 py-1 rounded bg-[var(--color-edify-soft)]/60 inline-flex items-start gap-1 leading-tight">
            <ChevronRight size={10} className="mt-0.5 text-[var(--color-edify-primary)] shrink-0" />
            <span><span className="font-extrabold">Next:</span> {item.nextAction}</span>
          </p>
        )}
      </div>
    </li>
  );
}

function Field({ label, value, fullWidth }: { label: string; value: string; fullWidth?: boolean }) {
  return (
    <div className={fullWidth ? "sm:col-span-2" : undefined}>
      <span className="muted">{label}: </span>
      <span className="font-semibold text-[var(--color-edify-text)]">{value}</span>
    </div>
  );
}

function Pill({ label, tone }: { label: string; tone: { bg: string; text: string } }) {
  return (
    <span className={cn("inline-flex items-center px-1.5 py-[1px] rounded text-[9.5px] font-extrabold uppercase tracking-wide", tone.bg, tone.text)}>
      {label}
    </span>
  );
}

// ────────── COSTS TAB ──────────

function CostsTab({ summary }: { summary: SchoolActivityInvestmentSummary }) {
  const cb = summary.costBreakdown;
  const total = cb.totalSpent;
  const rows: { label: string; value: number; tone: "primary" | "secondary" }[] = [
    { label: "Staff visits",         value: cb.staffVisitCost,       tone: "primary" },
    { label: "Partner visits",       value: cb.partnerVisitCost,     tone: "primary" },
    { label: "Trainings",            value: cb.trainingCost,         tone: "primary" },
    { label: "Cluster (allocated)",  value: cb.clusterAllocatedCost, tone: "secondary" },
    { label: "SSA",                  value: cb.ssaCost,              tone: "primary" },
    { label: "Projects / resources", value: cb.projectCost + cb.otherCost, tone: "secondary" },
  ];

  // Allocated-cost rule explainer — only shown when at least one
  // cluster activity contributed an allocated cost.
  const hasAllocated = summary.timeline.some((a) => a.costAllocated);

  return (
    <div className="space-y-2.5">
      <section className="rounded-md border border-emerald-200 bg-emerald-50/40 px-2.5 py-2 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h4 className="text-[11px] font-extrabold tracking-tight inline-flex items-center gap-1 text-emerald-800">
            <Wallet size={11} /> Total invested
          </h4>
          <p className="text-[10px] muted leading-tight mt-0.5">From database cost records.</p>
        </div>
        <span className="text-[16px] font-extrabold tabular text-emerald-700 shrink-0">{formatUgx(total)}</span>
      </section>

      <section className="rounded-lg border border-[var(--color-edify-divider)] bg-white p-2.5">
        <header className="mb-2">
          <h4 className="text-[12px] font-extrabold tracking-tight">Cost breakdown</h4>
          <p className="text-[10px] muted mt-0.5 leading-tight">By cost source. Stacked share visualises proportion of total.</p>
        </header>
        <StackedShareBar segments={rows.filter((r) => r.value > 0).map((r) => ({ label: r.label, value: r.value }))} total={total} />
        <ul className="mt-2 divide-y divide-[var(--color-edify-divider)]">
          {rows.map((r) => (
            <li key={r.label} className="flex items-baseline justify-between gap-2 py-1 text-caption">
              <span className="muted">{r.label}</span>
              <span className="tabular font-extrabold text-[var(--color-edify-text)]">{formatUgx(r.value)}</span>
            </li>
          ))}
          <li className="flex items-baseline justify-between gap-2 pt-1.5 mt-1 border-t border-[var(--color-edify-divider)] text-[11px] font-extrabold">
            <span>Total</span>
            <span className="tabular text-emerald-700">{formatUgx(total)}</span>
          </li>
        </ul>
      </section>

      {hasAllocated && (
        <section className="rounded-md border border-sky-200 bg-sky-50/60 px-3 py-2 text-[11px] text-sky-800 inline-flex items-start gap-1.5">
          <Sparkles size={12} className="mt-0.5 shrink-0" />
          <span>
            Cluster activities are allocated per school:
            <span className="font-extrabold"> total cluster cost ÷ participating schools</span>. The activity timeline shows the allocation maths inline.
          </span>
        </section>
      )}
    </div>
  );
}

function StackedShareBar({ segments, total }: { segments: { label: string; value: number }[]; total: number }) {
  if (total === 0) return <p className="text-[11px] muted">No cost recorded yet.</p>;
  const colors = [
    "bg-emerald-600", "bg-sky-600", "bg-amber-500", "bg-orange-500", "bg-violet-600", "bg-rose-500", "bg-slate-600",
  ];
  return (
    <div className="space-y-1">
      <div className="h-2 w-full rounded overflow-hidden flex bg-[var(--color-edify-soft)]/60">
        {segments.map((s, i) => (
          <div
            key={s.label}
            className={cn("h-full", colors[i % colors.length])}
            style={{ width: `${(s.value / total) * 100}%` }}
            title={`${s.label}: ${formatUgx(s.value)}`}
          />
        ))}
      </div>
      <div className="flex items-center gap-2.5 flex-wrap text-caption muted">
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

function EvidenceTab({ summary }: { summary: SchoolActivityInvestmentSummary }) {
  const es = summary.evidenceSummary;
  return (
    <div className="space-y-2.5">
      <section className="grid grid-cols-2 lg:grid-cols-5 gap-2">
        <Kpi label="Complete"            value={String(es.complete)}                  tone="good" />
        <Kpi label="Missing"             value={String(es.missing)}                   tone={es.missing > 0 ? "warn" : "neutral"} />
        <Kpi label="Awaiting CCEO"       value={String(es.awaitingCceoConfirmation)}  tone={es.awaitingCceoConfirmation > 0 ? "warn" : "neutral"} />
        <Kpi label="M&E verified"        value={String(es.verifiedByME)}              tone="good" />
        <Kpi label="Returned"            value={String(es.returnedForCorrection)}     tone={es.returnedForCorrection > 0 ? "warn" : "neutral"} />
      </section>

      <section className="rounded-lg border border-[var(--color-edify-divider)] bg-white p-2.5">
        <header className="mb-2">
          <h4 className="text-[12px] font-extrabold tracking-tight">Per-activity evidence status</h4>
          <p className="text-[10px] muted mt-0.5 leading-tight">Filter the timeline by missing/verified to take action on outliers.</p>
        </header>
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {summary.timeline.map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-2 py-2 text-[11px]">
              <span className="min-w-0 flex-1 truncate">
                <span className="font-extrabold text-[var(--color-edify-text)]">{a.title}</span>
                <span className="muted"> · {formatHumanDate(a.date)}</span>
              </span>
              <div className="inline-flex items-center gap-1.5 shrink-0">
                <Pill label={EVIDENCE_LABEL[a.evidenceStatus]}        tone={EVIDENCE_TONE[a.evidenceStatus]} />
                <Pill label={VERIFICATION_LABEL[a.verificationStatus]} tone={VERIFICATION_TONE[a.verificationStatus]} />
              </div>
            </li>
          ))}
          {summary.timeline.length === 0 && (
            <li className="py-3 text-center muted text-[11px]">No activities in scope.</li>
          )}
        </ul>
      </section>
    </div>
  );
}

// ────────── SSA TAB ──────────

function SsaTab({
  summary, onViewFullSsa,
}: {
  summary: SchoolActivityInvestmentSummary;
  onViewFullSsa?: () => void;
}) {
  const s = summary.ssaSummary;
  if (!s) {
    return (
      <section className="rounded-xl border border-rose-200 bg-rose-50/40 p-4 text-center">
        <span className="inline-grid place-items-center h-9 w-9 rounded-md bg-rose-100 text-rose-700 mb-2">
          <ClipboardList size={14} />
        </span>
        <h4 className="text-[12px] font-extrabold tracking-tight">No completed SSA on record</h4>
        <p className="text-[11px] muted mt-1 max-w-md mx-auto leading-snug">
          Planning remains locked until current-cycle SSA is completed. Open the
          dedicated SSA performance drawer for historical context.
        </p>
        {onViewFullSsa && (
          <div className="mt-3">
            <Button size="sm" variant="secondary" onClick={onViewFullSsa} Icon={BookOpen}>Open SSA performance</Button>
          </div>
        )}
      </section>
    );
  }

  const weakStatus     = ssaStatusFor(s.weakestScore);
  const strongStatus   = ssaStatusFor(s.strongestScore);
  const averageStatus  = ssaStatusFor(s.averageScore);
  const change         = s.changeFromPrevious ?? 0;
  const changeTone = change > 0
    ? { Icon: TrendingUp,   bg: "bg-emerald-50", text: "text-emerald-700", label: "Improving" }
    : change < 0
      ? { Icon: TrendingDown, bg: "bg-orange-50",  text: "text-orange-700",  label: "Declining" }
      : { Icon: Minus,        bg: "bg-slate-100",  text: "text-slate-600",   label: "Stable"    };

  return (
    <div className="space-y-2.5">
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-1.5">
        <Kpi label="Latest SSA" value={formatHumanDate(s.latestSsaDate)} />
        <Kpi label="Average"    value={`${s.averageScore.toFixed(1)}/10`} tone={statusToneFor(averageStatus)} />
        <Kpi label="Weakest"    value={`${s.weakestScore}/10`}            sub={s.weakestIntervention}     tone={statusToneFor(weakStatus)} />
        <Kpi label="Strongest"  value={`${s.strongestScore}/10`}          sub={s.strongestIntervention}   tone={statusToneFor(strongStatus)} />
      </section>

      <section className="rounded-md border border-[var(--color-edify-divider)] bg-white px-2.5 py-2 flex items-center gap-2">
        <span className={cn("grid place-items-center h-7 w-7 rounded-md shrink-0", changeTone.bg, changeTone.text)}>
          <changeTone.Icon size={11} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[9.5px] uppercase tracking-wider font-bold muted">Change from previous FY</div>
          <div className="text-[12px] font-extrabold leading-tight mt-0.5">
            {s.changeFromPrevious !== undefined
              ? `${change > 0 ? "+" : ""}${change.toFixed(1)} ${changeTone.label.toLowerCase()}`
              : "No baseline — first SSA on record"}
          </div>
        </div>
        {onViewFullSsa && (
          <Button size="sm" variant="secondary" Icon={BookOpen} onClick={onViewFullSsa}>SSA graph</Button>
        )}
      </section>
    </div>
  );
}

function statusToneFor(s: string): "good" | "warn" | "neutral" {
  if (s === "Strong" || s === "Good") return "good";
  if (s === "Needs Support") return "warn";
  if (s === "Critical") return "warn";
  return "neutral";
}

// ────────── NEXT ACTIONS TAB ──────────

function NextActionsTab({
  summary, onAction,
}: {
  summary: SchoolActivityInvestmentSummary;
  onAction?: (action: SchoolGapAction) => void;
}) {
  const r = summary.nextRecommendedAction;
  if (!r) {
    return (
      <section className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-4 text-center">
        <span className="inline-grid place-items-center h-9 w-9 rounded-md bg-emerald-100 text-emerald-700 mb-2">
          <CheckCircle2 size={14} />
        </span>
        <h4 className="text-[12px] font-extrabold tracking-tight">School is on track</h4>
        <p className="text-[11px] muted mt-1 max-w-md mx-auto leading-snug">
          No outstanding gap detected for the current cycle. The Overview tab shows what has been delivered.
        </p>
      </section>
    );
  }
  return (
    <section className="rounded-lg border border-[var(--color-edify-divider)] bg-white p-2.5">
      <header className="mb-2">
        <h4 className="text-[12px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <Sparkles size={13} className="text-[var(--color-edify-primary)]" />
          Next recommended action
        </h4>
        <p className="text-[10px] muted mt-0.5 leading-tight">Generated from SSA + activity history + cycle gates.</p>
      </header>
      <div className="rounded-md border border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/40 px-2.5 py-2 flex items-start gap-2">
        <span className="grid place-items-center h-7 w-7 rounded-md bg-white text-[var(--color-edify-primary)] border border-[var(--color-edify-border)] shrink-0">
          <AlertTriangle size={11} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[11.5px] font-extrabold tracking-tight leading-tight">{r.title}</p>
          <p className="text-caption muted leading-snug mt-0.5">{r.reason}</p>
        </div>
        {r.action && onAction && (
          <Button size="sm" onClick={() => onAction(r.action!)}>{r.ctaLabel}</Button>
        )}
      </div>
    </section>
  );
}

// ────────── Tiny atoms ──────────

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

// ────────── Helpers ──────────

