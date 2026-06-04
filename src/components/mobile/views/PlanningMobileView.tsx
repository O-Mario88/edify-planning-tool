"use client";

// PlanningMobileView — phone-shaped variant of the gap-driven /planning
// page. Replaces the legacy month/week/activity-list PlanView so mobile
// finally matches what staff see on desktop:
//   1.  Hero question + tone-coded summary tiles
//   2.  Core school planning entry CTA
//   3.  Schools by gap (4 collapsible buckets, urgent first)
//   4.  Cluster gaps (per-cluster status chips + primary CTA)
//   5.  Scheduling-only banner that points to the School Directory
//
// Tap targets are sized for thumbs; long copy collapses behind expand
// affordances so the page stays scannable. Assignment opens the shared
// PlanningAssignDrawer.

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  AlertOctagon, Footprints, GraduationCap, Users,
  Building2, ChevronDown, ChevronUp, ArrowRight, Lock, CheckCircle2,
  AlertTriangle, Circle, Clock, RotateCw, Handshake, Layers, type LucideIcon,
} from "lucide-react";
import { MobileShell } from "@/components/mobile/MobileShell";
import { MobileBottomNav } from "@/components/mobile/MobileBottomNav";
import { useSetPageTitle } from "@/components/shell/PageTitleContext";
import { cn } from "@/lib/utils";
import {
  schoolGaps,
  clusterGaps,
  recommendFor,
  recommendForCluster,
  GAP_SORT_ORDER,
  type SchoolGap,
  type SchoolGapCategory,
  type SchoolGapAction,
  type ClusterGap,
  type ClusterMeetingStatus,
} from "@/lib/planning/planning-gaps-mock";
import {
  PlanningAssignDrawer,
  type AssignOutcome,
  type PlanningAssignContext,
} from "@/components/planning/PlanningAssignDrawer";
import {
  AddToClusterDrawer,
  type AddToClusterOutcome,
  type AddToClusterContext,
} from "@/components/planning/AddToClusterDrawer";
import { CorePlanBoard } from "@/components/core/CorePlanBoard";
import type { SlotViewer } from "@/components/core/CoreSlotActions";
import type { CorePlanCardVM } from "@/lib/core/core-board";
import { PlanningOwnershipSectionsMobile } from "@/components/planning/PlanningOwnershipSectionsMobile";

// ────────── Mobile view ──────────

