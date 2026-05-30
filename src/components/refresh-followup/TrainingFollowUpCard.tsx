"use client";

import { useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  AlertOctagon,
  ArrowRight,
  CheckCircle2,
  Clock,
  UserCheck,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  followUpAlertsFor,
  followUpSummaryFor,
  type FollowUpAlert,
  type FollowUpStatus,
} from "@/lib/refresh-and-followup-mock";
import type { CurrentUser } from "@/lib/schools-mock";
import { useDemoStore } from "@/components/demo/DemoStore";
import { saveAssignment } from "@/lib/assignment-store";
import {
  AssignFollowUpDialog,
  type TeamCceo,
  type AssignmentSubmit,
} from "@/components/refresh-followup/AssignFollowUpDialog";
import { cn } from "@/lib/utils";

// The PL's supervised team. Real backend swaps this for a
// supervisedCceosFor(plStaffId) query; for the demo we hand-craft the
// roster so the PL has a meaningful picker AND the demo viewer can
// sign in as Paul to verify the loop closes end-to-end.
const PL_TEAM: TeamCceo[] = [
  { staffId: "STF-PC-001", name: "Paul Chinyama",   initials: "PC", region: "Kigun District",  status: "On Track", isDemoLoggable: true },
  { staffId: "STF-GN-007", name: "Grace Nansubuga", initials: "GN", region: "Central",         status: "On Track" },
  { staffId: "STF-JO-012", name: "James Okello",    initials: "JO", region: "East",            status: "On Track" },
  { staffId: "STF-PO-008", name: "Peter Ochieng",   initials: "PO", region: "North",           status: "At Risk" },
  { staffId: "STF-SN-009", name: "Sarah Namutebi",  initials: "SN", region: "West",            status: "On Track" },
  { staffId: "STF-DT-015", name: "David Tumusiime", initials: "DT", region: "North",           status: "Behind" },
];

// Urgency → icon + color. Replaces the long status pill so the row's
// left edge reads at a glance:
//   • Critical (60+ days) → red octagon — strongest weight
//   • Overdue   (45-59 days) → amber triangle — warning
//   • Due       (30-44 days) → orange clock — time-based, lowest urgency
type Urgency = FollowUpAlert["urgency"];

const urgencyIcon: Record<Urgency, LucideIcon> = {
  Critical: AlertOctagon,
  High:     AlertTriangle,
  Medium:   Clock,
};

const urgencyIconColor: Record<Urgency, string> = {
  Critical: "text-rose-600",
  High:     "text-amber-600",
  Medium:   "text-orange-500",
};

const urgencyTitle: Record<Urgency, string> = {
  Critical: "Critical Follow-Up Gap — 60+ days since training, no follow-up.",
  High:     "Follow-Up Overdue — 45-59 days since training.",
  Medium:   "Follow-Up Due — 30-44 days since training.",
};

// The 3 tiles are filter chips. Each one maps to a single
// `followUpStatus` value in the underlying alert feed. Clicking a
// tile narrows the list below to that bucket.
type TileKey = "due" | "overdue" | "critical";
const TILE_TO_STATUS: Record<TileKey, FollowUpStatus> = {
  due:      "Follow-Up Due",
  overdue:  "Follow-Up Overdue",
  critical: "Critical Follow-Up Gap",
};

