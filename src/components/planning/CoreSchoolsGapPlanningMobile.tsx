"use client";

// CoreSchoolsGapPlanningMobile — phone-frame variant of the desktop
// CoreSchoolsGapPlanning section. Same 11-tile summary + 7 tabs, but
// stacked, swipe-scrolled, and tap-to-expand so a thumb can reach it.
//
// The full school list reuses <CoreSchoolCard /> — its 12-col grid
// stacks to a single column at narrow widths so it already behaves on
// phones. We just wrap it in tighter padding + open the drawer.

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  AlertOctagon, Footprints, GraduationCap, Handshake, Clock, ListChecks,
  CheckCircle2, ArrowRight, ChevronDown, ChevronUp, type LucideIcon,
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

const TABS: { key: CorePlanningTab; label: string; Icon: LucideIcon }[] = [
  { key: "no_ssa",                    label: "No SSA",        Icon: AlertOctagon  },
  { key: "visit_gaps",                label: "Visit Gaps",    Icon: Footprints    },
  { key: "training_gaps",             label: "Training Gaps", Icon: GraduationCap },
  { key: "ready_to_plan",             label: "Ready",         Icon: ListChecks    },
  { key: "assigned_to_partner",       label: "Partner",       Icon: Handshake     },
  { key: "awaiting_partner_schedule", label: "Awaiting",      Icon: Clock         },
  { key: "completed",                 label: "Completed",     Icon: CheckCircle2  },
];

export function CoreSchoolsGapPlanningMobile() {
  const s = coreSchoolSummary();
  const [activeTab, setActiveTab] = useState<CorePlanningTab>("no_ssa");
  const [assign, setAssign] = useState<CoreAssignRequest | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  // Whole-section collapse — matches the other planning cards on mobile.
  const [open, setOpen] = useState(true);

  const tabCounts: Record<CorePlanningTab, number> = useMemo(() => ({
    no_ssa:                     s.noSsa,
    visit_gaps:                 s.noFirstVisit + s.noSecondVisit + s.noThirdVisit + s.noFourthVisit,
    training_gaps:              s.noFirstTraining + s.noSecondTraining + s.noThirdTraining + s.noFourthTraining,
    ready_to_plan:              s.ready,
    assigned_to_partner:        s.assignedToPartner,
    awaiting_partner_schedule:  s.awaitingPartnerSchedule,
    completed:                  s.cycleComplete,
  }), [s]);

  const plans = corePlansByTab(activeTab);

  function handleAssignSubmit(outcome: AssignOutcome) {
    const copy =
      outcome.owner === "myself"  ? "Activity moved to My Plan." :
      outcome.owner === "staff"   ? `Assigned to ${outcome.staffName}.` :
      outcome.owner === "partner" ? `Sent to ${outcome.partnerName}.` :
      `Facilitator request sent to ${outcome.facilitatorName}.`;
    setToast(copy);
    setTimeout(() => setToast(null), 3500);
  }

  const drawerContext: PlanningAssignContext | null = assign && {
    title: assign.label,
    schoolOrCluster: assign.plan.schoolName,
    purpose: assign.purpose,
    allowPartnerFacilitator: assign.allowFacilitator,
    allowPartnerOwnership: assign.allowPartner,
  };

  return (
    <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-3">
      <header className="flex items-start justify-between gap-2 mb-2.5">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex items-start gap-2 text-left flex-1 min-w-0"
        >
          <div className="min-w-0 flex-1">
            <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
              Core Schools Gap Planning
              <span className="inline-flex items-center px-1 py-[1px] rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] text-[10px] font-extrabold tabular">
                {s.total}
              </span>
            </h2>
            <p className="text-[11px] muted leading-snug mt-0.5">
              SSA-driven planning for core schools across four priority interventions.
            </p>
          </div>
          <span className="text-[var(--color-edify-muted)] shrink-0 mt-0.5">
            {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </span>
        </button>
        <Link
          href="/planning/core-schools"
          className="inline-flex items-center gap-0.5 text-[11px] font-extrabold text-[var(--color-edify-primary)] shrink-0 mt-0.5"
        >
          Full <ArrowRight size={10} />
        </Link>
      </header>

      {open && <>
      {/* Aggregate count tiles removed — the Core Schools dashboard
          owns those numbers and the tab chips below restate each
          count inline. See the desktop sibling for the same rule. */}

      {/* Tab strip — horizontal scroll for the 7 chips */}
      <div role="tablist" className="-mx-3 px-3 mb-3 flex gap-1.5 overflow-x-auto pb-1">
        {TABS.map((t) => {
          const active = activeTab === t.key;
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setActiveTab(t.key)}
              className={cn(
                "shrink-0 inline-flex items-center gap-1 h-8 px-2.5 rounded-full text-[11px] font-extrabold transition-colors",
                active
                  ? "bg-[var(--color-edify-primary)] text-white"
                  : "bg-white border border-[var(--color-edify-border)] text-[var(--color-edify-text)]",
              )}
            >
              <t.Icon size={11} />
              {t.label}
              <span className={cn(
                "tabular text-[10px] px-1 rounded-sm",
                active ? "bg-white/20 text-white" : "bg-[var(--color-edify-soft)] text-[var(--color-edify-text)]",
              )}>
                {tabCounts[t.key]}
              </span>
            </button>
          );
        })}
      </div>

      {/* Card list */}
      {plans.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/30 px-4 py-6 text-center text-[11px] muted italic">
          No core schools in this tab.
        </div>
      ) : (
        <ul className="space-y-3">
          {plans.map((plan) => (
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
        <div className="fixed bottom-24 left-3 right-3 z-50 rounded-xl shadow-lg bg-emerald-600 text-white text-[12px] font-semibold px-3 py-2.5 text-center">
          {toast}
        </div>
      )}
    </section>
  );
}