export function PlanningMobileView({
  coreCards = [],
  coreViewer = { canAssign: false, canExec: false, canIa: false },
  canChampion = false,
}: {
  coreCards?: CorePlanCardVM[];
  coreViewer?: SlotViewer;
  canChampion?: boolean;
} = {}) {
  useSetPageTitle("Planning");

  // Shared assign state for both school + cluster flows.
  const [assign, setAssign] = useState<
    | { kind: "school"; school: SchoolGap; action: SchoolGapAction }
    | { kind: "cluster"; cluster: ClusterGap; label: string; purpose: string; isTraining: boolean }
    | null
  >(null);
  // Mirror desktop: add_to_cluster routes through its own drawer.
  const [clusterAssign, setClusterAssign] = useState<AddToClusterContext | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  function handleAssignSubmit(outcome: AssignOutcome) {
    const ownerCopy =
      outcome.owner === "myself"  ? (
        outcome.month && outcome.week
          ? `Scheduled for ${outcome.month} · Week ${outcome.week} — moved to My Plan.`
          : "Activity moved to My Plan."
      ) :
      outcome.owner === "staff"   ? `Assigned to ${outcome.staffName}.` :
      outcome.owner === "partner" ? `Sent to ${outcome.partnerName} — awaiting partner schedule.` :
      `Facilitator request sent to ${outcome.facilitatorName}.`;
    setToast(ownerCopy);
    setTimeout(() => setToast(null), 3500);
  }

  function handleClusterSubmit(outcome: AddToClusterOutcome) {
    const copy =
      outcome.mode === "existing"
        ? `${outcome.schoolName} added to ${outcome.clusterName}.`
        : `New cluster ${outcome.clusterName} created in ${outcome.district} · ${outcome.subCounty}. ${outcome.schoolName} attached as the first school.`;
    setToast(copy);
    setClusterAssign(null);
    setTimeout(() => setToast(null), 4500);
  }

  const drawerContext: PlanningAssignContext | null = (() => {
    if (!assign) return null;
    if (assign.kind === "school") {
      const rec = recommendFor(assign.school);
      return {
        title: ACTION_LABEL[assign.action],
        schoolOrCluster: assign.school.schoolName,
        purpose: rec.purpose,
        // Partner-as-facilitator only makes sense for trainings.
        allowPartnerFacilitator: assign.action === "schedule_training",
        // SSA can be assigned to either a CCEO or a certified Partner —
        // partners deliver the bulk of SSA work in the operating model.
        // SSA Verification (separate purpose) stays staff-only via
        // STAFF_ONLY_PURPOSES in plan-cost-calculator, not here.
        allowPartnerOwnership: true,
      };
    }
    return {
      title: assign.label,
      schoolOrCluster: assign.cluster.clusterName,
      purpose: assign.purpose,
      allowPartnerFacilitator: assign.isTraining,
      allowPartnerOwnership: false,
    };
  })();

  return (
    <MobileShell>
      <main className="flex-1 px-3 pt-3 pb-6 space-y-3 bg-[var(--color-page)]">
        {/* ── Hero ─────────────────────────────────────── */}
        <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-4">
          <p className="text-[10px] uppercase tracking-[0.14em] font-extrabold text-[var(--color-edify-muted)]">
            Planning Console
          </p>
          <h1 className="text-[17px] font-extrabold tracking-tight leading-tight mt-1">
            Which client schools and clusters are missing required support?
          </h1>
          <p className="text-[12px] muted leading-relaxed mt-2">
            Each card below shows the{" "}
            <span className="font-extrabold text-[var(--color-edify-text)]">next valid action</span>
            {" "}and who can own it.
          </p>
        </section>

        {/* Aggregate gap tiles removed — the SchoolsBoardMobile and
            ClustersBoardMobile below carry the same counts inline on
            their pill chips, and the Core Schools dashboard owns the
            authoritative per-school numbers. */}

        {/* ── Schools by gap (collapsible buckets) ───────── */}
        <SchoolsBoardMobile
          onAssignSchool={(school, action) => {
            // add_to_cluster has its own dedicated drawer with
            // existing-vs-create-new modes — mirror the desktop routing.
            if (action === "add_to_cluster") {
              setClusterAssign({
                schoolId:   school.id,
                schoolName: school.schoolName,
                cceoName:   school.assignedCceo,
              });
              return;
            }
            setAssign({ kind: "school", school, action });
          }}
        />

        {/* ── Cluster gaps ──────────────────────────────── */}
        <ClustersBoardMobile
          onAssignCluster={(cluster, label, purpose, isTraining) =>
            setAssign({ kind: "cluster", cluster, label, purpose, isTraining })}
        />

        {/* ── Core Schools (unified CorePlan model) ─────── */}
        <CorePlanBoard cards={coreCards} viewer={coreViewer} canChampion={canChampion} />

        {/* ── Ownership sections (Me / Partner / Awaiting / This Month) ── */}
        <PlanningOwnershipSectionsMobile />

        {/* ── Scheduling-only banner ────────────────────── */}
        <Link
          href="/schools"
          className="rounded-2xl bg-[var(--color-edify-soft)]/60 border border-[var(--color-edify-border)] p-3 flex items-start gap-3 active:bg-[var(--color-edify-soft)] transition-colors"
        >
          <span className="grid place-items-center h-9 w-9 rounded-md bg-white text-[var(--color-edify-primary)] border border-[var(--color-edify-border)] shrink-0">
            <Layers size={15} />
          </span>
          <div className="flex-1 min-w-0">
            <div className="text-[12px] font-extrabold leading-tight">
              Planning Tool — visits + trainings only
            </div>
            <div className="text-[11px] muted mt-0.5 leading-snug">
              Clustering happens in the School Directory. Tap to open it.
            </div>
          </div>
          <ArrowRight size={13} className="text-[var(--color-edify-primary)] mt-2 shrink-0" />
        </Link>
      </main>

      <MobileBottomNav />

      <AddToClusterDrawer
        open={!!clusterAssign}
        context={clusterAssign}
        onClose={() => setClusterAssign(null)}
        onSubmit={handleClusterSubmit}
        allowCreate={false}
      />

      <PlanningAssignDrawer
        open={!!assign}
        context={drawerContext}
        onClose={() => setAssign(null)}
        onSubmit={handleAssignSubmit}
      />

      {toast && (
        <div className="fixed bottom-24 left-3 right-3 z-50 rounded-xl shadow-lg bg-emerald-600 text-white text-[12px] font-semibold px-3 py-2.5 text-center">
          {toast}
        </div>
      )}
    </MobileShell>
  );
}

