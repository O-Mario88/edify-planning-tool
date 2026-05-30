// Normalized action surface — the single shape every "10-Second
// Command" UI consumes.
//
// Every dashboard section (Next 3 Actions, Unified Inbox, Done For
// Today checklist, even the bulk-approve queue) reads ActionItem[].
// One type means the engine can pull from plan-cascade,
// weekly-fund-engine, fwi-engine, insights, etc. without each UI
// having to know which mock produced what.
//
// Why we normalize here:
//
//   • The roleActionEngine takes role + session → ActionItem[]. UIs
//     get a deterministic ranked list, not a tangle of per-module
//     queries. Decision speed is the metric.
//   • Adding a new action source (e.g. partner-onboarding alerts)
//     means writing one converter to ActionItem, not touching the UI.
//   • A normalised shape lets us add cross-cutting features —
//     bulk-approve, "what changed since you logged in", time-to-due
//     sorting — without per-source duplication.
//
// Importantly this type lives in a server+client-safe file so both
// server components (the role landing pages) and client islands
// (the bulk-approve checkboxes) can import it.

import type { EdifyRole } from "@/lib/auth-public";

// ────────── Categories ──────────
//
// Each ActionItem belongs to exactly one category. The category
// drives icon, default tone, and which inbox tab the item lands in.

export type ActionCategory =
  | "PlanApproval"          // CPL approves a CCEO plan; CD signs off budget
  | "FundApproval"          // weekly fund slip, monthly fund envelope
  | "Disbursement"          // accountant: pay the staff
  | "Reconciliation"        // accountant: reconcile a disbursement
  | "Reimbursement"         // accountant + lead: process a claim
  | "BalanceReturn"         // accountant: confirm returned cash
  | "DataVerification"      // M&E: resolve a Salesforce match
  | "CertifyData"           // CD: quality-sign-off
  | "FieldVisit"            // CCEO: today's visit
  | "Debrief"               // CCEO: submit the daily / weekly debrief
  | "EvidenceUpload"        // CCEO: photo / form for an activity
  | "SchoolRisk"            // any role: school moved to high-risk
  | "StaffSupport"          // CPL / HR: behind-pace / overloaded staff
  | "CostSettings"          // CD: activate cost-settings for the FY
  | "SpecialProject"        // any role: a project assignment
  | "RegionalEscalation"    // RVP: country-level intervention needed
  | "AdminSetup";           // Admin: user / permission / config

// ────────── Priority + risk ──────────
//
// Priority drives ordering inside the Next-3 + Inbox. Risk Level
// drives the dot colour. They aren't the same — a low-risk item can
// still be high priority because of a deadline.

export type ActionPriority = 1 | 2 | 3 | 4 | 5;  // 1 = highest
export type RiskLevel = "Critical" | "High" | "Medium" | "Low";

// ────────── Inbox tabs ──────────
//
// Fixed tab set across every role — the categorisation rule is:
//
//   • NeedsApproval — the user is the approver of record
//   • NeedsReview   — the user must look but not necessarily approve
//   • NeedsFollowUp — work the user already started, awaiting next step
//   • Blocked       — something else must resolve before this can move
//   • CompletedToday — closed in the last 24h, for the "done today" panel

export type InboxTab =
  | "NeedsApproval"
  | "NeedsReview"
  | "NeedsFollowUp"
  | "Blocked"
  | "CompletedToday";

// ────────── Approval safety ──────────
//
// Drives bulk-approve. The classifier in approval-safety.ts assigns
// one of these based on the source data + validation rules.

export type ApprovalSafety = "SafeToApprove" | "NeedsReview" | "Blocked";

// ────────── Status ──────────
//
// Status is the system-level state of the item — independent of the
// user's mental model. Used by the inbox to render the right chip.

export type ActionStatus =
  | "Pending"
  | "InProgress"
  | "AwaitingOther"
  | "OverdueLight"     // 1-3 days past
  | "OverdueHeavy"     // 4+ days past
  | "Completed";

// ────────── Affected entity ──────────
//
// What the action acts on. The UI displays this so the user knows
// "approve plan for Grace Njeri" instead of "approve item #128".

export type ActionAffected =
  | { kind: "Staff";   id: string; label: string; }
  | { kind: "School";  id: string; label: string; }
  | { kind: "Plan";    id: string; label: string; periodIso?: string; }
  | { kind: "Fund";    id: string; label: string; amountUgx?: number; }
  | { kind: "District"; id: string; label: string; }
  | { kind: "Country"; id: string; label: string; }
  | { kind: "Activity"; id: string; label: string; }
  | { kind: "System";  id: string; label: string; };

// ────────── CTA ──────────
//
// Primary CTA is what the dashboard surfaces as the big button.
// Secondary CTA is optional (e.g. "Open detail" next to "Approve").

export type ActionCTA = {
  label: string;
  href?: string;
  /// Custom action key used by the bulk-approve client component to
  /// route the click into the right handler. Server actions wrap
  /// these in the production version.
  intent?: "approve" | "reject" | "review" | "disburse" | "verify" | "submit" | "open";
};

// ────────── ActionItem ──────────

