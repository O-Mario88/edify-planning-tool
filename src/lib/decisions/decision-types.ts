// School Improvement Decision Engine — type contract.
//
// A `Decision` is the unit the engine produces. It is richer than an
// `ActionItem` because the platform's value isn't "here are tasks" — it
// is "here is a judgment, with reasoning, alternatives, and projected
// impact." A decision answers: what should we do next, who should do
// it, what will it cost, and what evidence supports it.
//
// Two flavours per role:
//   • NextBestAction   — operational. "You personally do this today."
//   • NextBestDecision — judgment. "Leadership chooses between A and B."
//
// Engines (SSA, FWI, weekly-funds, partner, workload-guardrails) feed
// signals into the decision engine; the engine fuses them into Decisions.
// The UI consumes Decisions and never re-derives meaning from raw signals.

import type { EdifyRole } from "@/lib/auth-public";

// ────────── Subject ──────────
//
// What the decision is *about*. The UI uses subject.kind to pick the
// right icon, link template, and detail card.

export type DecisionSubject =
  | { kind: "School";    id: string; label: string; district?: string }
  | { kind: "Staff";     id: string; label: string; role?: string }
  | { kind: "Partner";   id: string; label: string }
  | { kind: "Portfolio"; id: string; label: string }        // a staff's whole portfolio
  | { kind: "Budget";    id: string; label: string }         // a budget envelope
  | { kind: "District";  id: string; label: string }
  | { kind: "Country";   id: string; label: string }
  | { kind: "Fund";      id: string; label: string; amountUgx?: number }
  /// For decisions about queues / system-level surfaces (e.g. "5 plans
  /// are safe to bulk-approve"). Used sparingly — most decisions should
  /// have a concrete subject.
  | { kind: "System";    id: string; label: string };

// ────────── Rationale chain ──────────
//
// The visible *why* — the signals that produced the recommendation.
// Each node is one signal: a measurement, a threshold breach, a
// historical pattern, or a constraint. The UI renders these as a
// stacked list under "Why this matters."
//
// Weights:
//   primary     — load-bearing. Without this signal, the decision wouldn't exist.
//   supporting  — strengthens the case (corroborating data, pattern match).
//   context     — necessary background (workload, geography, availability).

export type RationaleWeight = "primary" | "supporting" | "context";

export type RationaleNode = {
  /// What the signal says. Phrased as a complete fragment:
  /// "Teaching & Learning SSA: 4/10" / "No follow-up in 47 days".
  signal: string;
  /// One of the engines that produced it. Drives the tiny source label
  /// shown on hover for trust + debuggability.
  source:
    | "ssa-planning"
    | "fwi-engine"
    | "weekly-fund-engine"
    | "workload-guardrails"
    | "partner-health"
    | "partner-fraud"
    | "support-quality"
    | "approval-safety"
    | "evidence"
    | "geography"
    | "history";
  weight: RationaleWeight;
  /// Optional tone — red = problem, amber = caution, green = positive
  /// (e.g. "Champion school 18km away"). Drives the dot colour next to
  /// the signal line.
  tone?: "red" | "amber" | "green";
};

// ────────── Confidence ──────────
//
// Not every recommendation is equally certain. Deterministic decisions
// ("evidence missing → upload") are High. Pattern-matched recommendations
// ("predict SSA regression based on 47-day gap") may be Medium or Low.
// The pill is visible on the card so the user can weight the advice.

export type DecisionConfidence = "High" | "Medium" | "Low";

// ────────── Owner recommendation ──────────
//
// For decisions where the engine has an opinion about who should
// execute. The reasoning is part of the decision's audit trail — if
// leadership rebalances against the recommendation, that's a learning
// signal for the engine.

export type OwnerRecommendation = {
  name: string;
  role: string;
  /// One sentence: why this person? "Already in district this week" /
  /// "Highest skill match" / "Lowest workload on the team."
  reasoning: string;
  /// True if the engine flagged a fairness concern about an alternative
  /// owner — e.g. "Staff A is at 95th-percentile workload, recommend
  /// Partner B instead." Drives the small fairness chip in the card.
  fairnessAdjusted?: boolean;
};

// ────────── Cost breakdown ──────────
//
// When the decision implies spending, the breakdown is shown inline so
// leadership doesn't have to open a separate budget tool to weigh the
// trade-off.

export type CostLine = {
  label: string;       // "Transport (2-way, 74km)"
  amountUgx: number;
  /// Optional: why this line is higher than baseline. Used for the
  /// "cost driver" tooltip — "secondary district requires overnight."
  note?: string;
};

// ────────── Alternative ──────────
//
// Next-Best-Decisions are often comparative: Option A vs. Option B.
// The engine surfaces both with the recommended one marked. Leadership
// chooses; the choice is recorded as a decision trail entry.

