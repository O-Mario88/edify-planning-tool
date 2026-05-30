// Planning-as-Engine — types for the SSA-gated, gap-based Planning Tool.
// Every gap card on the planning page is one PlanningGap; once acted on, the
// gap disappears from the list and the activity moves to MyPlan / Partner
// Planning / Scheduled Activities.

// SSA gate — controls what actions are available
export type SsaGateState =
  | "SIT_NOT_DONE"              // No School Improvement Training has been held
  | "SIT_DONE_SSA_MISSING"      // SIT happened but the school never completed SSA
  | "SSA_COMPLETE_NOT_PLANNED"  // SSA done, no support has been planned yet
  | "PLANNED"                   // At least one activity has been planned
  | "IN_PROGRESS"               // Planned work has started
  | "COMPLETED"                 // Planned work finished
  | "VERIFIED";                 // Evidence verified by IA

// Gap categories shown as planning tabs/lists
export type GapKind =
  // Client school gaps
  | "NO_SSA"
  | "NO_VISIT"
  | "NO_TRAINING"
  | "NO_CLUSTER"
  | "TRAINING_DONE_NO_FOLLOWUP"
  | "SSA_COMPLETE_NOT_PLANNED"
  // Cluster gaps
  | "CLUSTER_NO_FIRST_MEETING"
  | "CLUSTER_NO_SECOND_MEETING"
  | "CLUSTER_NO_THIRD_MEETING"
  | "CLUSTER_NO_SIT"
  | "CLUSTER_SSA_MISSING"
  | "CLUSTER_TRAINING_NEEDED"
  // Core school gaps
  | "CORE_NO_SSA"
  | "CORE_MISSING_VISIT_1"
  | "CORE_MISSING_VISIT_2"
  | "CORE_MISSING_VISIT_3"
  | "CORE_MISSING_VISIT_4"
  | "CORE_MISSING_TRAINING_1"
  | "CORE_MISSING_TRAINING_2"
  | "CORE_MISSING_TRAINING_3"
  | "CORE_MISSING_TRAINING_4"
  | "CORE_PACKAGE_INCOMPLETE"
  | "CORE_CHAMPION_REVIEW"
  // Partner gaps
  | "PARTNER_ASSIGNED_NOT_SCHEDULED"
  | "PARTNER_SCHEDULED"
  | "PARTNER_DELAYED"
  | "PARTNER_RESCHEDULED"
  | "PARTNER_EVIDENCE_PENDING";

// High-level grouping for tabs
export type GapGroup =
  | "CLIENT_SCHOOLS"
  | "CLUSTERS"
  | "CORE_SCHOOLS"
  | "PARTNER_ASSIGNMENTS";

// Maps each GapKind to the GapGroup it belongs to
export const GAP_GROUP: Record<GapKind, GapGroup> = {
  // Client school gaps
  NO_SSA: "CLIENT_SCHOOLS",
  NO_VISIT: "CLIENT_SCHOOLS",
  NO_TRAINING: "CLIENT_SCHOOLS",
  NO_CLUSTER: "CLIENT_SCHOOLS",
  TRAINING_DONE_NO_FOLLOWUP: "CLIENT_SCHOOLS",
  SSA_COMPLETE_NOT_PLANNED: "CLIENT_SCHOOLS",
  // Cluster gaps
  CLUSTER_NO_FIRST_MEETING: "CLUSTERS",
  CLUSTER_NO_SECOND_MEETING: "CLUSTERS",
  CLUSTER_NO_THIRD_MEETING: "CLUSTERS",
  CLUSTER_NO_SIT: "CLUSTERS",
  CLUSTER_SSA_MISSING: "CLUSTERS",
  CLUSTER_TRAINING_NEEDED: "CLUSTERS",
  // Core school gaps
  CORE_NO_SSA: "CORE_SCHOOLS",
  CORE_MISSING_VISIT_1: "CORE_SCHOOLS",
  CORE_MISSING_VISIT_2: "CORE_SCHOOLS",
  CORE_MISSING_VISIT_3: "CORE_SCHOOLS",
  CORE_MISSING_VISIT_4: "CORE_SCHOOLS",
  CORE_MISSING_TRAINING_1: "CORE_SCHOOLS",
  CORE_MISSING_TRAINING_2: "CORE_SCHOOLS",
  CORE_MISSING_TRAINING_3: "CORE_SCHOOLS",
  CORE_MISSING_TRAINING_4: "CORE_SCHOOLS",
  CORE_PACKAGE_INCOMPLETE: "CORE_SCHOOLS",
  CORE_CHAMPION_REVIEW: "CORE_SCHOOLS",
  // Partner gaps
  PARTNER_ASSIGNED_NOT_SCHEDULED: "PARTNER_ASSIGNMENTS",
  PARTNER_SCHEDULED: "PARTNER_ASSIGNMENTS",
  PARTNER_DELAYED: "PARTNER_ASSIGNMENTS",
  PARTNER_RESCHEDULED: "PARTNER_ASSIGNMENTS",
  PARTNER_EVIDENCE_PENDING: "PARTNER_ASSIGNMENTS",
};

