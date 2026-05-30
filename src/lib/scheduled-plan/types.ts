// Scheduled-plan lifecycle types.
//
// Every scheduled activity (training / visit / coaching / SSA /
// cluster meeting / partner activity) flows through this status
// machine. The status drives which action buttons render on the
// scheduled-plan card — the spec's section 8 matrix lives in
// `status.ts` as a pure function.

import type { ReschedulableActivity } from "@/lib/reschedule/types";

export type ScheduledPlanStatus =
  | "scheduled"           // future date, ready to start
  | "due_today"           // scheduled date is today
  | "due_this_week"       // scheduled within the current week
  | "rescheduled"         // user moved the date, still scheduled
  | "in_progress"         // user clicked Start Activity
  | "evidence_required"   // completed, evidence not yet uploaded
  | "completion_submitted"// partner submitted completion claim
  | "awaiting_review"     // CCEO hasn't decided
  | "completed"           // confirmed + closed
  | "cancelled"
  | "missed";             // scheduled date passed without start

export type ScheduledPlan = {
  id:            string;
  activityType:  ReschedulableActivity;
  /** Human label — "Hope Primary · Follow-Up visit". */
  label:         string;
  /** School / cluster name for context. */
  schoolName?:   string;
  clusterName?:  string;
  district?:     string;
  /** Pre-formatted date or week label — "June Week 2 · Thursday 13 June". */
  scheduledFor:  string;
  /** ISO when known; the formatted `scheduledFor` is what the card
   *  shows for human readability. */
  scheduledIso?: string;
  /** Why the activity exists — usually pulled from the SSA: "Teaching
   *  & Learning support based on SSA score 4/10". */
  purpose?:      string;
  /** Display label for the owner — "CCEO Sarah" / "Partner field officer
   *  Abel". */
  ownerLabel?:   string;
  /** Plain-text bullets of required evidence — surfaced in the Start
   *  Activity confirmation drawer so the user knows what to bring. */
  evidenceRequired?: string[];
  /** Cost rollup label when relevant. */
  costLabel?:    string;
  status:        ScheduledPlanStatus;
  /** Who would be rescheduling this — drives the routing rules in the
   *  Reschedule drawer. */
  actor:         "staff" | "partner";
};
