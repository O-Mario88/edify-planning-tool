"use client";

// "Assigned by your Program Lead" — section that surfaces directives
// the PL pushed to this CCEO via the Training Follow-Up Overdue card
// (or future PL-side assignment surfaces). Renders at the top of the
// CCEO's plan so they see the inbound work before their own weekly
// todos.
//
// Reads from the localStorage-backed assignment store. When the PL
// clicks "Assign to {CCEO}" on the CPL dashboard, the entry persists
// and shows up here on the next render — no rebuild, no server.

import { useEffect, useState } from "react";
import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Clock,
  Inbox,
  Send,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import {
  deadlineState,
  loadAssignmentsForCceo,
  markAssignmentCompleted,
  type FollowUpAssignment,
} from "@/lib/assignment-store";
import { useDemoStore } from "@/components/demo/DemoStore";
import { cn } from "@/lib/utils";

const URGENCY_ICON: Record<FollowUpAssignment["urgency"], LucideIcon> = {
  Critical: AlertOctagon,
  High:     AlertTriangle,
  Medium:   Clock,
};
const URGENCY_COLOR: Record<FollowUpAssignment["urgency"], string> = {
  Critical: "text-rose-600",
  High:     "text-amber-600",
  Medium:   "text-orange-500",
};
const URGENCY_LABEL: Record<FollowUpAssignment["urgency"], string> = {
  Critical: "Critical · 60+ days since training",
  High:     "Overdue · 45-59 days since training",
  Medium:   "Due · 30-44 days since training",
};

function relativeTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms) || ms < 0) return "just now";
  const m = Math.floor(ms / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

export function AssignedByPLCard({ userStaffId }: { userStaffId?: string }) {
  const [assignments, setAssignments] = useState<FollowUpAssignment[]>([]);
  const { pushToast } = useDemoStore();

  // localStorage reads must happen client-side. Re-read on mount so the
  // CCEO sees the PL's assignments without a hard reload. Migrate to
  // useSyncExternalStore during the React-19 sweep.
  useEffect(() => {
    if (!userStaffId) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAssignments(loadAssignmentsForCceo(userStaffId));
  }, [userStaffId]);

  // Hide the card entirely when there's nothing to show — no empty
  // chrome eating space at the top of the page.
  const openAssignments = assignments.filter((a) => a.status === "open");
  if (openAssignments.length === 0) return null;

  function handleAcknowledge(a: FollowUpAssignment) {
    markAssignmentCompleted(a.id);
    setAssignments(loadAssignmentsForCceo(userStaffId ?? ""));
    pushToast({
      tone: "success",
      title: "Marked in progress",
      body: `${a.schoolName} added to this week's plan. Capture the Salesforce ID after the visit to mark it verified.`,
    });
  }

  return (
    <section
      aria-labelledby="assigned-by-pl-heading"
      className="rounded-2xl border border-[var(--color-edify-primary)]/35 bg-gradient-to-br from-[var(--color-edify-soft)] to-white shadow-[0_1px_2px_rgba(15,23,32,.04),0_4px_12px_rgba(15,23,32,.04)] overflow-hidden"
    >
      <header className="flex items-baseline justify-between gap-3 px-4 pt-4 pb-3 border-b border-[var(--color-edify-border)]/60 flex-wrap">
        <div className="min-w-0">
          <div className="text-[var(--text-caption)] font-bold uppercase tracking-[0.16em] muted inline-flex items-center gap-1.5">
            <Inbox size={11} />
            From your Program Lead
          </div>
          <h2
            id="assigned-by-pl-heading"
            className="text-[var(--text-h-xs)] font-extrabold tracking-tight mt-0.5"
          >
            {openAssignments.length} follow-up{openAssignments.length === 1 ? "" : "s"} assigned to you
          </h2>
        </div>
        <span className="inline-flex items-center gap-1 text-[var(--text-tiny)] muted">
          <Sparkles size={10} className="text-[var(--color-edify-primary)]" />
          Goes straight into this week&apos;s plan when you acknowledge
        </span>
      </header>

      <ul className="divide-y divide-[var(--color-edify-border)]/60">
        {openAssignments.slice(0, 5).map((a) => {
          const Icon = URGENCY_ICON[a.urgency];
          const deadline = deadlineState(a.dueDate);
          const deadlineCls =
            deadline.tone === "rose"
              ? "bg-rose-100 text-rose-700"
              : deadline.tone === "amber"
                ? "bg-amber-100 text-amber-700"
                : "bg-[var(--color-edify-soft)] text-[var(--color-edify-text)]";
          return (
            <li
              key={a.id}
              className="px-4 py-3 grid grid-cols-[auto_1fr_auto] items-center gap-3 hover:bg-white/60"
            >
              <Icon
                size={16}
                className={cn("shrink-0", URGENCY_COLOR[a.urgency])}
                aria-label={URGENCY_LABEL[a.urgency]}
              />
              <div className="min-w-0">
                <div className="flex items-baseline gap-2 min-w-0 flex-wrap">
                  <div className="text-[var(--text-body-lg)] font-semibold leading-tight truncate flex-1 min-w-0">
                    {a.schoolName}
                  </div>
                  {deadline.tone !== "none" && (
                    <span
                      title={a.dueDate ? `Deadline ${a.dueDate}` : ""}
                      className={cn(
                        "inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[var(--text-tiny)] font-bold whitespace-nowrap shrink-0",
                        deadlineCls,
                      )}
                    >
                      <Clock size={9} />
                      {deadline.label}
                    </span>
                  )}
                </div>
                <div className="text-[var(--text-caption)] muted leading-tight truncate mt-0.5">
                  {a.district} · {a.daysSinceTraining}d since training
                </div>
                {/* Recommended action on its own line so we can stamp it
                    rose+bold when the assignment is critical. */}
                {a.urgency === "Critical" ? (
                  <div className="text-[var(--text-caption)] leading-tight font-bold text-rose-700 mt-0.5 inline-flex items-start gap-1.5">
                    <AlertOctagon size={11} className="shrink-0 mt-[1px] text-rose-600" />
                    <span>{a.recommendedAction}</span>
                  </div>
                ) : (
                  <div className="text-[var(--text-caption)] leading-tight mt-0.5">
                    {a.recommendedAction}
                  </div>
                )}
                {a.note && (
                  <div className="text-[var(--text-caption)] leading-tight mt-0.5 px-1.5 py-[2px] rounded inline-block bg-[var(--color-edify-soft)]/80 border border-[var(--color-edify-border)]">
                    <span className="font-semibold">Note:</span> {a.note}
                  </div>
                )}
                <div className="text-[var(--text-tiny)] muted leading-tight mt-1 inline-flex items-center gap-1">
                  <Send size={10} />
                  Assigned by {a.assignedByName} · {relativeTime(a.assignedAt)}
                </div>
              </div>
              <button
                type="button"
                onClick={() => handleAcknowledge(a)}
                className="btn btn-sm btn-primary inline-flex items-center gap-1.5 shrink-0"
              >
                <CheckCircle2 size={11} />
                Add to plan
              </button>
            </li>
          );
        })}
      </ul>

      <footer className="px-4 py-2.5 bg-[var(--color-edify-soft)]/60 border-t border-[var(--color-edify-border)]/60 flex items-center justify-between gap-3 flex-wrap">
        <span className="text-[var(--text-caption)] muted leading-snug">
          Each assignment becomes a school visit on your plan. Capture the Salesforce ID after the visit to confirm completion.
        </span>
        <a
          href="#this-week"
          className="text-[var(--text-caption)] font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-1 whitespace-nowrap"
        >
          Open this week
          <ChevronRight size={11} />
        </a>
      </footer>
    </section>
  );
}
