"use client";

// CoreSchoolsBoard — the Core School Planning Console body.
//
// Composes:
//   • Summary tiles (No SSA · Ready to start · In cycle · Cycle complete)
//   • No-SSA warning banner when ≥1 core school is still blocked
//   • Three collapsible buckets (No SSA · In cycle · Cycle complete)
//   • CoreSchoolCard list per bucket
//   • Shared PlanningAssignDrawer for owner selection
//
// The board owns assign state + toast so the page route stays a thin
// composition layer.

import { useMemo, useState } from "react";
import {
  AlertOctagon, Activity, CheckCircle2, ChevronDown, ChevronUp,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  coreSchoolPlans,
  coreSchoolSummary,
  progressOf,
  nextCoreGap,
  type CoreSchoolPlan,
} from "@/lib/planning/core-school-plan-mock";
import {
  PlanningAssignDrawer,
  type AssignOutcome,
  type PlanningAssignContext,
} from "@/components/planning/PlanningAssignDrawer";
import { CoreSchoolCard, type CoreAssignRequest } from "./CoreSchoolCard";

type BucketKey = "no_ssa" | "in_cycle" | "complete";

const BUCKET_META: Record<BucketKey, { label: string; Icon: LucideIcon; tone: "danger" | "warn" | "good"; helper: string }> = {
  no_ssa: {
    label: "No SSA — blocked",
    Icon: AlertOctagon,
    tone: "danger",
    helper: "Core activities are disabled until SSA is complete. Schedule SSA first.",
  },
  in_cycle: {
    label: "In the support cycle",
    Icon: Activity,
    tone: "warn",
    helper: "SSA complete. The next visit or training in the 4×4 cycle is below.",
  },
  complete: {
    label: "Cycle complete — follow-up SSA due",
    Icon: CheckCircle2,
    tone: "good",
    helper: "4 visits + 4 trainings delivered. Run the follow-up SSA to measure impact.",
  },
};

const TONE: Record<"danger" | "warn" | "info" | "good", { bg: string; text: string }> = {
  danger: { bg: "bg-rose-50",    text: "text-rose-700"    },
  warn:   { bg: "bg-amber-50",   text: "text-amber-700"   },
  info:   { bg: "bg-blue-50",    text: "text-blue-700"    },
  good:   { bg: "bg-emerald-50", text: "text-emerald-700" },
};

