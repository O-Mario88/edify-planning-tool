"use client";

// ClusterGapsBoard — clusters with missing meetings or School
// Improvement Training. Same gap-driven shape as the school board.
// School Improvement Training is gated on enough schools having
// SSA — disabled buttons explain the gate inline.

import { useMemo, useState } from "react";
import { formatUgxShort as formatUgx } from "@/lib/format-utils";
import {
  Users, Calendar, AlertTriangle, ArrowRight, CheckCircle2, Circle, Clock, RotateCw,
  Lock, Handshake, ChevronDown, ChevronRight, ChevronUp, CalendarCheck, Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  clusterGaps,
  CLUSTER_MEETING_SLOT_LABEL,
  recommendForCluster,
  type ClusterGap,
  type ClusterMeetingStatus,
  type ClusterMeetingSlot,
} from "@/lib/planning/planning-gaps-mock";
import {
  PlanningAssignDrawer,
  type AssignOutcome,
  type PlanningAssignContext,
} from "@/components/planning/PlanningAssignDrawer";
import {
  RescheduleClusterMeetingDrawer,
  type RescheduleOutcome,
  type RescheduleContext,
} from "@/components/planning/RescheduleClusterMeetingDrawer";
import {
  ScheduleActivityDrawer,
  type ScheduleActivityContext,
  type ScheduleActivityOutcome,
} from "@/components/planning/ScheduleActivityDrawer";
import {
  ClusterActivityProfileDrawer,
  type ClusterActivityProfileContext,
} from "@/components/planning/ClusterActivityProfileDrawer";
import { scheduleClusterMeetingAction } from "@/lib/actions/cluster-actions";
import type { ClusterMeetingKind } from "@/lib/cluster/cluster-core";

/**
 * Translate a cluster gap + slot into the unified ScheduleActivityDrawer's
 * context. Centralized so the drawer doesn't have to know about cluster
 * vs. school terminology, and so the SIP eligibility warning (cluster SIT
 * only) lives in one obvious place.
 */
function buildClusterScheduleContext(c: ClusterGap, slot: ClusterMeetingSlot): ScheduleActivityContext {
  const isTraining = slot === "sit";
  const missing    = Math.max(0, c.schoolsCount - c.schoolsWithSsa);
  return {
    target: { kind: "cluster", id: c.id, name: c.clusterName },
    activityType:        CLUSTER_MEETING_SLOT_LABEL[slot],
    isTraining,
    defaultParticipants: c.schoolsCount * 2,
    defaultProposedBy:   `${c.assignedCceo} (CCEO)`,
    locationLine:        c.district,
    clusterSummary:      `${c.schoolsCount} schools · ${c.schoolsWithSsa} with SSA · CCEO ${c.assignedCceo}`,
    // SIP eligibility warning — only meaningful for SIT (training is
    // gated on SSA). For routine meetings every school in the cluster
    // attends regardless of SSA status.
    ssaShortfall: isTraining && missing > 0
      ? { missing, total: c.schoolsCount }
      : undefined,
  };
}

const MEETING_TONE: Record<ClusterMeetingStatus, { bg: string; text: string; Icon: typeof CheckCircle2 }> = {
  Completed:    { bg: "bg-emerald-50", text: "text-emerald-700", Icon: CheckCircle2 },
  Scheduled:    { bg: "bg-sky-50",     text: "text-sky-700",     Icon: Clock        },
  Rescheduled:  { bg: "bg-amber-50",   text: "text-amber-700",   Icon: RotateCw     },
  Missing:      { bg: "bg-rose-50",    text: "text-rose-700",    Icon: AlertTriangle },
  "Not Yet Due":{ bg: "bg-slate-100",  text: "text-slate-600",   Icon: Circle },
};

