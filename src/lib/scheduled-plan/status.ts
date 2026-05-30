// Status → button-visibility matrix (spec §8).
//
// Pure functions. The card reads these to decide which actions to
// render. Keeps the matrix in one testable place so future status
// changes only need to be reflected here.

import type { ScheduledPlanStatus } from "./types";

export type PlanActionKey =
  | "start"
  | "reschedule"
  | "complete"
  | "upload_evidence"
  | "view_evidence"
  | "view_report"
  | "mark_missed"
  | "awaiting_review_chip"; // not a button — a chip the card renders

export function actionsForStatus(status: ScheduledPlanStatus): PlanActionKey[] {
  switch (status) {
    case "scheduled":
    case "due_this_week":
      return ["reschedule", "start"];
    case "due_today":
      return ["reschedule", "start"];
    case "rescheduled":
      return ["reschedule", "start"];
    case "in_progress":
      return ["complete"];
    case "evidence_required":
      return ["upload_evidence"];
    case "completion_submitted":
    case "awaiting_review":
      return ["awaiting_review_chip"];
    case "completed":
      return ["view_report"];
    case "cancelled":
      return [];
    case "missed":
      return ["reschedule", "mark_missed"];
  }
}

// Human label + tone for the status badge on the card.
export const STATUS_META: Record<ScheduledPlanStatus, { label: string; tone: "slate" | "blue" | "emerald" | "amber" | "rose" | "violet" }> = {
  scheduled:            { label: "Scheduled",              tone: "blue"    },
  due_today:            { label: "Due today",              tone: "amber"   },
  due_this_week:        { label: "Due this week",          tone: "blue"    },
  rescheduled:          { label: "Rescheduled",            tone: "violet"  },
  in_progress:          { label: "In progress",            tone: "emerald" },
  evidence_required:    { label: "Evidence required",      tone: "amber"   },
  completion_submitted: { label: "Submitted",              tone: "blue"    },
  awaiting_review:      { label: "Awaiting review",        tone: "blue"    },
  completed:            { label: "Completed",              tone: "emerald" },
  cancelled:            { label: "Cancelled",              tone: "slate"   },
  missed:               { label: "Missed",                 tone: "rose"    },
};

/** Does the Start button mean "Start now" or "Scheduled for …"? Spec §2:
 *  due_today / due_this_week → enabled; future scheduled → disabled
 *  with a label hint (unless policy allows early start). */
export function startState(status: ScheduledPlanStatus): "enabled" | "future" | "hidden" {
  if (status === "due_today" || status === "due_this_week") return "enabled";
  if (status === "scheduled" || status === "rescheduled")  return "enabled"; // demo: permit start; future variant could flip to "future"
  return "hidden";
}