export function CoreSchoolsBoard() {
  const summary = coreSchoolSummary();
  const [collapsed, setCollapsed] = useState<Record<BucketKey, boolean>>({
    no_ssa: false, in_cycle: false, complete: true,
  });
  const [assign, setAssign] = useState<CoreAssignRequest | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  // Group schools by bucket.
  const buckets = useMemo(() => {
    const map: Record<BucketKey, CoreSchoolPlan[]> = { no_ssa: [], in_cycle: [], complete: [] };
    for (const plan of coreSchoolPlans) {
      const rec = nextCoreGap(plan);
      if (rec.gap === "no_ssa")              map.no_ssa.push(plan);
      else if (rec.gap === "cycle_complete") map.complete.push(plan);
      else                                   map.in_cycle.push(plan);
    }
    // Within each bucket, sort by progress so the most-stalled are first.
    map.in_cycle.sort((a, b) => progressOf(a).pct - progressOf(b).pct);
    return map;
  }, []);

  function handleAssignSubmit(outcome: AssignOutcome) {
    const ownerCopy =
      outcome.owner === "myself"  ? "Activity moved to My Plan." :
      outcome.owner === "staff"   ? `Assigned to ${outcome.staffName}.` :
      outcome.owner === "partner" ? `Sent to ${outcome.partnerName} — awaiting partner schedule.` :
      `Facilitator request sent to ${outcome.facilitatorName}.`;
    setToast(ownerCopy);
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
    <div className="space-y-4">
      {/* Summary tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <SummaryTile
          label="Total core schools"
          value={summary.total}
          Icon={Activity}
          tone="info"
          caption="In the SSA-driven support pipeline"
        />
        <SummaryTile
          label="No SSA — blocked"
          value={summary.noSsa}
          Icon={AlertOctagon}
          tone="danger"
          caption="Core support cannot start"
        />
        <SummaryTile
          label="In cycle"
          value={summary.inFlight}
          Icon={Activity}
          tone="warn"
          caption="One or more activities pending"
        />
        <SummaryTile
          label="Cycle complete"
          value={summary.cycleComplete}
          Icon={CheckCircle2}
          tone="good"
          caption="Follow-Up SSA recommended"
        />
      </div>

      {/* No-SSA banner — only when schools are blocked. */}
      {summary.noSsa > 0 && (
        <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3 flex items-start gap-3">
          <span className="grid place-items-center h-9 w-9 rounded-lg bg-rose-100 text-rose-700 shrink-0">
            <AlertOctagon size={16} />
          </span>
          <div className="min-w-0">
            <div className="text-[13px] font-extrabold tracking-tight text-rose-900">
              {summary.noSsa} core {summary.noSsa === 1 ? "school is" : "schools are"} blocked from core support
            </div>
            <p className="text-[11.5px] text-rose-800/90 leading-snug mt-0.5">
              No completed SSA = no core school visit or training schedule. Visit + training buttons stay
              disabled until SSA is complete and the 4 weakest interventions are identified.
            </p>
          </div>
        </div>
      )}

      {/* Bucketed cards */}
      <div className="space-y-3">
        {(Object.keys(BUCKET_META) as BucketKey[]).map((key) => {
          const meta = BUCKET_META[key];
          const tone = TONE[meta.tone];
          const list = buckets[key];
          const isCollapsed = collapsed[key];
          return (
            <section key={key} className="card rounded-2xl">
              <button
                type="button"
                onClick={() => setCollapsed((c) => ({ ...c, [key]: !c[key] }))}
                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-[var(--color-edify-soft)]/40 transition-colors text-left rounded-t-2xl"
              >
                <span className={cn("grid place-items-center h-9 w-9 rounded-lg shrink-0", tone.bg, tone.text)}>
                  <meta.Icon size={15} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] font-extrabold tracking-tight">{meta.label}</div>
                  <div className="text-[11px] muted leading-tight mt-0.5">{meta.helper}</div>
                </div>
                <span className="text-body-lg font-extrabold tabular text-[var(--color-edify-text)]">
                  {list.length}
                </span>
                <span className="text-[var(--color-edify-muted)]">
                  {isCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                </span>
              </button>
              {!isCollapsed && (
                <div className="border-t border-[var(--color-edify-divider)] px-3 py-3">
                  {list.length === 0 ? (
                    <div className="text-[11.5px] muted italic px-2 py-6 text-center">
                      No schools in this state — keep it up.
                    </div>
                  ) : (
                    <ul className="space-y-3">
                      {list.map((plan) => (
                        <CoreSchoolCard key={plan.id} plan={plan} onAssign={setAssign} />
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </section>
          );
        })}
      </div>

      <PlanningAssignDrawer
        open={!!assign}
        context={drawerContext}
        onClose={() => setAssign(null)}
        onSubmit={handleAssignSubmit}
      />

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl shadow-lg bg-emerald-600 text-white text-body font-semibold px-4 py-3 max-w-[400px]">
          {toast}
        </div>
      )}
    </div>
  );
}

function SummaryTile({
  label, value, Icon, tone, caption,
}: {
  label:   string;
  value:   number;
  Icon:    LucideIcon;
  tone:    "danger" | "warn" | "info" | "good";
  caption: string;
}) {
  const t = TONE[tone];
  return (
    <div className="card p-3.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] uppercase tracking-wider font-bold text-[var(--color-edify-muted)] truncate">
          {label}
        </span>
        <span className={cn("grid place-items-center h-7 w-7 rounded-md", t.bg, t.text)}>
          <Icon size={13} />
        </span>
      </div>
      <div className={cn(
        "text-[26px] font-extrabold tabular num-hero leading-none mt-2",
        value === 0 ? "text-[var(--color-edify-muted)]" : "text-[var(--color-edify-text)]",
      )}>
        {value}
      </div>
      <div className="text-caption muted mt-1.5">{caption}</div>
    </div>
  );
}