export function ClusterGapsBoard({
  assigningUserRole = "CountryProgramLead",
  gaps,
  liveGaps = false,
}: {
  /** Role threaded to the assign drawer for owner-option gating. */
  assigningUserRole?: "CCEO" | "CountryProgramLead" | "ImpactAssessment" | "CountryDirector" | "Admin";
  /** Engine-derived cluster gaps (from the real cluster engine). Falls back to
   *  the seed mock only when not provided (standalone/storybook use). */
  gaps?: ClusterGap[];
  /** True when gaps are REAL backend clusters: schedule through the live writer
   *  (POST /api/activities with the cluster's real id). */
  liveGaps?: boolean;
} = {}) {
  // Source of truth = engine-derived gaps passed by the Planning page; the
  // imported seed list is only a standalone fallback.
  const data = gaps ?? clusterGaps;
  const [assign, setAssign] = useState<{ cluster: ClusterGap; label: string; purpose: string; isTraining: boolean } | null>(null);
  const [reschedule, setReschedule] = useState<RescheduleContext | null>(null);
  // Initial scheduling for a cluster meeting / SIT — opens the unified
  // ScheduleActivityDrawer. We carry the slot alongside the context so
  // the overlay write can key off the cluster's slot without the drawer
  // having to know about cluster-specific terminology.
  const [scheduleAssign, setScheduleAssign] = useState<
    | { context: ScheduleActivityContext; cluster: ClusterGap; slot: ClusterMeetingSlot }
    | null
  >(null);
  /**
   * Per-slot scheduling overlay. Key = `${clusterId}:${slot}`. When a
   * slot is scheduled in this session, the overlay forces the chip
   * to render as Scheduled with the chosen date — without mutating
   * the underlying mock. Production swaps this for a real cluster
   * schedule write.
   */
  const [scheduleOverlay, setScheduleOverlay] = useState<Map<string, { date: string; proposedBy: string }>>(new Map());
  // View cluster → opens the activity, performance & investment
  // profile drawer (meetings + trainings + SSA + school potential
  // + costs + evidence + next actions).
  const [clusterProfile, setClusterProfile] = useState<ClusterActivityProfileContext | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  function overlayKey(clusterId: string, slot: ClusterMeetingSlot): string {
    return `${clusterId}:${slot}`;
  }
  function overlayFor(clusterId: string, slot: ClusterMeetingSlot) {
    return scheduleOverlay.get(overlayKey(clusterId, slot));
  }
  // Whole-card collapse matches the School Gaps + Core Schools cards —
  // the planning page stays scannable when every section is closed.
  const [open, setOpen] = useState(true);

  function handleAssignSubmit(outcome: AssignOutcome) {
    const ownerCopy =
      outcome.owner === "myself"  ? (
        outcome.month && outcome.week
          ? `Cluster activity scheduled for ${outcome.month} · Week ${outcome.week} — moved to My Plan.`
          : "Cluster activity moved to My Plan."
      ) :
      outcome.owner === "staff"   ? `Cluster activity assigned to ${outcome.staffName}.` :
      outcome.owner === "partner" ? `Sent to ${outcome.partnerName} — awaiting partner schedule.` :
      `Facilitator request sent to ${outcome.facilitatorName}.`;
    setToast(ownerCopy);
    setTimeout(() => setToast(null), 3500);
  }

  function handleRescheduleSubmit(outcome: RescheduleOutcome) {
    setToast(
      `Rescheduled to ${outcome.newDate} — cluster leader + facilitator notified. (${outcome.reason})`,
    );
    setReschedule(null);
    setTimeout(() => setToast(null), 4500);
  }

  function handleScheduleSubmit(outcome: ScheduleActivityOutcome) {
    const pending = scheduleAssign;
    if (!pending) return;

    const costFragment = outcome.projectedCostUgx
      ? ` · Projected cost ${formatUgx(outcome.projectedCostUgx)} (${outcome.participants} participants)`
      : outcome.participants
        ? ` · ${outcome.participants} participants`
        : "";
    const partnerFragment = outcome.partnerFacilitator
      ? ` Facilitator: ${outcome.partnerFacilitator}.`
      : "";
    setToast(
      `${pending.cluster.clusterName} · ${outcome.activityType} scheduled for ${outcome.date}.${costFragment}${partnerFragment} Added to My Plan.`,
    );
    // Push the slot into the overlay so the MeetingChip flips to
    // Scheduled + the chosen date without waiting for a refresh.
    setScheduleOverlay((prev) => {
      const next = new Map(prev);
      next.set(overlayKey(pending.cluster.id, pending.slot), {
        date:       outcome.date,
        proposedBy: outcome.proposedBy,
      });
      return next;
    });
    setScheduleAssign(null);
    setTimeout(() => setToast(null), 5500);

    // Persist to the cluster store (and backend when enabled) so the
    // activity appears in My Plan on the next page load. Fire-and-forget
    // — the overlay already reflects success in the current session.
    // Map the board's slot ("first") to the action's ClusterMeetingKind
    // ("first_meeting"). The two type spaces diverged — this is the bridge.
    const SLOT_TO_KIND: Record<ClusterMeetingSlot, ClusterMeetingKind> = {
      first: "first_meeting", second: "second_meeting", third: "third_meeting", sit: "sit",
    };
    scheduleClusterMeetingAction(
      pending.cluster.id,
      SLOT_TO_KIND[pending.slot],
      outcome.isoDate,
      outcome.participants,
      outcome.notes,
    ).catch(() => undefined);
  }

  /** Rolled-up list of meetings/trainings scheduled in this session.
   *  Sorted by date ascending so the next event sits at the top.
   *  Production swaps this for a real "newly scheduled" feed. */
  const scheduledThisSession = useMemo(() => {
    const items: Array<{
      clusterId:   string;
      clusterName: string;
      district:    string;
      slot:        ClusterMeetingSlot;
      slotLabel:   string;
      date:        string;
      proposedBy:  string;
    }> = [];
    for (const [key, value] of scheduleOverlay.entries()) {
      const [clusterId, slot] = key.split(":") as [string, ClusterMeetingSlot];
      const cluster = data.find((cg) => cg.id === clusterId);
      if (!cluster) continue;
      const slotLabel =
        slot === "first"  ? "1st cluster meeting" :
        slot === "second" ? "2nd cluster meeting" :
        slot === "third"  ? "3rd cluster meeting" :
                            "School Improvement Training";
      items.push({
        clusterId,
        clusterName: cluster.clusterName,
        district:    cluster.district,
        slot,
        slotLabel,
        date:        value.date,
        proposedBy:  value.proposedBy,
      });
    }
    items.sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
    return items;
  }, [scheduleOverlay]);

  /** Maps a cluster primaryAction to the matching meeting slot. */
  function slotForPrimaryAction(action: string): ClusterMeetingSlot | null {
    if (action === "schedule_first")  return "first";
    if (action === "schedule_second") return "second";
    if (action === "schedule_third")  return "third";
    if (action === "schedule_sit")    return "sit";
    return null;
  }

  const drawerContext: PlanningAssignContext | null = assign && {
    title: assign.label,
    schoolOrCluster: assign.cluster.clusterName,
    purpose: assign.purpose,
    allowPartnerFacilitator: assign.isTraining, // training + cluster meetings can be partner-facilitated
    allowPartnerOwnership: false,               // cluster activities are staff-owned
    assigningUserRole,
  };

  return (
    <section className="card p-3.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full flex items-start justify-between gap-3 text-left -m-1 p-1 rounded-md hover:bg-[var(--color-edify-soft)]/30 transition-colors"
      >
        <div className="min-w-0">
          <h2 className="text-[16px] font-extrabold tracking-tight inline-flex items-center gap-2">
            Cluster gaps
            <span className="inline-flex items-center px-1.5 py-[2px] rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] text-[10px] font-extrabold tabular">
              {data.length}
            </span>
          </h2>
          <p className="text-[12px] muted mt-0.5">
            Clusters with missing meetings or School Improvement Trainings. SIT is gated on schools having SSA — disabled buttons explain why.
          </p>
        </div>
        <span className="text-[var(--color-edify-muted)] shrink-0 mt-1">
          {open ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
        </span>
      </button>

      {open && scheduledThisSession.length > 0 && (
        <section className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50/40 p-3">
          <header className="flex items-center justify-between mb-2">
            <div className="inline-flex items-center gap-1.5">
              <CalendarCheck size={13} className="text-emerald-700" />
              <span className="text-[11.5px] uppercase tracking-wider font-extrabold text-emerald-700">
                Scheduled this session
              </span>
              <span className="inline-flex items-center px-1.5 py-[2px] rounded-md bg-white text-emerald-700 border border-emerald-200 text-[10px] font-extrabold tabular ml-1">
                {scheduledThisSession.length}
              </span>
            </div>
            <span className="text-caption muted inline-flex items-center gap-1">
              <Sparkles size={9} />
              Live overlay
            </span>
          </header>
          <ul className="divide-y divide-emerald-200/60 -mx-1">
            {scheduledThisSession.map((item) => (
              <li
                key={`${item.clusterId}:${item.slot}`}
                className="px-1 py-2 grid grid-cols-12 gap-2 items-center"
              >
                <div className="col-span-12 sm:col-span-7 min-w-0">
                  <div className="text-[12px] font-extrabold tracking-tight truncate">
                    {item.clusterName}
                    <span className="text-[var(--color-edify-muted)] font-semibold"> · {item.district}</span>
                  </div>
                  <div className="text-[11px] muted inline-flex items-center gap-1 mt-0.5">
                    <Calendar size={9} className="text-emerald-700" />
                    <span className="font-semibold text-[var(--color-edify-text)]">{item.slotLabel}</span>
                    <span className="opacity-50">·</span>
                    <span className="tabular">{item.date}</span>
                  </div>
                  <div className="text-caption muted mt-0.5">
                    Proposed by {item.proposedBy}
                  </div>
                </div>
                <div className="col-span-12 sm:col-span-5 flex items-center justify-end gap-1.5">
                  <button
                    type="button"
                    onClick={() => {
                      const cluster = data.find((cg) => cg.id === item.clusterId);
                      if (cluster) setReschedule({ cluster, slot: item.slot });
                    }}
                    className="h-7 px-2.5 rounded-md border border-emerald-200 bg-white text-emerald-700 text-caption font-extrabold hover:bg-emerald-50 transition-colors inline-flex items-center gap-1"
                  >
                    <RotateCw size={10} />
                    Reschedule
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {open && (
        <ul className="space-y-2.5 mt-3">
          {data.map((c) => (
            <ClusterRow
              key={c.id}
              cluster={c}
              onAssign={(payload) => {
                // Route initial-schedule actions to the unified
                // ScheduleActivityDrawer. Anything else (e.g.
                // add_schools, partner-facilitator) stays on the
                // generic owner picker.
                const slot = slotForPrimaryAction(payload.primaryAction);
                if (slot) {
                  setScheduleAssign({
                    cluster: c,
                    slot,
                    context: buildClusterScheduleContext(c, slot),
                  });
                  return;
                }
                setAssign(payload);
              }}
              onReschedule={(slot) => setReschedule({ cluster: c, slot })}
              onViewCluster={() => setClusterProfile({ cluster: c })}
              overlay={{
                first:  overlayFor(c.id, "first"),
                second: overlayFor(c.id, "second"),
                third:  overlayFor(c.id, "third"),
                sit:    overlayFor(c.id, "sit"),
              }}
            />
          ))}
        </ul>
      )}

      <PlanningAssignDrawer
        open={!!assign}
        context={drawerContext}
        onClose={() => setAssign(null)}
        onSubmit={handleAssignSubmit}
      />

      <RescheduleClusterMeetingDrawer
        open={!!reschedule}
        context={reschedule}
        onClose={() => setReschedule(null)}
        onSubmit={handleRescheduleSubmit}
      />

      {/* Always use the unified drawer — it handles both mock and live modes.
          After submit, handleScheduleSubmit updates the overlay + persists
          via scheduleClusterMeetingAction (which calls the backend when enabled). */}
      <ScheduleActivityDrawer
        open={!!scheduleAssign}
        context={scheduleAssign?.context ?? null}
        onClose={() => setScheduleAssign(null)}
        onSubmit={handleScheduleSubmit}
      />

      <ClusterActivityProfileDrawer
        open={!!clusterProfile}
        context={clusterProfile}
        onClose={() => setClusterProfile(null)}
        // Action CTAs inside the drawer route back through the
        // existing scheduling machinery (schedule_first, schedule_sit,
        // etc.). For school-upgrade reviews we surface a toast
        // placeholder — the dedicated review flow lands as part of
        // the core-promotion engine.
        onAction={(action, schoolId) => {
          if (!clusterProfile) return;
          const c = clusterProfile.cluster;
          setClusterProfile(null);

          // Cluster meeting / SIT scheduling — match the existing
          // primary-CTA routing in ClusterRow so the same drawer +
          // overlay write fire.
          const slot = slotForPrimaryAction(action ?? "");
          if (slot) {
            setScheduleAssign({
              cluster: c, slot,
              context: buildClusterScheduleContext(c, slot),
            });
            return;
          }
          if (action === "review_core" || action === "review_champion") {
            const verb = action === "review_core" ? "Core" : "Champion";
            setToast(`Opened ${verb} upgrade review for ${schoolId ?? "school"}. (Full review flow lands with the promotion engine.)`);
            setTimeout(() => setToast(null), 4500);
            return;
          }
          if (action === "schedule_ssa" || action === "schedule_training") {
            setToast(`Routing ${action.replace("_", " ")} to the school planning workflow.`);
            setTimeout(() => setToast(null), 4500);
          }
        }}
      />

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl shadow-lg bg-emerald-600 text-white text-[12px] font-semibold px-4 py-3 max-w-[400px]">
          {toast}
        </div>
      )}
    </section>
  );
}

function ClusterRow({
  cluster: c, onAssign, onReschedule, onViewCluster, overlay,
}: {
  cluster: ClusterGap;
  onAssign: (a: {
    cluster: ClusterGap;
    label: string;
    purpose: string;
    isTraining: boolean;
    primaryAction: string;     // routes initial-schedule actions to the calendar drawer
  }) => void;
  onReschedule: (slot: ClusterMeetingSlot) => void;
  onViewCluster: () => void;
  /** In-session schedule overlay — slot → { date, proposedBy }. */
  overlay: Record<ClusterMeetingSlot, { date: string; proposedBy: string } | undefined>;
}) {
  // Pass the overlay so the rec engine treats in-session scheduled
  // slots as effectively Scheduled — primary CTA advances past the
  // gap immediately, no page refresh needed.
  const rec = recommendForCluster(c, overlay);
  const sitBlocked = !!rec.sitDisabledReason;
  const [open, setOpen] = useState(false);

  // Per-slot effective status + date. The overlay represents work the
  // user just did this session; it forces the chip into the Scheduled
  // state with the chosen date even though the underlying mock still
  // says Missing.
  function chipStatus(slot: ClusterMeetingSlot, base: typeof c.firstMeeting) {
    return overlay[slot] ? "Scheduled" : base;
  }
  function chipDate(slot: ClusterMeetingSlot, base: string | undefined) {
    return overlay[slot]?.date ?? base;
  }

  return (
    <li className={cn(
      "rounded-xl border border-[var(--color-edify-divider)] bg-white overflow-hidden transition-colors",
      open && "bg-[var(--color-edify-soft)]/30",
    )}>
      {/* Collapsed header — identity + slot chips so the planner sees
          which meetings are missing / scheduled at a glance. Click
          anywhere on the header to expand. The meeting chips remain
          tappable for reschedule — clicks inside them stop propagation
          via their own onClick. */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen((o) => !o);
          }
        }}
        aria-expanded={open}
        aria-controls={`cluster-${c.id}-detail`}
        className="w-full p-3.5 flex items-start gap-3 text-left cursor-pointer hover:bg-[var(--color-edify-soft)]/40 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-edify-primary)]/40"
      >
        <span className="grid place-items-center h-9 w-9 rounded-lg bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
          <Users size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-body-lg font-extrabold tracking-tight truncate">{c.clusterName}</h3>
          <p className="text-[11px] muted leading-tight">
            {c.district} · {c.schoolsCount} schools · {c.schoolsWithSsa} with SSA · CCEO {c.assignedCceo}
          </p>
          <div
            className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3"
            onClick={(e) => e.stopPropagation()}
          >
            <MeetingChip
              label="SIT"
              status={chipStatus("sit", c.schoolImprovementTraining)}
              date={chipDate("sit", c.sitDate)}
              rescheduleCount={c.sitReschedules?.length ?? 0}
              onReschedule={() => onReschedule("sit")}
            />
            <MeetingChip
              label="1st meeting"
              status={chipStatus("first", c.firstMeeting)}
              date={chipDate("first", c.firstMeetingDate)}
              rescheduleCount={c.firstMeetingReschedules?.length ?? 0}
              onReschedule={() => onReschedule("first")}
            />
            <MeetingChip
              label="2nd meeting"
              status={chipStatus("second", c.secondMeeting)}
              date={chipDate("second", c.secondMeetingDate)}
              rescheduleCount={c.secondMeetingReschedules?.length ?? 0}
              onReschedule={() => onReschedule("second")}
            />
            <MeetingChip
              label="3rd meeting"
              status={chipStatus("third", c.thirdMeeting)}
              date={chipDate("third", c.thirdMeetingDate)}
              rescheduleCount={c.thirdMeetingReschedules?.length ?? 0}
              onReschedule={() => onReschedule("third")}
            />
          </div>
        </div>
        <ChevronRight
          size={14}
          className={cn(
            "text-[var(--color-edify-muted)] shrink-0 mt-1 transition-transform",
            open && "rotate-90",
          )}
        />
      </div>

      {open && (
        <div id={`cluster-${c.id}-detail`} className="px-3.5 pb-3.5 -mt-1 space-y-3">
          {c.partnerFacilitator && (
            <div className="text-[11px] muted">
              Partner facilitator: <span className="font-semibold text-[var(--color-edify-text)]">{c.partnerFacilitator}</span>
            </div>
          )}
          {/* Recommendation callout */}
          <div className="rounded-md border border-[var(--color-edify-divider)] px-2.5 py-2">
            <div className="text-[10px] uppercase tracking-wider font-bold muted">Recommended next action</div>
            <p className="text-[12px] font-extrabold text-[var(--color-edify-text)] mt-0.5">{rec.headline}</p>
            <p className="text-[11px] muted leading-snug mt-1">{rec.purpose}</p>
          </div>

          {/* Actions. Primary first, then a 2-col grid of secondary. */}
          <div className="space-y-2">
            {rec.primaryAction === "view" ? (
              <button
                type="button"
                onClick={onViewCluster}
                className="w-full inline-flex items-center justify-center gap-1 h-9 px-3 rounded-md border border-emerald-300 bg-emerald-50 text-emerald-700 text-[12px] font-extrabold hover:bg-emerald-100 transition-colors whitespace-nowrap"
              >
                <CalendarCheck size={12} />
                {rec.primaryLabel}
              </button>
            ) : rec.primaryAction === "schedule_sit" ? (
              <>
                <button
                  type="button"
                  onClick={() => !sitBlocked && onAssign({
                    cluster: c,
                    label: rec.primaryLabel,
                    purpose: rec.purpose,
                    isTraining: true,
                    primaryAction: rec.primaryAction,
                  })}
                  disabled={sitBlocked}
                  title={sitBlocked ? rec.sitDisabledReason : undefined}
                  className={cn(
                    "w-full inline-flex items-center justify-center gap-1 h-9 px-3 rounded-md text-[12px] font-extrabold transition-colors whitespace-nowrap",
                    sitBlocked
                      ? "bg-slate-100 text-slate-400 cursor-not-allowed"
                      : "bg-[var(--color-edify-primary)] text-white hover:bg-[var(--color-edify-dark)]",
                  )}
                >
                  {rec.primaryLabel}
                  {!sitBlocked && <ArrowRight size={12} />}
                </button>
                {sitBlocked && (
                  <div className="text-[11px] muted leading-snug flex items-start gap-1.5 px-1">
                    <Lock size={10} className="mt-0.5 text-rose-500 shrink-0" />
                    <span>{rec.sitDisabledReason}</span>
                  </div>
                )}
              </>
            ) : (
              <button
                type="button"
                onClick={() => onAssign({
                  cluster: c,
                  label: rec.primaryLabel,
                  purpose: rec.purpose,
                  isTraining: false,
                  primaryAction: rec.primaryAction,
                })}
                className="w-full inline-flex items-center justify-center gap-1 h-9 px-3 rounded-md bg-[var(--color-edify-primary)] text-white text-[12px] font-extrabold hover:bg-[var(--color-edify-dark)]"
              >
                {rec.primaryLabel}
                <ArrowRight size={12} />
              </button>
            )}

            <div className="grid grid-cols-2 gap-1.5">
              <button
                type="button"
                onClick={() => onAssign({
                  cluster: c,
                  label: "Assign partner as facilitator",
                  purpose: rec.purpose,
                  isTraining: true,
                  primaryAction: "assign_facilitator",
                })}
                className="inline-flex items-center justify-center gap-1 h-9 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[11px] font-semibold hover:bg-[var(--color-edify-soft)]/60 whitespace-nowrap"
              >
                <Handshake size={11} /> Partner facilitator
              </button>
              <button
                type="button"
                onClick={onViewCluster}
                className="inline-flex items-center justify-center gap-1 h-9 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[11px] font-semibold hover:bg-[var(--color-edify-soft)]/60 whitespace-nowrap"
              >
                <Calendar size={11} /> View cluster
              </button>
            </div>
          </div>
        </div>
      )}
    </li>
  );
}

function MeetingChip({
  label, status, date, rescheduleCount = 0, onReschedule,
}: {
  label: string;
  status: ClusterMeetingStatus;
  date?: string;
  rescheduleCount?: number;
  onReschedule?: () => void;
}) {
  const tone        = MEETING_TONE[status];
  const isClickable = (status === "Scheduled" || status === "Rescheduled") && !!onReschedule;

  const body = (
    <div className={cn("rounded-md px-2 py-1.5 flex items-center gap-1.5 transition-colors", tone.bg, isClickable && "hover:brightness-95")}>
      <tone.Icon size={11} className={tone.text} />
      <div className="min-w-0 flex-1">
        <div className={cn("text-[10px] uppercase tracking-wide font-bold inline-flex items-center gap-1", tone.text)}>
          {label}
          {rescheduleCount > 0 && (
            <span
              title={`Moved ${rescheduleCount} time${rescheduleCount === 1 ? "" : "s"}`}
              className="inline-flex items-center justify-center min-w-[14px] h-[14px] px-1 rounded-full bg-white/70 text-[9px] font-extrabold tabular text-amber-700 ring-1 ring-amber-200"
            >
              ×{rescheduleCount}
            </span>
          )}
        </div>
        <div className="text-[12px] font-extrabold text-[var(--color-edify-text)] leading-tight truncate">
          {date ? date : status}
        </div>
        {date && status !== "Completed" && (
          <div className="text-[10px] muted leading-tight truncate">{status}{isClickable ? " · Tap to reschedule" : ""}</div>
        )}
      </div>
    </div>
  );

  if (!isClickable) return body;
  return (
    <button
      type="button"
      onClick={onReschedule}
      aria-label={`Reschedule ${label} (currently ${status}${date ? ` for ${date}` : ""})`}
      className="text-left w-full"
    >
      {body}
    </button>
  );
}