// What the next action should be when this gap is resolved
export type PlanningActionKind =
  | "COMPLETE_SSA"               // The only action when SSA is missing
  | "SCHEDULE_SIT"               // Schedule School Improvement Training
  | "SCHEDULE_VISIT"
  | "SCHEDULE_FOLLOW_UP_VISIT"
  | "SCHEDULE_COACHING_VISIT"
  | "SCHEDULE_IN_SCHOOL_TRAINING"
  | "SCHEDULE_CLUSTER_TRAINING"
  | "SCHEDULE_CLUSTER_MEETING"
  | "SCHEDULE_GROUP_TRAINING"
  | "ASSIGN_TO_SELF"
  | "ASSIGN_TO_CCEO"
  | "ASSIGN_TO_PARTNER"
  | "ADD_TO_CLUSTER"
  | "VIEW_SSA"
  | "VIEW_SCHOOL"
  | "VIEW_CLUSTER";

// Recommended action for a gap card — comes from the engine
export type PlanningRecommendation = {
  primaryAction:    PlanningActionKind;
  primaryLabel:     string;                       // e.g. "Schedule in-school training on Teaching & Learning"
  secondaryActions: PlanningActionKind[];         // up to 2-3 extras
  reason:           string;                       // why this is recommended (SSA weakness, missing visit, etc.)
  purpose?:         string;                       // optional purpose copy that auto-fills in the schedule form
  intervention?:    string;                       // SSA intervention this action addresses
};

// Date vs week/month scheduling discipline from the spec
export type SchedulePrecision = "EXACT_DATE" | "WEEK_OF_MONTH";

// Maps each PlanningActionKind to its required precision
// (trainings + cluster meetings need exact date; visits can use week/month)
export const SCHEDULE_PRECISION: Record<PlanningActionKind, SchedulePrecision> = {
  COMPLETE_SSA: "EXACT_DATE",
  SCHEDULE_SIT: "EXACT_DATE",
  SCHEDULE_VISIT: "WEEK_OF_MONTH",
  SCHEDULE_FOLLOW_UP_VISIT: "WEEK_OF_MONTH",
  SCHEDULE_COACHING_VISIT: "WEEK_OF_MONTH",
  SCHEDULE_IN_SCHOOL_TRAINING: "EXACT_DATE",
  SCHEDULE_CLUSTER_TRAINING: "EXACT_DATE",
  SCHEDULE_CLUSTER_MEETING: "EXACT_DATE",
  SCHEDULE_GROUP_TRAINING: "EXACT_DATE",
  ASSIGN_TO_SELF: "WEEK_OF_MONTH",
  ASSIGN_TO_CCEO: "WEEK_OF_MONTH",
  ASSIGN_TO_PARTNER: "WEEK_OF_MONTH",
  ADD_TO_CLUSTER: "WEEK_OF_MONTH",
  VIEW_SSA: "EXACT_DATE",
  VIEW_SCHOOL: "EXACT_DATE",
  VIEW_CLUSTER: "EXACT_DATE",
};

// The atomic unit of the gap-based planning page
export type PlanningGap = {
  id:                  string;
  kind:                GapKind;
  group:               GapGroup;

  // Subject of the gap (one of these is set)
  schoolId?:           string;
  schoolName?:         string;
  clusterId?:          string;
  clusterName?:        string;
  coreSchoolId?:       string;

  // Operational context
  district:            string;
  region:              string;
  assignedCceoId?:     string;
  assignedCceoName?:   string;
  assignedPartnerId?:  string;
  assignedPartnerName?: string;

  // SSA gate — controls which actions are available on the card
  ssaGate:             SsaGateState;

  // SSA snapshot (only set when ssaGate is past SSA_MISSING)
  ssaAverageScore?:    number;          // /10
  ssaWeakestArea?:     string;          // e.g. "Teaching & Learning"
  ssaWeakestScore?:    number;
  ssaSecondWeakest?:   string;

  // Priority — surfaced as a chip on the card
  priority:            "CRITICAL" | "HIGH" | "NORMAL" | "LOW";
  blockingReason?:     string;          // when ssaGate locks the card, this explains why

  // Recommendation produced by the engine
  recommendation:      PlanningRecommendation;

  // Provenance
  createdAtIso:        string;
  lastTouchedIso?:     string;
};

// Action-state — used by the UI to render the locked / available state
export type ActionState = "AVAILABLE" | "LOCKED" | "DISABLED";

/**
 * Determines whether a given action is available based on the SSA gate state.
 *
 * Rule: COMPLETE_SSA is always AVAILABLE when SSA is missing; everything else
 * is LOCKED until SSA is complete.
 *
 * View-only actions (VIEW_SSA, VIEW_SCHOOL, VIEW_CLUSTER) remain AVAILABLE at
 * any gate so users can always inspect the subject of a gap.
 */
export function actionStateFor(
  gate: SsaGateState,
  action: PlanningActionKind,
): ActionState {
  // View actions are always available — they never mutate state.
  if (action === "VIEW_SSA" || action === "VIEW_SCHOOL" || action === "VIEW_CLUSTER") {
    return "AVAILABLE";
  }

  // When SSA is missing, only COMPLETE_SSA is available; everything else is LOCKED.
  if (gate === "SIT_NOT_DONE" || gate === "SIT_DONE_SSA_MISSING") {
    if (action === "COMPLETE_SSA") return "AVAILABLE";
    // SCHEDULE_SIT is the natural next step when SIT hasn't been done yet.
    if (gate === "SIT_NOT_DONE" && action === "SCHEDULE_SIT") return "AVAILABLE";
    return "LOCKED";
  }

  // SSA is complete — COMPLETE_SSA itself is no longer applicable.
  if (action === "COMPLETE_SSA") return "DISABLED";

  // All other actions are AVAILABLE once SSA is complete, regardless of
  // downstream state (PLANNED / IN_PROGRESS / COMPLETED / VERIFIED).
  return "AVAILABLE";
}