export type DecisionAlternative = {
  label: string;        // "Train 20 new schools"
  costUgx: number;
  expectedImpact: "High" | "Medium" | "Low";
  projectedOutcome: string;
  risk: "High" | "Medium" | "Low";
  recommended: boolean;
  /// One sentence: why this alternative was rated this way.
  reasoning: string;
};

// ────────── Urgency ──────────
//
// Separate from priority. Urgency is the *deadline pressure*; priority
// is the *importance ranking* among visible decisions.

export type DecisionUrgency = "Today" | "ThisWeek" | "ThisMonth" | "ThisQuarter";

// ────────── Decision kind ──────────

export type DecisionKind = "NextBestAction" | "NextBestDecision";

// ────────── Category ──────────
//
// Drives the card's accent icon. Categories are deliberately broader
// than ActionCategory because a single decision often spans multiple
// underlying action sources.

export type DecisionCategory =
  | "SchoolIntervention"     // visit, coaching, training for a school
  | "WorkloadRebalance"      // shift portfolio between staff
  | "FundReallocation"       // move budget between activities/regions
  | "PartnerEscalation"      // partner needs support or correction
  | "EvidenceGap"            // verification holdup
  | "RiskMitigation"         // school predicted to regress
  | "Recognition"            // recognize hidden leader / champion school
  | "Approval"               // bulk approve safe items
  | "Compliance"             // government / donor compliance gap
  | "CapacityBuilding"       // training, coaching for staff/partners
  | "Strategic";             // country-level resource allocation

// ────────── Decision ──────────

export type Decision = {
  id: string;
  role: EdifyRole;
  kind: DecisionKind;
  category: DecisionCategory;

  /// Imperative one-line. "Send coaching to Hope Primary this week."
  /// "Rebalance 8 schools from Sarah to David."
  headline: string;

  /// Optional one-line context — shown directly under headline in a
  /// muted tone. Adds the "so that..." framing without bloating the
  /// hero. Keep under ~110 chars.
  subhead?: string;

  subject: DecisionSubject;

  /// Visible reasoning chain. Order matters — primary signals first.
  rationale: RationaleNode[];

  confidence: DecisionConfidence;
  /// Optional: one sentence explaining the confidence rating.
  confidenceWhy?: string;

  /// If the decision implies cost, total + breakdown. Totals drive the
  /// inline budget chip; breakdown opens on click.
  costEstimateUgx?: number;
  costBreakdown?: CostLine[];

  /// Projected outcome if the decision is acted on. Honest about
  /// uncertainty — "Likely to move SSA T&L from 4 to 6 within 60 days
  /// based on 14 similar schools."
  projectedImpact?: string;

  recommendedOwner?: OwnerRecommendation;

  /// For NextBestDecision-kind comparative trade-offs. Each alternative
  /// is rendered as a side-by-side card.
  alternatives?: DecisionAlternative[];

  urgency: DecisionUrgency;
  /// ISO date when the decision must be made by. Optional — some
  /// decisions are recurring opportunities, not deadlined.
  decideBy?: string;

  /// Priority among visible decisions. 1 = top of the list.
  priority: 1 | 2 | 3 | 4 | 5;

  /// Overall risk tone for the card border.
  tone: "red" | "amber" | "green";

  /// The single button shown on the card.
  primaryAction: { label: string; href: string; intent?: "act" | "approve" | "review" };
  /// Optional secondary action (e.g. "Reassign", "Defer", "Decline").
  secondaryAction?: { label: string; href: string };

  /// Audit metadata. The engine fills this in.
  generatedAt: string;
  /// Which engines fed signals into this decision. Used by the source
  /// chip + the audit trail.
  sourceSignals: string[];

  /// Optional explicit "Why now?" line — when the decision became
  /// active. "Triggered today because school crossed 45-day no-visit
  /// threshold." Surfaces above the rationale chain.
  triggeredBecause?: string;
};

// ────────── Aggregate ──────────
//
// One engine call → one DecisionBoard per role. The page consumes this
// directly. UI is a renderer.

export type DecisionBoard = {
  role: EdifyRole;
  /// Greeting + mission line + period label, same shape as the existing
  /// MissionHeader from action-types. We re-declare so this module
  /// doesn't pull from actions/ — keeps the boundary clean.
  header: {
    greeting: string;
    mission: string;
    periodLabel: string;
    /// One sentence: the leading decision context. "1 critical school,
    /// 1 overloaded staff, 2 evidence gaps blocking M&E."
    summary: string;
  };
  /// The single most important decision — rendered as the hero card.
  topDecision: Decision | null;
  /// Remaining decisions, ranked by priority then urgency.
  nextBestActions: Decision[];     // NextBestAction kind
  nextBestDecisions: Decision[];   // NextBestDecision kind
  /// Empty-state message when both lists are empty.
  emptyState?: { headline: string; body: string };
};
