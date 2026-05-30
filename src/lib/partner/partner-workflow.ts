// Partner Delivery + Payment Accountability — state machine.
//
// Single source of truth for the partner activity lifecycle. Every
// downstream dashboard (Partner, CCEO, PL, Accountant) reads its
// queues from this enum so a status change in one surface
// automatically reroutes the activity to whoever owns the next step.
//
// Design principles encoded here:
//   • Simple   — each role has exactly one next step, derived from
//                ROLE_NEXT_STEP keyed on status.
//   • Healthy  — every transition is gated (canTransition()) so no
//                accidental skips (e.g. partner can't mark Paid).
//   • Focused  — every Paid status must trace back through CCEO
//                confirmation, PL approval, AND IA verification,
//                enforced by REQUIRED_PATH. Partner payment approvers are
//                CCEO → PL → IA; only then does it reach the accountant.

import type { EdifyRole } from "@/lib/auth-public";

// ────────── Status enum ──────────

export type PartnerWorkflowStatus =
  // Linear happy path
  | "PlannedByStaff"          // Staff has created the activity, not yet assigned
  | "AssignedToPartner"       // Staff has selected a partner; partner sees on their inbox
  | "ScheduledByPartner"      // Partner has placed it in a delivery week
  | "Delivered"               // Partner has marked delivery done
  | "EvidenceSubmitted"       // Partner has uploaded required evidence
  | "AwaitingCceoConfirmation"// CCEO needs to confirm work was completed properly
  | "ConfirmedByCceo"         // CCEO has signed off — payment can move
  | "AwaitingPlApproval"      // PL needs to approve the payment request
  | "ApprovedByPl"            // PL has approved
  | "AwaitingIaVerification"  // IA verifies the Salesforce entry before payment
  | "IaVerified"              // IA has verified — payment can move to accountant
  | "SentToAccountant"        // Accountant queue
  | "Paid"                    // Accountant has cleared
  | "Closed"                  // Activity fully closed; school journey updated
  // Branches
  | "Delayed"                 // SLA breached on any pre-delivery step
  | "ReturnedToPartner"       // CCEO/PL returned for evidence/report correction
  | "ReturnedToCceo"          // PL returned to CCEO for clarification
  | "Rejected"                // Work invalid / outside scope
  | "OnHold"                  // Accountant or PL paused with reason
  | "Reassigned";             // Activity moved to a different partner

// Linear happy-path order, used for progress indicators.
export const HAPPY_PATH: PartnerWorkflowStatus[] = [
  "PlannedByStaff",
  "AssignedToPartner",
  "ScheduledByPartner",
  "Delivered",
  "EvidenceSubmitted",
  "AwaitingCceoConfirmation",
  "ConfirmedByCceo",
  "AwaitingPlApproval",
  "ApprovedByPl",
  "AwaitingIaVerification",
  "IaVerified",
  "SentToAccountant",
  "Paid",
  "Closed",
];

// Human-readable label per status.
export const STATUS_LABEL: Record<PartnerWorkflowStatus, string> = {
  PlannedByStaff:           "Planned by staff",
  AssignedToPartner:        "Assigned to partner",
  ScheduledByPartner:       "Scheduled by partner",
  Delivered:                "Delivered",
  EvidenceSubmitted:        "Evidence submitted",
  AwaitingCceoConfirmation: "Awaiting CCEO confirmation",
  ConfirmedByCceo:          "Confirmed by CCEO",
  AwaitingPlApproval:       "Awaiting PL approval",
  ApprovedByPl:             "Approved by PL",
  AwaitingIaVerification:   "Awaiting IA verification",
  IaVerified:               "IA verified",
  SentToAccountant:         "Sent to accountant",
  Paid:                     "Paid / cleared",
  Closed:                   "Closed",
  Delayed:                  "Delayed",
  ReturnedToPartner:        "Returned to partner",
  ReturnedToCceo:           "Returned to CCEO",
  Rejected:                 "Rejected",
  OnHold:                   "On hold",
  Reassigned:               "Reassigned",
};

// ────────── Role ownership ──────────
//
// "Whose move is it next?" — given a status, which role owns the next
// transition. Drives the inbox-routing on every dashboard.

