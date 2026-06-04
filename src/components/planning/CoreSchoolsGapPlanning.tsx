"use client";

// CoreSchoolsGapPlanning — the SSA-driven planning section on the main
// /planning page. Sits directly below the Cluster Gap Card.
//
// Surface:
//   1. Section header + subtitle (with Open full console link)
//   2. Tab strip (7 tabs) — each tab filters the school list and
//      shows its own count badge inline
//   3. Helper line for the active tab
//   4. Filtered list of <CoreSchoolCard /> reusing the existing card
//      (SSA gating, 4 priority interventions, 4×4 cycle, next-action
//      recommendation, assignment via PlanningAssignDrawer)
//
// The aggregate "No SSA / No Visits / No 1st–4th Training / Cycle
// complete" tile rows that used to live above the tab strip were
// removed: the Core Schools dashboard owns those numbers, and the
// tab badges below already restate them inline. Keeping them here
// duplicated the source of truth and added vertical noise.
//
// The component owns its own assign drawer + toast so the page-level
// composition stays a thin scroll of sections.

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertOctagon, Footprints, GraduationCap, Activity, Handshake, Clock,
  CheckCircle2, ListChecks, ArrowRight, ChevronDown, ChevronUp,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  coreSchoolSummary,
  corePlansByTab,
  type CorePlanningTab,
} from "@/lib/planning/core-school-plan-mock";
import {
  PlanningAssignDrawer,
  type AssignOutcome,
  type PlanningAssignContext,
} from "@/components/planning/PlanningAssignDrawer";
import { CoreSchoolCard, type CoreAssignRequest } from "@/components/planning/CoreSchoolCard";
import { PlanningEmptyState } from "@/components/planning/PlanningEmptyState";

// ────────── Tab metadata ──────────

const TABS: { key: CorePlanningTab; label: string; Icon: LucideIcon; tone: TileTone; helper: string }[] = [
  { key: "no_ssa",                    label: "No SSA",                  Icon: AlertOctagon, tone: "danger", helper: "Only Schedule SSA is allowed for these schools. The SSA can be assigned to a CCEO or to a certified Partner." },
  { key: "visit_gaps",                label: "Visit Gaps",              Icon: Footprints,   tone: "warn",   helper: "SSA complete, one or more visits still missing." },
  { key: "training_gaps",             label: "Training Gaps",           Icon: GraduationCap,tone: "warn",   helper: "SSA complete, one or more trainings still missing." },
  { key: "ready_to_plan",             label: "Ready to Plan",           Icon: ListChecks,   tone: "info",   helper: "SSA complete, priority interventions identified, nothing scheduled yet." },
  { key: "assigned_to_partner",       label: "Assigned to Partner",     Icon: Handshake,    tone: "info",   helper: "At least one core activity owned by or facilitated by a partner." },
  { key: "awaiting_partner_schedule", label: "Awaiting Partner Schedule", Icon: Clock,      tone: "warn",   helper: "Partner-assigned core activities still without a delivery date." },
  { key: "completed",                 label: "Completed Core Support",  Icon: CheckCircle2, tone: "good",   helper: "4 visits + 4 trainings delivered. Follow-Up SSA recommended." },
];

type TileTone = "danger" | "warn" | "info" | "good";

const TILE_TONE: Record<TileTone, { bg: string; text: string; ring: string }> = {
  danger: { bg: "bg-rose-50",    text: "text-rose-700",    ring: "ring-rose-100"    },
  warn:   { bg: "bg-amber-50",   text: "text-amber-700",   ring: "ring-amber-100"   },
  info:   { bg: "bg-blue-50",    text: "text-blue-700",    ring: "ring-blue-100"    },
  good:   { bg: "bg-emerald-50", text: "text-emerald-700", ring: "ring-emerald-100" },
};

// ────────── Component ──────────