// ────────── Summary tile ──────────

const TONE: Record<"danger" | "warn" | "info" | "good", { bg: string; text: string }> = {
  danger: { bg: "bg-rose-50",    text: "text-rose-700"    },
  warn:   { bg: "bg-amber-50",   text: "text-amber-700"   },
  info:   { bg: "bg-blue-50",    text: "text-blue-700"    },
  good:   { bg: "bg-emerald-50", text: "text-emerald-700" },
};


// ────────── Schools board (mobile) ──────────

const SCHOOL_CAT_META: Record<SchoolGapCategory, { label: string; Icon: LucideIcon; tone: keyof typeof TONE; helper: string }> = {
  no_ssa:      { label: "No SSA",      Icon: AlertOctagon,  tone: "danger", helper: "Schedule SSA first." },
  no_training: { label: "No Training", Icon: GraduationCap, tone: "warn",   helper: "SIT from weakest area." },
  no_visit:    { label: "No Visit",    Icon: Footprints,    tone: "warn",   helper: "First support visit." },
  no_cluster:  { label: "No Cluster",  Icon: Users,         tone: "info",   helper: "Add to a peer cluster." },
};

const ACTION_LABEL: Record<SchoolGapAction, string> = {
  schedule_ssa:           "Schedule SSA",
  schedule_support_visit: "Schedule Support Visit",
  schedule_training:      "Schedule Training",
  schedule_follow_up:     "Schedule Follow-Up",
  schedule_coaching:      "Schedule Coaching",
  add_to_cluster:         "Add to Cluster",
  assign_partner:         "Assign to Partner",
  view_school:            "View School",
  view_ssa:               "View SSA",
};

