// Debrief intelligence — shared types.
//
// Three submitter roles produce three debrief variants. Reviewer roles
// consume them via category-driven routing. The existing CCEO
// DailyFieldDebrief in field-intelligence-mock.ts continues to power
// CCEO history; this layer adds the spec's missing dimensions
// (category, priority, routing) and the PL + Partner variants.

import type { EdifyRole } from "@/lib/auth-public";

export type DebriefSubmitterRole = "CCEO" | "CountryProgramLead" | "Partner";

export type DebriefReviewerRole =
  | "HumanResource"
  | "CountryDirector"
  | "CountryProgramLead"
  | "CCEO"
  | "ProgramAccountant"
  | "ImpactAssessment";

// Field reality mood — the spec's "How was today's field reality?" chips.
// Keeps it short and supportive (Healthy principle) — no "good/bad",
// just descriptive states a person can pick honestly.
export type DebriefMood =
  | "Calm"
  | "Busy"
  | "Difficult"
  | "Blocked"
  | "Successful"
  | "Urgent";

export type DebriefPriority = "Normal" | "Important" | "Urgent" | "Critical";

// Lifecycle. Mirrors the spec's status list.
export type DebriefStatus =
  | "Submitted"
  | "Seen"
  | "Acknowledged"
  | "Action Created"
  | "In Progress"
  | "Resolved"
  | "Escalated"
  | "Closed";

// A category key is a stable string. The labels + per-role pickers live
// in `categories.ts`; the routing rules in `routing.ts`. Keys are shared
// across roles where the underlying concept is the same (e.g.
// "urgent-escalation") so routing logic can match generically.
export type DebriefCategory =
  // CCEO categories
  | "school-support-issue"
  | "workload-burnout"
  | "travel-distance"
  | "funds-finance-delay"
  | "partner-delay"
  | "school-leadership-issue"
  | "teacher-practice-issue"
  | "safeguarding-safety"
  | "data-evidence-issue"
  | "success-story"
  | "program-improvement-idea"
  | "urgent-escalation"
  // PL-specific
  | "staff-workload"
  | "partner-performance"
  | "planning-gap"
  | "budget-funds-blocker"
  | "school-risk"
  | "evidence-data-quality"
  | "training-quality"
  | "cluster-issue"
  | "ssa-issue"
  | "operational-risk"
  | "program-improvement"
  | "urgent-decision-needed"
  // Partner-specific
  | "school-needs-followup"
  | "ssa-recommendation-issue"
  | "training-quality-issue"
  | "evidence-issue"
  | "schedule-delay"
  | "coordination-issue"
  | "transport-distance-issue"
  | "partner-support-needed";

// Free-form text answers — keys vary by submitter role. We use a single
// shape rather than three separate types because every form is "label +
// short text" and a single shape makes storage / search / monthly trend
// extraction uniform.
export type DebriefAnswer = {
  /** Question key — stable string, matches the form's prompts. */
  key:    string;
  /** The question text as shown — kept alongside the answer so a
   *  reviewer reading a historical debrief never sees an answer without
   *  its question, even if the form prompt is later reworded. */
  prompt: string;
  /** What the staff member wrote. */
  text:   string;
};

// A draft is what the form holds in memory; a submission is what the
// router stores. Routing recipients are computed at submit time from
// the categories — clients don't pick them.
export type DebriefDraft = {
  submitterRole: DebriefSubmitterRole;
  submitterId:   string;       // staff or partner id
  submitterName: string;
  mood:          DebriefMood | null;
  answers:       DebriefAnswer[];
  categories:    DebriefCategory[];
  priority:      DebriefPriority;
};

export type DebriefSubmission = DebriefDraft & {
  id:        string;
  submittedAt: string;          // ISO timestamp
  routedTo:    DebriefReviewerRole[];
  status:      DebriefStatus;
};

// Map an EdifyRole (the auth role) to the submitter variant it can file.
// Partner-* roles all file partner debriefs.
export function submitterRoleFor(role: EdifyRole): DebriefSubmitterRole | null {
  switch (role) {
    case "CCEO":               return "CCEO";
    case "CountryProgramLead": return "CountryProgramLead";
    case "PartnerAdmin":
    case "PartnerFieldOfficer":
    case "PartnerViewer":      return "Partner";
    default:                   return null;
  }
}