export function CoreSchoolsGapPlanning({
  assigningUserRole = "CountryProgramLead",
  assignedGapIds = [],
}: {
  /**
   * Role of the user viewing the planning page. Threaded through to
   * the assign drawer so CCEOs see only the Partner option per the
   * Section 1 permissions contract. Defaults to PL — the most common
   * planning operator.
   */
  assigningUserRole?: "CCEO" | "CountryProgramLead" | "ImpactAssessment" | "CountryDirector" | "Admin";
  /** Plan ids already assigned (from the server assignment overlay) — seeded
   *  into the dismissed set so an assigned core gap stays gone across reloads. */
  assignedGapIds?: string[];
} = {}) {
  const s = coreSchoolSummary();
  const [activeTab, setActiveTab] = useState<CorePlanningTab>("no_ssa");
  const [assign, setAssign] = useState<CoreAssignRequest | null>(null);
  // Confirmed-assigned plans drop off the gap list per the operating
  // contract. Local state for the demo; production routes through a
  // gap-list query that excludes assigned-to-partner / partner-planned.
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(() => new Set(assignedGapIds));
  const [toast, setToast] = useState<string | null>(null);
  // Section-level collapse mirrors the School Gaps + Cluster Gaps cards
  // so the whole planning page collapses to a clean outline.
  const [open, setOpen] = useState(true);

  // Per-tab counts for the chip strip.
  const tabCounts: Record<CorePlanningTab, number> = useMemo(() => ({
    no_ssa:                     s.noSsa,
    visit_gaps:                 s.noFirstVisit + s.noSecondVisit + s.noThirdVisit + s.noFourthVisit,
    training_gaps:              s.noFirstTraining + s.noSecondTraining + s.noThirdTraining + s.noFourthTraining,
    ready_to_plan:              s.ready,
    assigned_to_partner:        s.assignedToPartner,
    awaiting_partner_schedule:  s.awaitingPartnerSchedule,
    completed:                  s.cycleComplete,
  }), [s]);

  const plansInTab = useMemo(() => {
    return corePlansByTab(activeTab).filter((p) => !dismissedIds.has(p.id));
  }, [activeTab, dismissedIds]);

  function handleAssignSubmit(outcome: AssignOutcome) {
    const ownerCopy =
      outcome.owner === "myself"  ? (
        outcome.month && outcome.week
          ? `Scheduled for ${outcome.month} · Week ${outcome.week} — moved to My Plan.`
          : "Activity moved to My Plan."
      ) :
      outcome.owner === "staff"   ? `Assigned to ${outcome.staffName}.` :
      outcome.owner === "partner" ? `Sent to ${outcome.partnerName} — awaiting partner planning.` :
      `Facilitator request sent to ${outcome.facilitatorName}.`;
    setToast(ownerCopy);
    // Confirm Assignment removes the plan from the gap list.
    if (assign?.plan?.id) {
      setDismissedIds((prev) => {
        const next = new Set(prev);
        next.add(assign.plan.id);
        return next;
      });
    }
    setTimeout(() => setToast(null), 3500);
  }

  const drawerContext: PlanningAssignContext | null = assign && {
    gapId: assign.plan.id,
    title: assign.label,
    schoolOrCluster: assign.plan.schoolName,
    purpose: assign.purpose,
    allowPartnerFacilitator: assign.allowFacilitator,
    allowPartnerOwnership: assign.allowPartner,
    // PL is the default role for the demo planning surface. Production
    // threads getCurrentUser().role through CoreSchoolsGapPlanning.
    // CCEO-side mounts override this prop to "CCEO" so only Partner
    // owner option renders.
    assigningUserRole: assigningUserRole,
  };

  return (
    <section className="card p-3.5">
      {/* ── Header — clickable to collapse the entire section ───── */}
      <header className="flex items-start justify-between gap-3 mb-3">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex items-start gap-2 text-left flex-1 min-w-0 -m-1 p-1 rounded-md hover:bg-[var(--color-edify-soft)]/30 transition-colors"
        >
          <div className="min-w-0 flex-1">
            <h2 className="text-[16px] font-extrabold tracking-tight inline-flex items-center gap-2">
              Core Schools Gap Planning
              <span className="inline-flex items-center px-1.5 py-[2px] rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] text-[10px] font-extrabold tabular">
                {s.total}
              </span>
            </h2>
            <p className="text-[12px] muted mt-0.5 leading-snug max-w-[80ch]">
              SSA-driven planning for core schools across four priority interventions. No completed SSA = no
              core visit or training schedule.
            </p>
          </div>
          <span className="text-[var(--color-edify-muted)] shrink-0 mt-1">
            {open ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
          </span>
        </button>
        <Link
          href="/planning/core-schools"
          className="inline-flex items-center gap-1 text-[11px] font-extrabold text-[var(--color-edify-primary)] hover:text-[var(--color-edify-dark)] shrink-0 mt-1"
        >
          Open full console <ArrowRight size={11} />
        </Link>
      </header>

      {open && <>

      {/* ── Tab strip ─────────────────────────────────
          Horizontal scroll on tablet (md) where 7 chips would otherwise
          wrap to 2 rows; unwrapped chip bar from lg upward. */}
      <div
        role="tablist"
        className="flex gap-1.5 border-b border-[var(--color-edify-divider)] pb-2.5 mb-3 overflow-x-auto lg:flex-wrap lg:overflow-visible -mx-1 px-1"
      >
        {TABS.map((t) => {
          const isActive = activeTab === t.key;
          const tone = TILE_TONE[t.tone];
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveTab(t.key)}
              className={cn(
                "shrink-0 inline-flex items-center gap-1.5 h-9 px-3 rounded-full text-[12px] font-extrabold transition-colors whitespace-nowrap",
                isActive
                  ? "bg-[var(--color-edify-primary)] text-white shadow-sm"
                  : "bg-white border border-[var(--color-edify-border)] text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60",
              )}
            >
              <t.Icon size={12} className={isActive ? "" : tone.text} />
              {t.label}
              <span className={cn(
                "tabular text-[11px] px-1.5 py-[1px] rounded-md",
                isActive ? "bg-white/20 text-white" : "bg-[var(--color-edify-soft)] text-[var(--color-edify-text)]",
              )}>
                {tabCounts[t.key]}
              </span>
            </button>
          );
        })}
      </div>

      {/* ── Active-tab helper line ───────────────────── */}
      <div className="text-[11px] muted mb-3 px-0.5 flex items-center gap-1.5">
        <Activity size={11} />
        {TABS.find((t) => t.key === activeTab)?.helper}
      </div>

      {/* ── Card list ────────────────────────────────── */}
      {plansInTab.length === 0 ? (
        <PlanningEmptyState
          variant={activeTab === "completed" ? "good" : "calm"}
          title={emptyStateTitle(activeTab)}
          body={emptyStateBody(activeTab)}
        />
      ) : (
        <ul className="space-y-3">
          {plansInTab.map((plan) => (
            <CoreSchoolCard key={plan.id} plan={plan} onAssign={setAssign} />
          ))}
        </ul>
      )}
      </>}

      <PlanningAssignDrawer
        open={!!assign}
        context={drawerContext}
        onClose={() => setAssign(null)}
        onSubmit={handleAssignSubmit}
      />

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl shadow-lg bg-emerald-600 text-white text-[12px] font-semibold px-4 py-3 max-w-[400px]">
          {toast}
        </div>
      )}
    </section>
  );
}