export const ROLE_NEXT_STEP: Record<PartnerWorkflowStatus, EdifyRole | "Staff" | "System" | null> = {
  PlannedByStaff:           "Staff",                // assign partner
  AssignedToPartner:        "PartnerAdmin",         // schedule
  ScheduledByPartner:       "PartnerFieldOfficer",  // deliver on the scheduled day
  Delivered:                "PartnerAdmin",         // upload evidence
  EvidenceSubmitted:        "CCEO",                 // confirm
  AwaitingCceoConfirmation: "CCEO",                 // confirm
  ConfirmedByCceo:          "System",               // auto-routes to PL queue
  AwaitingPlApproval:       "CountryProgramLead",   // approve
  ApprovedByPl:             "System",               // auto-routes to IA queue
  AwaitingIaVerification:   "ImpactAssessment",     // verify Salesforce entry
  IaVerified:               "System",               // auto-routes to accountant queue
  SentToAccountant:         "ProgramAccountant",    // clear
  Paid:                     "System",               // auto-closes when school journey updates
  Closed:                   null,                   // terminal
  Delayed:                  "Staff",                // remind or reassign
  ReturnedToPartner:        "PartnerAdmin",         // correct
  ReturnedToCceo:           "CCEO",                 // clarify
  Rejected:                 null,                   // terminal
  OnHold:                   "CountryProgramLead",   // resume or reject
  Reassigned:               "PartnerAdmin",         // new partner schedules
};

// ────────── Tone per status ──────────
//
// Used for status chips across all dashboards so the same colour
// always means the same thing.

export type StatusTone = "neutral" | "info" | "warn" | "danger" | "success" | "muted";

export const STATUS_TONE: Record<PartnerWorkflowStatus, StatusTone> = {
  PlannedByStaff:           "neutral",
  AssignedToPartner:        "info",
  ScheduledByPartner:       "info",
  Delivered:                "info",
  EvidenceSubmitted:        "info",
  AwaitingCceoConfirmation: "warn",
  ConfirmedByCceo:          "success",
  AwaitingPlApproval:       "warn",
  ApprovedByPl:             "success",
  AwaitingIaVerification:   "warn",
  IaVerified:               "success",
  SentToAccountant:         "warn",
  Paid:                     "success",
  Closed:                   "muted",
  Delayed:                  "danger",
  ReturnedToPartner:        "warn",
  ReturnedToCceo:           "warn",
  Rejected:                 "danger",
  OnHold:                   "warn",
  Reassigned:               "neutral",
};

// ────────── Allowed transitions ──────────
//
// `from → to` pairs that the workflow accepts, gated by `byRole`.
// Anything not listed is forbidden — keeps an accidental
// `partner.markPaid()` impossible by construction.

type Transition = {
  from: PartnerWorkflowStatus;
  to: PartnerWorkflowStatus;
  byRole: ReadonlyArray<EdifyRole | "Staff" | "System">;
  label: string;
};