export type ActionItem = {
  id: string;
  role: EdifyRole;
  priority: ActionPriority;
  category: ActionCategory;
  title: string;
  /// One-sentence reason — what's at stake if ignored. Phrased
  /// human-first (the same voice rule as the dashboard hero).
  description: string;
  affectedEntity: ActionAffected;
  /// ISO date. Optional because some actions ("evidence upload") are
  /// roll-over, not deadline-bound.
  dueDate?: string;
  riskLevel: RiskLevel;
  status: ActionStatus;
  approvalSafety: ApprovalSafety;
  primaryAction: ActionCTA;
  secondaryAction?: ActionCTA;
  /// Where this came from — drives observability + debugging.
  sourceModule:
    | "planning"
    | "weekly-funds"
    | "fund-approvals"
    | "data-intake"
    | "team-targets"
    | "fwi"
    | "insights"
    | "ssa"
    | "cost-settings"
    | "leave"
    | "reimbursement"
    | "balance-return"
    | "admin"
    | "rvp"
    | "special-projects"
    // SimpleHealthyFocused additions — engines that produce action items
    // alongside the originals.
    | "workload-guardrails"
    | "support-quality"
    | "ssa-planning";
  /// Inbox tab assignment — computed by the engine, not the UI.
  inboxTab: InboxTab;
  // ─── SimpleHealthyFocused extensions ───
  //
  // These flags let downstream UIs (digest classifier, school-focused
  // surfaces, finance dashboards) filter intelligently without
  // re-deriving the meaning from category + description strings.
  /// Why an item is Blocked — populated only when approvalSafety="Blocked".
  /// Surfaced in the inbox tooltip so the user knows what to fix.
  blockedReason?: string;
  /// Which support area this item touches — drives the School Support
  /// Journey grouping. Optional because not every action targets a
  /// specific area (e.g. cost-settings activation).
  schoolSupportArea?:
    | "TeachingAndLearning"
    | "LearningEnvironment"
    | "LeadershipAndGovernance"
    | "ParentAndCommunityEngagement"
    | "StudentWellbeing"
    | "AssessmentAndDataUse";
  /// True when the action directly affects a school's improvement
  /// trajectory (visit, training, follow-up). Drives "School Support
  /// Focus" filters on CPL/CD dashboards.
  isSchoolFacing?: boolean;
  /// True when this action is preventing money from flowing
  /// (cost-settings draft, missing approval signature, blocked
  /// disbursement). Drives the Finance dashboards' "unblocker" view.
  isFinanceBlocking?: boolean;
  /// True when this action is holding the verification queue (M&E
  /// review pending, missing evidence on a verified-class record).
  isVerificationBlocking?: boolean;
  /// True when the action represents a workload-risk signal — staff
  /// approaching or past the healthy-load thresholds. Drives HR's
  /// "support watchlist" view + protects the staff from being
  /// labeled "underperforming" without context.
  isWorkloadRisk?: boolean;
  /// Convenience pointers — let cross-board generators reach related
  /// data without re-querying. Optional; populated when known.
  affectedDistrict?: string;
  affectedPartner?:  string;
  affectedStaff?:    string;
  /// Short-cut href for the primary action — useful in compact UIs
  /// where the full ActionCTA isn't rendered. Identical to
  /// primaryAction.href; duplicated for ergonomics.
  href?: string;
};

// ────────── Done-for-today ──────────
//
// Distinct from ActionItem because the check items are a fixed list
// per role rather than data-driven. The UI tints them green when the
// engine marks them satisfied.

export type DoneCheckItem = {
  id: string;
  label: string;
  /// What the engine inspects to flip this from open → done.
  satisfiedWhen: string;
  done: boolean;
  /// Optional sub-detail (e.g. "5 of 6 visits logged").
  detail?: string;
};

// ────────── ChangedSince entry ──────────
//
// What appeared / changed since the user last viewed this dashboard.
// Compact, link-out, optionally severity-tinted.

export type ChangedSinceEntry = {
  id: string;
  /// "Plan submitted" / "Fund disbursed" / "School moved to high risk"
  kind: string;
  /// "Grace Njeri" / "Bright Future PS" — who/what changed
  subject: string;
  /// Optional further context — "12 schools" / "UGX 4.2M" — when present
  /// the UI renders it as a tail clause.
  context?: string;
  /// ISO timestamp of when the change happened.
  at: string;
  /// One of the standard tones so the dot colour matches the rest of
  /// the app.
  tone: "info" | "success" | "warn" | "danger";
  /// Where clicking takes the user.
  href: string;
};

// ────────── Mission header ──────────
//
// Role-specific copy for the top of the page. Static per role today
// (lives in role-action-engine.ts); a future enhancement can swap
// the body for an LLM-generated summary based on the user's
// portfolio + the day's actions.

export type MissionHeader = {
  greeting: string;
  mission: string;
  /// "Today" / "This Week" / "May 2026" — current period context.
  periodLabel: string;
  /// One sentence — what to look at first.
  summary: string;
};

// ────────── Aggregate ──────────
//
// The roleActionEngine returns this aggregate. The UI consumes it
// directly — one engine call → one fully-populated dashboard.

export type RoleActionBoard = {
  role: EdifyRole;
  header: MissionHeader;
  nextThree: ActionItem[];          // top-3 by priority
  inbox: ActionItem[];              // everything (tabs filter)
  doneToday: DoneCheckItem[];
  changedSince: ChangedSinceEntry[];
};