// ────────── Internal — per-tab empty state copy ──────────

function emptyStateTitle(tab: CorePlanningTab): string {
  switch (tab) {
    case "no_ssa":                    return "Every core school has an SSA.";
    case "visit_gaps":                return "All visits are accounted for.";
    case "training_gaps":             return "All trainings are accounted for.";
    case "ready_to_plan":             return "Nothing waiting in the wings.";
    case "assigned_to_partner":       return "No partner-assigned core activities yet.";
    case "awaiting_partner_schedule": return "All partner-assigned activities are scheduled.";
    case "completed":                 return "No cycles fully complete yet — that's normal.";
  }
}

function emptyStateBody(tab: CorePlanningTab): string {
  switch (tab) {
    case "no_ssa":
      return "When a core school's SSA expires or hasn't started, it will appear here with a single Schedule SSA action.";
    case "visit_gaps":
      return "Visit gaps appear here as core schools work through the 4 priority interventions.";
    case "training_gaps":
      return "Training gaps appear here as core schools work through their support cycle.";
    case "ready_to_plan":
      return "Schools land here right after their SSA completes — before the first activity is scheduled.";
    case "assigned_to_partner":
      return "Assign a visit or training to a partner from any of the other tabs to populate this view.";
    case "awaiting_partner_schedule":
      return "If a partner-owned activity is overdue for scheduling it will surface here so you can bump them.";
    case "completed":
      return "Schools land here once all 4 visits + 4 trainings are verified. Follow-Up SSA recommended next.";
  }
}