export const TRANSITIONS: ReadonlyArray<Transition> = [
  // Linear happy path
  { from: "PlannedByStaff",           to: "AssignedToPartner",        byRole: ["CCEO", "CountryProgramLead", "Admin"],     label: "Assign partner" },
  { from: "AssignedToPartner",        to: "ScheduledByPartner",       byRole: ["PartnerAdmin", "Admin"],                   label: "Schedule activity" },
  { from: "ScheduledByPartner",       to: "Delivered",                byRole: ["PartnerAdmin", "PartnerFieldOfficer", "Admin"], label: "Mark delivered" },
  { from: "Delivered",                to: "EvidenceSubmitted",        byRole: ["PartnerAdmin", "PartnerFieldOfficer", "Admin"], label: "Upload Evidence" },
  { from: "EvidenceSubmitted",        to: "AwaitingCceoConfirmation", byRole: ["System"],                                  label: "Route to CCEO" },
  { from: "AwaitingCceoConfirmation", to: "ConfirmedByCceo",          byRole: ["CCEO", "Admin"],                           label: "Confirm completed" },
  { from: "ConfirmedByCceo",          to: "AwaitingPlApproval",       byRole: ["System"],                                  label: "Route to PL" },
  { from: "AwaitingPlApproval",       to: "ApprovedByPl",             byRole: ["CountryProgramLead", "Admin"],             label: "Approve payment" },
  { from: "ApprovedByPl",             to: "AwaitingIaVerification",   byRole: ["System"],                                  label: "Route to IA verification" },
  { from: "AwaitingIaVerification",   to: "IaVerified",               byRole: ["ImpactAssessment", "Admin"],               label: "Verify Salesforce entry" },
  { from: "IaVerified",               to: "SentToAccountant",         byRole: ["System"],                                  label: "Route to accountant" },
  { from: "SentToAccountant",         to: "Paid",                     byRole: ["ProgramAccountant", "Admin"],              label: "Clear payment" },
  { from: "Paid",                     to: "Closed",                   byRole: ["System", "CCEO", "Admin"],                 label: "Close activity" },
  // CCEO branches
  { from: "AwaitingCceoConfirmation", to: "ReturnedToPartner",        byRole: ["CCEO", "Admin"],                           label: "Return to partner" },
  { from: "AwaitingCceoConfirmation", to: "Rejected",                 byRole: ["CCEO", "Admin"],                           label: "Reject confirmation" },
  // PL branches
  { from: "AwaitingPlApproval",       to: "ReturnedToCceo",           byRole: ["CountryProgramLead", "Admin"],             label: "Return to CCEO" },
  { from: "AwaitingPlApproval",       to: "ReturnedToPartner",        byRole: ["CountryProgramLead", "Admin"],             label: "Return to partner" },
  { from: "AwaitingPlApproval",       to: "Rejected",                 byRole: ["CountryProgramLead", "Admin"],             label: "Reject payment" },
  { from: "AwaitingPlApproval",       to: "OnHold",                   byRole: ["CountryProgramLead", "Admin"],             label: "Hold payment" },
  // IA branches
  { from: "AwaitingIaVerification",   to: "ReturnedToPartner",        byRole: ["ImpactAssessment", "Admin"],               label: "Return for correction" },
  { from: "AwaitingIaVerification",   to: "ReturnedToCceo",           byRole: ["ImpactAssessment", "Admin"],               label: "Return to CCEO" },
  { from: "AwaitingIaVerification",   to: "Rejected",                 byRole: ["ImpactAssessment", "Admin"],               label: "Reject — Salesforce entry invalid" },
  // Accountant branches
  { from: "SentToAccountant",         to: "ReturnedToPartner",        byRole: ["ProgramAccountant", "Admin"],              label: "Return for correction" },
  { from: "SentToAccountant",         to: "OnHold",                   byRole: ["ProgramAccountant", "Admin"],              label: "Hold payment" },
  // Partner correction loop
  { from: "ReturnedToPartner",        to: "EvidenceSubmitted",        byRole: ["PartnerAdmin", "PartnerFieldOfficer"],     label: "Resubmit" },
  // PL resume / reject after hold
  { from: "OnHold",                   to: "AwaitingPlApproval",       byRole: ["CountryProgramLead", "Admin"],             label: "Resume" },
  { from: "OnHold",                   to: "Rejected",                 byRole: ["CountryProgramLead", "Admin"],             label: "Reject" },
  // Delay flag — system can set, staff can clear
  { from: "AssignedToPartner",        to: "Delayed",                  byRole: ["System"],                                  label: "Flag as delayed" },
  { from: "ScheduledByPartner",       to: "Delayed",                  byRole: ["System"],                                  label: "Flag as delayed" },
  { from: "Delayed",                  to: "ScheduledByPartner",       byRole: ["PartnerAdmin"],                            label: "Reschedule" },
  { from: "Delayed",                  to: "Reassigned",               byRole: ["CCEO", "CountryProgramLead", "Admin"],     label: "Reassign to another partner" },
  { from: "Reassigned",               to: "AssignedToPartner",        byRole: ["System"],                                  label: "Routed to new partner" },
];

// ────────── Helpers ──────────

export function canTransition(
  from: PartnerWorkflowStatus,
  to: PartnerWorkflowStatus,
  role: EdifyRole | "Staff" | "System",
): boolean {
  return TRANSITIONS.some(
    (t) =>
      t.from === from &&
      t.to === to &&
      (t.byRole as ReadonlyArray<string>).includes(role),
  );
}

// All transitions a given role can fire from the current status.
// Drives the action menu on every status chip.
export function actionsFor(
  status: PartnerWorkflowStatus,
  role: EdifyRole | "Staff" | "System",
): Transition[] {
  return TRANSITIONS.filter(
    (t) =>
      t.from === status &&
      (t.byRole as ReadonlyArray<string>).includes(role),
  );
}

// Progress (%) along the happy path. Branches return null.
export function progressPct(status: PartnerWorkflowStatus): number | null {
  const i = HAPPY_PATH.indexOf(status);
  if (i === -1) return null;
  return Math.round((i / (HAPPY_PATH.length - 1)) * 100);
}

// Required chain of past statuses for an activity to be eligible
// for the given step. Used by gates: "payment cannot move to PL
// unless CCEO has confirmed".
export const REQUIRED_PATH: Partial<Record<PartnerWorkflowStatus, PartnerWorkflowStatus[]>> = {
  AwaitingPlApproval:     ["EvidenceSubmitted", "ConfirmedByCceo"],
  AwaitingIaVerification: ["EvidenceSubmitted", "ConfirmedByCceo", "ApprovedByPl"],
  SentToAccountant:       ["EvidenceSubmitted", "ConfirmedByCceo", "ApprovedByPl", "IaVerified"],
  Paid:                   ["EvidenceSubmitted", "ConfirmedByCceo", "ApprovedByPl", "IaVerified", "SentToAccountant"],
};