function SchoolsBoardMobile({
  onAssignSchool,
}: {
  onAssignSchool: (s: SchoolGap, action: SchoolGapAction) => void;
}) {
  const [collapsed, setCollapsed] = useState<Record<SchoolGapCategory, boolean>>({
    no_ssa: false, no_training: true, no_visit: true, no_cluster: true,
  });

  const groups = useMemo(() => {
    const map: Record<SchoolGapCategory, SchoolGap[]> = {
      no_ssa: [], no_training: [], no_visit: [], no_cluster: [],
    };
    for (const s of schoolGaps) map[s.gapCategory].push(s);
    return map;
  }, []);

  return (
    <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm">
      <header className="px-3 pt-3 pb-2">
        <h2 className="text-[12px] font-extrabold tracking-tight">Client school gaps</h2>
        <p className="text-[11px] muted leading-tight mt-0.5">
          Tap a bucket to expand. No-SSA schools only show the SSA action.
        </p>
      </header>
      <div className="border-t border-[#eef2f4]">
        {GAP_SORT_ORDER.map((cat) => {
          const list  = groups[cat];
          const meta  = SCHOOL_CAT_META[cat];
          const tone  = TONE[meta.tone];
          const isOpen = !collapsed[cat];
          return (
            <div key={cat} className="border-b border-[#eef2f4] last:border-b-0">
              <button
                type="button"
                onClick={() => setCollapsed((c) => ({ ...c, [cat]: !c[cat] }))}
                className="w-full flex items-center gap-2 px-3 py-2.5 active:bg-[var(--color-edify-soft)]/40 text-left"
              >
                <span className={cn("grid place-items-center h-7 w-7 rounded-md shrink-0", tone.bg, tone.text)}>
                  <meta.Icon size={12} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-[12px] font-extrabold tracking-tight">{meta.label}</div>
                  <div className="text-[10px] muted leading-tight">{meta.helper}</div>
                </div>
                <span className="text-[12px] font-extrabold tabular shrink-0">{list.length}</span>
                <span className="text-[var(--color-edify-muted)] shrink-0">
                  {isOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                </span>
              </button>
              {isOpen && (
                <ul className="border-t border-[#eef2f4] divide-y divide-[var(--color-edify-divider)]">
                  {list.length === 0 ? (
                    <li className="text-[11px] muted italic px-3 py-4 text-center">
                      No schools in this state.
                    </li>
                  ) : (
                    list.map((s) => (
                      <SchoolRowMobile key={s.id} school={s} onAction={(a) => onAssignSchool(s, a)} />
                    ))
                  )}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

const RISK_TONE: Record<SchoolGap["riskLevel"], string> = {
  Critical: "bg-rose-100 text-rose-800",
  High:     "bg-rose-50 text-rose-700",
  Medium:   "bg-amber-50 text-amber-700",
  Low:      "bg-emerald-50 text-emerald-700",
};

function SchoolRowMobile({
  school: s, onAction,
}: {
  school: SchoolGap;
  onAction: (action: SchoolGapAction) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const rec = recommendFor(s);
  const ssaBlocked = !s.ssaCompleted;

  // Mobile keeps the row tight — primary action + view shown by default,
  // tap-to-expand to reveal recommendation copy + secondary actions.
  return (
    <li className="px-3 py-2.5">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left flex items-start gap-2"
      >
        <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0 mt-0.5">
          <Building2 size={12} />
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <h3 className="text-[12px] font-extrabold tracking-tight truncate flex-1">
              {s.schoolName}
            </h3>
            <span className={cn(
              "inline-flex items-center px-1.5 py-[1px] rounded-md text-[10px] font-extrabold uppercase tracking-wide shrink-0",
              RISK_TONE[s.riskLevel],
            )}>
              {s.riskLevel}
            </span>
          </div>
          <div className="text-[10px] muted truncate">
            {s.district} · {s.subCounty}
          </div>
          {s.weakestArea && !ssaBlocked && (
            <div className="text-[10px] mt-0.5">
              <span className="muted">Weakest: </span>
              <span className="font-extrabold text-[var(--color-edify-text)]">
                {s.weakestArea.area} {s.weakestArea.score}/10
              </span>
            </div>
          )}
        </div>
        {expanded ? <ChevronUp size={13} className="text-[var(--color-edify-muted)] mt-1 shrink-0" />
                  : <ChevronDown size={13} className="text-[var(--color-edify-muted)] mt-1 shrink-0" />}
      </button>

      {expanded && (
        <div className="mt-2 pl-9 space-y-2">
          <div className="rounded-md bg-[var(--color-edify-soft)]/50 border border-[var(--color-edify-divider)] px-2.5 py-2">
            <div className="text-[10px] uppercase tracking-wider font-bold muted">Next action</div>
            <p className="text-[11px] font-extrabold text-[var(--color-edify-text)] mt-0.5">{rec.headline}</p>
            <p className="text-[11px] muted leading-snug mt-0.5">{rec.purpose}</p>
          </div>

          <button
            type="button"
            onClick={() => onAction(rec.primaryAction)}
            className="w-full inline-flex items-center justify-center gap-1 h-9 px-3 rounded-md bg-[var(--color-edify-primary)] text-white text-[12px] font-extrabold active:bg-[var(--color-edify-dark)]"
          >
            {rec.primaryLabel}
            <ArrowRight size={12} />
          </button>

          {ssaBlocked && rec.disabledReason && (
            <div className="text-[10px] muted leading-snug flex items-start gap-1.5">
              <Lock size={10} className="mt-0.5 text-rose-500 shrink-0" />
              <span>{rec.disabledReason}</span>
            </div>
          )}

          {/* Secondary actions row — skip the primary; respect SSA gate. */}
          <div className="grid grid-cols-2 gap-1.5">
            {rec.allowedActions
              .filter((a) => a !== rec.primaryAction)
              .slice(0, 4)
              .map((action) => {
                const disabled = ssaBlocked &&
                  action !== "schedule_ssa" &&
                  action !== "view_school";
                return (
                  <button
                    key={action}
                    type="button"
                    onClick={() => !disabled && onAction(action)}
                    disabled={disabled}
                    className={cn(
                      "inline-flex items-center justify-center gap-1 h-8 px-2 rounded-md text-[11px] font-semibold",
                      disabled
                        ? "bg-slate-100 text-slate-400"
                        : "border border-[var(--color-edify-border)] bg-white text-[var(--color-edify-text)] active:bg-[var(--color-edify-soft)]/60",
                    )}
                  >
                    {ACTION_LABEL[action]}
                  </button>
                );
              })}
          </div>
        </div>
      )}
    </li>
  );
}

// ────────── Clusters board (mobile) ──────────

const MEETING_TONE: Record<ClusterMeetingStatus, { bg: string; text: string; Icon: LucideIcon }> = {
  Completed:     { bg: "bg-emerald-50", text: "text-emerald-700", Icon: CheckCircle2 },
  Scheduled:     { bg: "bg-sky-50",     text: "text-sky-700",     Icon: Clock },
  Rescheduled:   { bg: "bg-amber-50",   text: "text-amber-700",   Icon: RotateCw },
  Missing:       { bg: "bg-rose-50",    text: "text-rose-700",    Icon: AlertTriangle },
  "Not Yet Due": { bg: "bg-slate-100",  text: "text-slate-600",   Icon: Circle },
};

function ClustersBoardMobile({
  onAssignCluster,
}: {
  onAssignCluster: (c: ClusterGap, label: string, purpose: string, isTraining: boolean) => void;
}) {
  // Section-level collapse matches every other planning card on mobile.
  const [open, setOpen] = useState(true);
  return (
    <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full px-3 pt-3 pb-2 flex items-start gap-2 text-left active:bg-[var(--color-edify-soft)]/30 transition-colors rounded-t-2xl"
      >
        <div className="flex-1 min-w-0">
          <h2 className="text-[12px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            Cluster gaps
            <span className="inline-flex items-center px-1 py-[1px] rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] text-[10px] font-extrabold tabular">
              {clusterGaps.length}
            </span>
          </h2>
          <p className="text-[11px] muted leading-tight mt-0.5">
            Missing meetings + School Improvement Trainings. SIT is gated on SSA coverage.
          </p>
        </div>
        <span className="text-[var(--color-edify-muted)] shrink-0 mt-0.5">
          {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </span>
      </button>
      {open && (
        <ul className="border-t border-[#eef2f4] divide-y divide-[var(--color-edify-divider)]">
          {clusterGaps.map((c) => (
            <ClusterRowMobile key={c.id} cluster={c} onAssign={onAssignCluster} />
          ))}
        </ul>
      )}
    </section>
  );
}

function ClusterRowMobile({
  cluster: c, onAssign,
}: {
  cluster: ClusterGap;
  onAssign: (c: ClusterGap, label: string, purpose: string, isTraining: boolean) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const rec = recommendForCluster(c);
  const sitBlocked = !!rec.sitDisabledReason;
  const isPrimaryTraining = rec.primaryAction === "schedule_sit";

  return (
    <li className="px-3 py-2.5">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left flex items-start gap-2"
      >
        <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0 mt-0.5">
          <Users size={12} />
        </span>
        <div className="flex-1 min-w-0">
          <h3 className="text-[12px] font-extrabold tracking-tight truncate">{c.clusterName}</h3>
          <div className="text-[10px] muted leading-tight">
            {c.district} · {c.schoolsCount} schools · {c.schoolsWithSsa} with SSA
          </div>
          {/* 4 mini chips — SIT first (it's the first activity in the
              cluster training cycle), then meetings 1 → 2 → 3. */}
          <div className="flex items-center gap-1 mt-1.5 flex-wrap">
            <MiniMeetingChip label="SIT" status={c.schoolImprovementTraining} />
            <MiniMeetingChip label="M1"  status={c.firstMeeting} />
            <MiniMeetingChip label="M2"  status={c.secondMeeting} />
            <MiniMeetingChip label="M3"  status={c.thirdMeeting} />
          </div>
        </div>
        {expanded ? <ChevronUp size={13} className="text-[var(--color-edify-muted)] mt-1 shrink-0" />
                  : <ChevronDown size={13} className="text-[var(--color-edify-muted)] mt-1 shrink-0" />}
      </button>

      {expanded && (
        <div className="mt-2 pl-9 space-y-2">
          <div className="rounded-md bg-[var(--color-edify-soft)]/50 border border-[var(--color-edify-divider)] px-2.5 py-2">
            <div className="text-[10px] uppercase tracking-wider font-bold muted">Next action</div>
            <p className="text-[11px] font-extrabold text-[var(--color-edify-text)] mt-0.5">{rec.headline}</p>
            <p className="text-[11px] muted leading-snug mt-0.5">{rec.purpose}</p>
          </div>

          <button
            type="button"
            onClick={() => {
              if (sitBlocked && isPrimaryTraining) return;
              onAssign(c, rec.primaryLabel, rec.purpose, isPrimaryTraining);
            }}
            disabled={sitBlocked && isPrimaryTraining}
            className={cn(
              "w-full inline-flex items-center justify-center gap-1 h-9 px-3 rounded-md text-[12px] font-extrabold",
              sitBlocked && isPrimaryTraining
                ? "bg-slate-100 text-slate-400"
                : "bg-[var(--color-edify-primary)] text-white active:bg-[var(--color-edify-dark)]",
            )}
          >
            {rec.primaryLabel}
            {!(sitBlocked && isPrimaryTraining) && <ArrowRight size={12} />}
          </button>

          {sitBlocked && isPrimaryTraining && (
            <div className="text-[10px] muted leading-snug flex items-start gap-1.5">
              <Lock size={10} className="mt-0.5 text-rose-500 shrink-0" />
              <span>{rec.sitDisabledReason}</span>
            </div>
          )}

          <button
            type="button"
            onClick={() => onAssign(c, "Assign partner as facilitator", rec.purpose, true)}
            className="w-full inline-flex items-center justify-center gap-1 h-8 px-2 rounded-md border border-[var(--color-edify-border)] bg-white text-[11px] font-semibold active:bg-[var(--color-edify-soft)]/60"
          >
            <Handshake size={11} /> Partner facilitator
          </button>
        </div>
      )}
    </li>
  );
}

function MiniMeetingChip({ label, status }: { label: string; status: ClusterMeetingStatus }) {
  const tone = MEETING_TONE[status];
  return (
    <span
      className={cn("inline-flex items-center gap-0.5 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold", tone.bg, tone.text)}
      title={`${label} — ${status}`}
    >
      <tone.Icon size={9} />
      {label}
    </span>
  );
}