export function TrainingFollowUpCard({ user }: { user: CurrentUser }) {
  const alerts = followUpAlertsFor(user);
  const summary = followUpSummaryFor(user);
  const { pushToast } = useDemoStore();

  // Default to whichever bucket has the most items so the card opens
  // on the work the CPL is most likely to act on first. Critical wins
  // ties — it's the most-urgent bucket.
  const initialTile: TileKey =
    summary.critical > 0 ? "critical" :
    summary.overdue  > 0 ? "overdue"  :
    "due";
  const [activeTile, setActiveTile] = useState<TileKey>(initialTile);
  const activeStatus = TILE_TO_STATUS[activeTile];
  const filteredAlerts = alerts.filter((a) => a.followUpStatus === activeStatus);

  // Track which alerts have been assigned this session so the row can
  // reflect the confirmed state inline. Each entry remembers WHO it
  // was sent to so the row label can read "Sent to Grace" / "Sent to
  // Paul" instead of a generic chip.
  const [assignedMap, setAssignedMap] = useState<Record<string, TeamCceo>>({});

  // Dialog state — opens with the alert it should assign for.
  const [dialogAlert, setDialogAlert] = useState<FollowUpAlert | null>(null);

  function handleDialogSubmit(submission: AssignmentSubmit) {
    if (!dialogAlert) return;
    const a = dialogAlert;
    saveAssignment({
      id: `assn-${a.alertId}`,
      alertId: a.alertId,
      schoolId: a.schoolId,
      schoolName: a.schoolName,
      district: a.district,
      urgency: a.urgency,
      daysSinceTraining: a.daysSinceTraining,
      recommendedAction: a.recommendedAction,
      assignedToCceoId: submission.cceo.staffId,
      assignedToCceoName: submission.cceo.name,
      assignedByName: user.name,
      assignedAt: new Date().toISOString(),
      dueDate: submission.dueDate,
      note: submission.note,
      source: "training-follow-up",
      status: "open",
    });
    setAssignedMap((prev) => ({ ...prev, [a.alertId]: submission.cceo }));
    setDialogAlert(null);
    const isPaul = submission.cceo.isDemoLoggable;
    pushToast({
      tone: "success",
      title: "Follow-Up assigned",
      body: isPaul
        ? `${a.schoolName} added to ${submission.cceo.name}'s todo list (due ${submission.dueDate}). Sign in as Paul Chinyama to see it on My Targets.`
        : `${a.schoolName} added to ${submission.cceo.name}'s todo list (due ${submission.dueDate}).`,
    });
  }

  function handleSchedule(a: FollowUpAlert) {
    pushToast({
      tone: "success",
      title: "Follow-Up scheduled",
      body: `${a.schoolName} routed for next-week scheduling. Assign to a CCEO to push it to their todo list.`,
    });
  }

  return (
    <SectionCard
      icon={<AlertTriangle size={13} className="text-[var(--color-edify-orange)]" />}
      title="Training Follow-Up Overdue"
      subtitle="Schools trained 30+ days ago with no follow-up activity. Closes only on scheduled or completed follow-up."
      actions={
        <Link
          href="/alerts"
          className="inline-flex items-center gap-1 text-[var(--text-body)] font-semibold text-[var(--color-edify-primary)]"
        >
          View All
          <ArrowRight size={11} />
        </Link>
      }
    >
      {/* Filter chips — each tile narrows the list below to the
          matching follow-up status. The active tile gets an outline
          ring; the others stay flat. Implemented as `aria-pressed`
          toggle buttons (not full role="tab" since we don't carry
          arrow-key navigation here). */}
      <div
        role="group"
        aria-label="Filter follow-up alerts by urgency"
        className="grid grid-cols-3 gap-2 mb-3"
      >
        <TileTab
          tileKey="due"
          label="Due"
          fullLabel="Follow-Up Due"
          value={summary.due}
          tone="bg-amber-50 text-amber-700"
          activeRing="ring-amber-400"
          isActive={activeTile === "due"}
          onClick={() => setActiveTile("due")}
        />
        <TileTab
          tileKey="overdue"
          label="Overdue"
          fullLabel="Follow-Up Overdue"
          value={summary.overdue}
          tone="bg-amber-100 text-amber-700"
          activeRing="ring-amber-500"
          isActive={activeTile === "overdue"}
          onClick={() => setActiveTile("overdue")}
        />
        <TileTab
          tileKey="critical"
          label="Critical 60+d"
          fullLabel="Critical Follow-Up Gap (60+ days)"
          value={summary.critical}
          tone="bg-rose-50 text-rose-700"
          activeRing="ring-rose-500"
          isActive={activeTile === "critical"}
          onClick={() => setActiveTile("critical")}
        />
      </div>

      {alerts.length === 0 ? (
        <div className="text-[var(--text-body)] muted text-center py-4 flex items-center justify-center gap-1.5">
          <CheckCircle2 size={13} className="text-[var(--color-success)]" />
          No follow-up gaps for your assigned schools.
        </div>
      ) : filteredAlerts.length === 0 ? (
        <div
          id="follow-up-alert-list"
          aria-live="polite"
          className="text-[var(--text-body)] muted text-center py-4 flex items-center justify-center gap-1.5"
        >
          <CheckCircle2 size={13} className="text-[var(--color-success)]" />
          {activeTile === "due"      && "No schools currently in the Due bucket."}
          {activeTile === "overdue"  && "No schools currently Overdue."}
          {activeTile === "critical" && "No Critical (60+ days) follow-up gaps. Good."}
        </div>
      ) : (
        <div
          id="follow-up-alert-list"
          aria-live="polite"
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2"
        >
          {filteredAlerts.slice(0, 5).map((a) => {
            const UrgencyIcon = urgencyIcon[a.urgency];
            const assignedTo = assignedMap[a.alertId];
            const isAssigned = Boolean(assignedTo);
            const assignedFirstName = assignedTo?.name.split(" ")[0] ?? "";
            return (
              // Mobile-first row: icon · school name · days-ago chip on
              // row 1, then meta + recommended action below, then action
              // buttons. The CCEO captures the Salesforce ID after the
              // visit, so the PL's row no longer carries that action.
              //
              // Critical rows wear a rose left-edge accent so they pop
              // when the PL scrolls the bucket.
              <div
                key={a.alertId}
                className={cn(
                  "rounded-lg border p-2 space-y-1 transition-colors border-l-[3px]",
                  isAssigned
                    ? "border-emerald-200 bg-emerald-50/40 border-l-emerald-400"
                    : a.urgency === "Critical"
                      ? "border-[var(--color-edify-border)] border-l-rose-500 bg-rose-50/30"
                      : a.urgency === "High"
                        ? "border-[var(--color-edify-border)] border-l-amber-500"
                        : "border-[var(--color-edify-border)] border-l-orange-400",
                )}
              >
                <div className="flex items-center gap-1.5 min-w-0">
                  {/* Color-coded urgency icon — replaces the long status
                      pill. Title attribute carries the full label for
                      screen readers + hover. */}
                  <UrgencyIcon
                    size={13}
                    className={cn("shrink-0", urgencyIconColor[a.urgency])}
                    aria-label={urgencyTitle[a.urgency]}
                  >
                    <title>{urgencyTitle[a.urgency]}</title>
                  </UrgencyIcon>
                  <div className="text-[12px] font-semibold leading-tight truncate flex-1 min-w-0">
                    {a.schoolName}
                  </div>
                  {isAssigned ? (
                    <span className="inline-flex items-center gap-1 px-1 py-[1px] rounded text-[9.5px] font-bold bg-emerald-100 text-emerald-700 whitespace-nowrap shrink-0">
                      <CheckCircle2 size={9} />
                      Assigned
                    </span>
                  ) : (
                    <span className="text-[9.5px] muted whitespace-nowrap tabular shrink-0">
                      {a.daysSinceTraining}d
                    </span>
                  )}
                </div>
                <div className="text-[10px] muted leading-snug">
                  {a.district} · trained {a.latestTrainingDate}
                </div>
                {/* Alarming red treatment for critical follow-ups. The
                    medium / high tiers stay neutral so the rose only
                    fires for the 60+-day backlog that genuinely needs
                    same-week action. Weight stays normal — color carries
                    the urgency, not bolding. */}
                {a.urgency === "Critical" ? (
                  <div className="text-caption leading-snug text-rose-700 inline-flex items-start gap-1">
                    <AlertOctagon size={10} className="shrink-0 mt-[1px] text-rose-600" />
                    <span>{a.recommendedAction}</span>
                  </div>
                ) : (
                  <div className="text-caption leading-snug">
                    {a.recommendedAction}
                  </div>
                )}
                <div className="flex items-center gap-1.5 pt-0.5 flex-wrap">
                  <button
                    type="button"
                    onClick={() => handleSchedule(a)}
                    disabled={isAssigned}
                    className="btn btn-sm btn-primary"
                  >
                    Schedule
                  </button>
                  <button
                    type="button"
                    onClick={() => setDialogAlert(a)}
                    disabled={isAssigned}
                    title={
                      isAssigned
                        ? `Already sent to ${assignedTo?.name}'s todo list`
                        : "Pick a CCEO and a deadline"
                    }
                    className={cn(
                      "btn btn-sm inline-flex items-center gap-1",
                      isAssigned && "opacity-60",
                    )}
                  >
                    <UserCheck size={10} />
                    {isAssigned ? `Sent to ${assignedFirstName}` : "Assign"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
      <div className="mt-2 pt-2 border-t border-[#eef2f4] text-[var(--text-caption)] muted">
        Cannot dismiss without action: schedule, complete with Salesforce ID, or supervisor dismissal with documented reason.
      </div>

      {/* Assignment dialog — open with the row's alert. The dialog
          captures the CCEO + deadline + note; on submit the parent
          writes to the assignment store and the receiving CCEO sees
          the work on their My Targets plan. */}
      <AssignFollowUpDialog
        open={dialogAlert !== null}
        onClose={() => setDialogAlert(null)}
        onSubmit={handleDialogSubmit}
        team={PL_TEAM}
        schoolName={dialogAlert?.schoolName ?? ""}
        schoolDistrict={dialogAlert?.district ?? ""}
        recommendedAction={dialogAlert?.recommendedAction ?? ""}
      />
    </SectionCard>
  );
}

function TileTab({
  tileKey,
  label,
  fullLabel,
  value,
  tone,
  activeRing,
  isActive,
  onClick,
}: {
  tileKey: TileKey;
  label: string;
  fullLabel: string;
  value: number;
  tone: string;
  activeRing: string;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      id={`tile-${tileKey}`}
       
      aria-pressed={isActive ? "true" : "false"}
      aria-controls="follow-up-alert-list"
      title={fullLabel}
      onClick={onClick}
      className={cn(
        "rounded-lg px-2.5 py-2 flex flex-col items-start overflow-hidden text-left transition-shadow",
        tone,
        // Visual selected state: 2px ring + slight lift. Non-active
        // tiles keep a 1px transparent ring so the layout doesn't
        // shift when selection changes.
        isActive
          ? cn("ring-2 ring-offset-1 ring-offset-white shadow-sm", activeRing)
          : "ring-2 ring-transparent hover:ring-1 hover:ring-current/20",
      )}
    >
      <span className="text-[var(--text-tiny)] font-semibold uppercase tracking-wide truncate w-full">
        {label}
      </span>
      <span className="text-[var(--text-h-sm)] font-extrabold tabular leading-none mt-1 truncate w-full">
        {value}
      </span>
    </button>
  );
}
