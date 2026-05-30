// Reschedule workflow — shared types.
//
// Every scheduled activity (training / visit / coaching / SSA / partner
// activity) can be rescheduled, but only with at least one reason from
// the controlled list. The reason drives routing — Staff reschedules
// notify PL/IA/Accountant/HR; Partner reschedules notify
// CCEO/PL/CD/IA/Accountant/RVP. This file is the source of truth for
// reason categories + the submission shape.

import type { EdifyRole } from "@/lib/auth-public";

export type RescheduleReasonCategory =
  | "finance"
  | "transport"
  | "school_availability"
  | "calendar"
  | "staff_availability"
  | "program_readiness"
  | "safety"
  | "other";

export type RescheduleReason = {
  /** Stable key — used by analytics + routing. */
  key:       string;
  /** Human label rendered in the drawer checkboxes. */
  label:     string;
  category:  RescheduleReasonCategory;
  /** When true, the optional notes box becomes required (the spec's
   *  "Other" case). */
  requiresNotes?: boolean;
};

/** Who initiated the reschedule. Drives the notification recipients. */
export type RescheduleActor = "staff" | "partner";

/** Activity types the reschedule workflow applies to (spec section 1). */
export type ReschedulableActivity =
  | "training"
  | "cluster_meeting"
  | "school_visit"
  | "follow_up_visit"
  | "coaching_visit"
  | "in_school_training"
  | "classroom_observation"
  | "ssa_visit"
  | "core_school_visit"
  | "core_training"
  | "partner_visit"
  | "partner_in_school_activity"
  | "partner_facilitation"
  | "school_improvement_training";

export type RescheduleSubmission = {
  id:             string;
  /** Foreign key to the activity record being rescheduled. */
  activityId:     string;
  activityType:   ReschedulableActivity;
  /** Pre-resolved display label — "Hope Primary · Follow-Up visit". */
  activityLabel:  string;
  /** Optional context (schoolId / clusterId / partnerId) that informs
   *  the recipient set when paired with the directory. */
  schoolId?:      string;
  clusterId?:     string;
  partnerId?:     string;
  district?:      string;
  region?:        string;

  actor:          RescheduleActor;
  actorUserId:    string;
  actorName:      string;
  actorRole:      EdifyRole;

  /** ISO timestamp of the original scheduled date. */
  originalDate:   string;
  /** ISO timestamp of the new scheduled date. */
  newDate:        string;

  reasonKeys:     string[];
  notes?:         string;

  createdAt:      string;
};
