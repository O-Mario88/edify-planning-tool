// Controlled list of reschedule reasons (spec section 3).
//
// Keep this list narrow — analytics is only useful when reasons are
// consistent across thousands of reschedules. New reasons go through
// program leadership review, not ad-hoc additions per role.

import type { RescheduleReason, RescheduleReasonCategory } from "./types";

export const RESCHEDULE_REASONS: RescheduleReason[] = [
  // ─── Finance / Funds ───
  { key: "finance.no_funds_released",          label: "No funds released",                     category: "finance" },
  { key: "finance.funds_released_late",        label: "Funds released late",                    category: "finance" },
  { key: "finance.insufficient_funds",         label: "Insufficient funds",                     category: "finance" },
  { key: "finance.accountability_blocker",     label: "Accountability issue blocking new funds", category: "finance" },
  { key: "finance.reimbursement_delay",        label: "Reimbursement delay",                    category: "finance" },
  { key: "finance.budget_not_approved",        label: "Budget not approved",                    category: "finance" },
  { key: "finance.payment_not_cleared",        label: "Payment not cleared",                    category: "finance" },

  // ─── Transport / Distance / Movement ───
  { key: "transport.none",                     label: "No transport",                           category: "transport" },
  { key: "transport.came_late",                label: "Transport came late",                    category: "transport" },
  { key: "transport.breakdown",                label: "Transport breakdown",                    category: "transport" },
  { key: "transport.fuel_issue",               label: "Fuel issue",                             category: "transport" },
  { key: "transport.driver_unavailable",       label: "Driver unavailable",                     category: "transport" },
  { key: "transport.road_condition",           label: "Road condition / access issue",          category: "transport" },
  { key: "transport.long_distance",            label: "Long distance / secondary district challenge", category: "transport" },
  { key: "transport.accommodation",            label: "Accommodation not confirmed",            category: "transport" },
  { key: "transport.weather_travel",           label: "Weather affected travel",                category: "transport" },

  // ─── School Availability ───
  { key: "school.leader_unavailable",          label: "School leader not available",            category: "school_availability" },
  { key: "school.teachers_unavailable",        label: "Teachers not available",                 category: "school_availability" },
  { key: "school.requested_postponement",      label: "School requested postponement",          category: "school_availability" },
  { key: "school.closed",                      label: "School closed",                          category: "school_availability" },
  { key: "school.event_conflict",              label: "School event conflict",                  category: "school_availability" },
  { key: "school.exam_period",                 label: "Exams / assessment period",              category: "school_availability" },
  { key: "school.learners_unavailable",        label: "Learners not available",                 category: "school_availability" },
  { key: "school.board_meeting_conflict",      label: "Board/management meeting conflict",      category: "school_availability" },
  { key: "school.emergency",                   label: "Emergency at school",                    category: "school_availability" },

  // ─── Calendar / External Events ───
  { key: "calendar.public_holiday",            label: "Public holiday",                         category: "calendar" },
  { key: "calendar.district_activity_conflict",label: "District activity conflict",             category: "calendar" },
  { key: "calendar.government_inspection",     label: "Government inspection",                  category: "calendar" },
  { key: "calendar.religious_event",           label: "Religious event",                        category: "calendar" },
  { key: "calendar.community_event",           label: "Community event",                        category: "calendar" },
  { key: "calendar.national_event",            label: "National event",                         category: "calendar" },
  { key: "calendar.venue_unavailable",         label: "Training venue unavailable",             category: "calendar" },
  { key: "calendar.meeting_postponed",         label: "Meeting postponed",                      category: "calendar" },

  // ─── Staff / Partner Availability ───
  { key: "staff.sickness",                     label: "Staff sickness",                         category: "staff_availability" },
  { key: "staff.partner_sickness",             label: "Partner sickness",                       category: "staff_availability" },
  { key: "staff.family_emergency",             label: "Family emergency",                       category: "staff_availability" },
  { key: "staff.urgent_task",                  label: "Staff assigned urgent task",             category: "staff_availability" },
  { key: "staff.partner_unavailable",          label: "Partner unavailable",                    category: "staff_availability" },
  { key: "staff.facilitator_unavailable",      label: "Facilitator unavailable",                category: "staff_availability" },
  { key: "staff.pl_cd_requested_change",       label: "PL/CD requested change",                 category: "staff_availability" },
  { key: "staff.hr_approved_leave",            label: "HR-approved leave",                      category: "staff_availability" },

  // ─── Program / Quality Readiness ───
  { key: "program.ssa_not_completed",          label: "SSA not completed",                      category: "program_readiness" },
  { key: "program.materials_not_ready",        label: "Training materials not ready",           category: "program_readiness" },
  { key: "program.evidence_missing",           label: "Evidence from previous activity missing",category: "program_readiness" },
  { key: "program.participants_not_mobilized", label: "Participants not mobilized",             category: "program_readiness" },
  { key: "program.school_not_ready",           label: "School not ready",                       category: "program_readiness" },
  { key: "program.cluster_not_ready",          label: "Cluster not ready",                      category: "program_readiness" },
  { key: "program.wrong_activity_assigned",    label: "Wrong activity assigned",                category: "program_readiness" },
  { key: "program.revise_purpose",             label: "Need to revise activity purpose",        category: "program_readiness" },
  { key: "program.align_ssa",                  label: "Need to align with SSA recommendation",  category: "program_readiness" },

  // ─── Safety / Risk ───
  { key: "safety.security",                    label: "Security concern",                       category: "safety" },
  { key: "safety.safeguarding",                label: "Safeguarding concern",                   category: "safety" },
  { key: "safety.health_emergency",            label: "Health emergency",                       category: "safety" },
  { key: "safety.weather_risk",                label: "Weather safety risk",                    category: "safety" },
  { key: "safety.travel_risk",                 label: "Travel safety risk",                     category: "safety" },
  { key: "safety.community_tension",           label: "Community tension",                      category: "safety" },

  // ─── Other ───
  { key: "other.reason",                       label: "Other reason",                           category: "other", requiresNotes: true },
];

export const CATEGORY_LABEL: Record<RescheduleReasonCategory, string> = {
  finance:             "Finance / Funds",
  transport:           "Transport / Distance",
  school_availability: "School Availability",
  calendar:            "Calendar / External Events",
  staff_availability:  "Staff / Partner Availability",
  program_readiness:   "Program / Quality Readiness",
  safety:              "Safety / Risk",
  other:               "Other",
};

export const CATEGORY_ORDER: RescheduleReasonCategory[] = [
  "finance",
  "transport",
  "school_availability",
  "calendar",
  "staff_availability",
  "program_readiness",
  "safety",
  "other",
];

export function reasonByKey(key: string): RescheduleReason | undefined {
  return RESCHEDULE_REASONS.find((r) => r.key === key);
}

export function reasonsForCategory(category: RescheduleReasonCategory): RescheduleReason[] {
  return RESCHEDULE_REASONS.filter((r) => r.category === category);
}

/** Resolve a set of reason keys back to display labels. Used in the
 *  notification message body so reviewers see human text, not slugs. */
export function reasonLabels(keys: string[]): string[] {
  return keys.map((k) => reasonByKey(k)?.label ?? k);
}
