// Mock decisions for the School Improvement Decision Engine.
//
// These are the shapes the engine will produce in production. They are
// hand-written today so the UI can be designed against real, multi-signal
// rationale chains rather than synthetic placeholders.
//
// When the engine lands, swap `decisionBoardFor(role)` for a real call
// that fuses signals from ssa-planning, fwi-engine, weekly-fund-engine,
// partner-health, workload-guardrails. The Decision type stays.
//
// Cost numbers shown here come from the canonical cost engine
// (lib/cost-engine) using the CD-set rates. Tests assert the alignment.

import type { Decision, DecisionBoard, CostLine } from "./decision-types";
import type { EdifyRole } from "@/lib/auth-public";
import { computeVisitCost, type VisitCostRates } from "@/lib/cost-engine/cost-engine";

// Rates duplicated here so the mock builder stays pure (no server-only
// import). In production the page loads rates via loadVisitCostRates()
// and passes them to the engine — these literals match what the CD has
// set in cost-settings-mock.ts.
const MOCK_RATES: VisitCostRates = {
  staffPrimaryTransportPerSchool:   56_000,
  staffSecondaryTransportPerSchool: 66_000,
  staffLunchPerDay:                 30_000,
  staffBreakfastPerDay:             20_000, // secondary district only
  staffDinnerPerDay:                50_000, // secondary district only
  staffAccommodationPerNight:      150_000, // secondary district only
  partnerLumpSumPerSchool:          40_000,
};

// Helper — turn an engine breakdown into the Decision's CostLine[] shape.
function breakdownToCostLines(lines: { label: string; amountUgx: number; note?: string }[]): CostLine[] {
  return lines.map((l) => ({ label: l.label, amountUgx: l.amountUgx, note: l.note }));
}

// ────────── Cost helpers (engine-driven) ──────────

// Hope Primary is in the CCEO's home district (Mukono) → primary, single
// school, single day → 56k transport + 30k lunch = 86k.
const COST_HOPE_FOLLOWUP = computeVisitCost({
  mode: "staff",
  schools: [{ schoolId: "S-HP-1", schoolName: "Hope Primary School", districtType: "primary" }],
  days: 1,
  rates: MOCK_RATES,
});

// Grace Primary intervention is recommended to be delivered by Partner
// LTU — partner lump sum, 1 school = 40k.
const COST_GRACE_PARTNER = computeVisitCost({
  mode: "partner",
  schools: [{ schoolId: "S-GP-1", schoolName: "Grace Primary School", districtType: "primary" }],
  rates: MOCK_RATES,
});

// "Skip Victory, go to Grace" — same primary district, single day, single
// school. Demonstrates how a deceptively small swap costs the same as a
// normal day-trip.
const COST_GRACE_SWAP = computeVisitCost({
  mode: "staff",
  schools: [{ schoolId: "S-GP-1", schoolName: "Grace Primary School", districtType: "primary" }],
  days: 1,
  rates: MOCK_RATES,
});

// Kitgum cluster trip — 3 schools in a secondary district over 2 days.
// Demonstrates the secondary-district pricing tier: higher transport,
// dinner + accommodation auto-included.
const COST_KITGUM_CLUSTER = computeVisitCost({
  mode: "staff",
  schools: [
    { schoolId: "S-KT-1", schoolName: "Kitgum Central PS",  districtType: "secondary" },
    { schoolId: "S-KT-2", schoolName: "Layibi Memorial PS", districtType: "secondary" },
    { schoolId: "S-KT-3", schoolName: "Pajule Primary",     districtType: "secondary" },
  ],
  days: 2,
  rates: MOCK_RATES,
});

// ────────── CCEO — Next Best Actions ──────────
//
// Field officer. Decisions are operational: "do this today." Each card
// gives them: where to be, why it matters, what to bring, and what
// counts as done.

const CCEO_DECISIONS: Decision[] = [
  {
    id: "cceo-d-1",
    role: "CCEO",
    kind: "NextBestAction",
    category: "SchoolIntervention",
    headline: "Visit Hope Primary today — follow up on phonics training",
    subhead: "21-day window closes Friday. Skip the follow-up and the training won't lock.",
    subject: { kind: "School", id: "S-HP-1", label: "Hope Primary School", district: "Mukono" },
    rationale: [
      { signal: "Teaching & Learning SSA: 4/10 (weakest area)",            source: "ssa-planning",       weight: "primary",    tone: "red" },
      { signal: "Phonics training delivered 14 days ago — no follow-up",   source: "history",            weight: "primary",    tone: "amber" },
      { signal: "Similar schools improved 1.8 SSA points with follow-up",  source: "support-quality",    weight: "supporting", tone: "green" },
      { signal: "Mukono is your primary district — same-day round trip",   source: "geography",          weight: "context",    tone: "green" },
    ],
    confidence: "High",
    confidenceWhy: "Deterministic: training was logged, follow-up is missing, the 21-day window is a documented playbook step.",
    costEstimateUgx: COST_HOPE_FOLLOWUP.totalUgx,
    costBreakdown: breakdownToCostLines(COST_HOPE_FOLLOWUP.lines),
    projectedImpact: "Likely to convert the training from one-off to durable. Pattern from 14 comparable follow-ups shows +1.8 SSA points within 60 days.",
    urgency: "ThisWeek",
    decideBy: "2026-05-29",
    priority: 1,
    tone: "red",
    primaryAction: { label: "Add to this week's plan", href: "/plans/new?schoolId=S-HP-1&activityKind=TRAINING_FOLLOW_UP&suggestedBy=decision-engine", intent: "act" },
    secondaryAction: { label: "Reassign to partner",    href: "/decisions/cceo-d-1/reassign" },
    generatedAt: "2026-05-24T06:30:00Z",
    sourceSignals: ["ssa-planning", "support-quality", "geography", "history"],
    triggeredBecause: "Today crosses the 14-day mark since the phonics training — your team's playbook closes the window at 21 days.",
  },
  {
    id: "cceo-d-2",
    role: "CCEO",
    kind: "NextBestAction",
    category: "EvidenceGap",
    headline: "Upload Evidence for 2 visits at Mukono Central — M&E is holding",
    subhead: "Activities are logged but won't count toward your target until evidence lands.",
    subject: { kind: "School", id: "S-MK-1", label: "Mukono Central PS", district: "Mukono" },
    rationale: [
      { signal: "2 visits logged · 0 attachments uploaded",            source: "evidence",        weight: "primary",    tone: "red" },
      { signal: "M&E will return both records on the next sweep",      source: "approval-safety", weight: "supporting", tone: "amber" },
      { signal: "These 2 visits represent 8% of your monthly target",  source: "history",         weight: "context" },
    ],
    confidence: "High",
    urgency: "Today",
    decideBy: "2026-05-24",
    priority: 2,
    tone: "amber",
    primaryAction: { label: "Upload Evidence",  href: "/data-intake?schoolId=S-MK-1", intent: "act" },
    secondaryAction: { label: "View activities", href: "/schools/S-MK-1" },
    generatedAt: "2026-05-24T06:30:00Z",
    sourceSignals: ["evidence", "approval-safety"],
  },
  {
    id: "cceo-d-3",
    role: "CCEO",
    kind: "NextBestAction",
    category: "SchoolIntervention",
    headline: "Skip the visit to Victory Primary — go to Grace Primary instead",
    subhead: "Victory is on track. Grace is overdue, weaker, and closer to your other stops.",
    subject: { kind: "School", id: "S-GP-1", label: "Grace Primary School", district: "Mukono" },
    rationale: [
      { signal: "Grace SSA Literacy: 3/10 — district worst",                source: "ssa-planning",       weight: "primary",    tone: "red" },
      { signal: "Grace last visit: 84 days ago",                            source: "history",            weight: "primary",    tone: "red" },
      { signal: "Victory SSA stable at 7/10 — no degradation signal",       source: "ssa-planning",       weight: "supporting", tone: "green" },
      { signal: "Grace is 8 km from Hope Primary (your morning stop)",      source: "geography",          weight: "context" },
    ],
    confidence: "Medium",
    confidenceWhy: "SSA is a single time-slice; final call belongs to the CCEO who knows community context.",
    costEstimateUgx: COST_GRACE_SWAP.totalUgx,
    costBreakdown: breakdownToCostLines(COST_GRACE_SWAP.lines),
    projectedImpact: "Bring Grace back inside its 90-day cadence and address the literacy gap before the term review.",
    urgency: "ThisWeek",
    priority: 3,
    tone: "amber",
    primaryAction: { label: "Swap on plan",    href: "/my-plan?swap=S-VP-1%E2%86%92S-GP-1", intent: "act" },
    secondaryAction: { label: "Keep original", href: "/decisions/cceo-d-3/decline" },
    generatedAt: "2026-05-24T06:30:00Z",
    sourceSignals: ["ssa-planning", "history", "geography"],
  },
  {
    id: "cceo-d-4",
    role: "CCEO",
    kind: "NextBestAction",
    category: "Approval",
    headline: "Submit Week 2 fund accountability — Week 3 is blocked behind it",
    subhead: "UGX 1.2M disbursed, receipts in your wallet. Submit and Week 3 unlocks automatically.",
    subject: { kind: "Fund", id: "WFR-W2", label: "Week 2 fund slip", amountUgx: 1_200_000 },
    rationale: [
      { signal: "Funds disbursed 8 days ago — accountability is due",     source: "weekly-fund-engine", weight: "primary",    tone: "amber" },
      { signal: "Week 3 fund request is BLOCKED_PRIOR_OUTSTANDING",       source: "weekly-fund-engine", weight: "primary",    tone: "red" },
      { signal: "Receipts available in mobile money app · NR ready",      source: "history",            weight: "context",    tone: "green" },
    ],
    confidence: "High",
    urgency: "Today",
    priority: 4,
    tone: "amber",
    primaryAction: { label: "Submit accountability", href: "/weekly-funds?wfr=WFR-W2", intent: "act" },
    generatedAt: "2026-05-24T06:30:00Z",
    sourceSignals: ["weekly-fund-engine"],
  },
  {
    id: "cceo-d-5",
    role: "CCEO",
    kind: "NextBestAction",
    category: "SchoolIntervention",
    headline: "Plan a 2-day Kitgum cluster trip — 3 schools overdue",
    subhead: "Secondary district. Dinner + accommodation auto-included. Pre-clear with CPL before the week ends.",
    subject: { kind: "District", id: "D-KITGUM", label: "Kitgum cluster (3 schools)" },
    rationale: [
      { signal: "Kitgum Central · Layibi · Pajule all > 90 days no visit", source: "history",   weight: "primary",    tone: "red" },
      { signal: "Kitgum is outside Mukono — secondary district",           source: "geography", weight: "primary",    tone: "amber" },
      { signal: "Same trip closes the gap for 3 schools at once",          source: "geography", weight: "supporting", tone: "green" },
      { signal: "Accommodation auto-included — no separate request needed", source: "geography", weight: "context",    tone: "green" },
    ],
    confidence: "High",
    confidenceWhy: "Cost engine deterministically derives secondary-district rates from your home base (Mukono).",
    costEstimateUgx: COST_KITGUM_CLUSTER.totalUgx,
    costBreakdown: breakdownToCostLines(COST_KITGUM_CLUSTER.lines),
    projectedImpact: "Restore the 90-day cadence for 3 schools in one trip; consolidates travel cost vs. 3 separate days.",
    urgency: "ThisWeek",
    priority: 5,
    tone: "amber",
    primaryAction: { label: "Build cluster trip", href: "/plans/new?cluster=kitgum&schools=S-KT-1,S-KT-2,S-KT-3&days=2", intent: "act" },
    secondaryAction: { label: "Defer one school", href: "/decisions/cceo-d-5/defer" },
    generatedAt: "2026-05-24T06:30:00Z",
    sourceSignals: ["history", "geography"],
    triggeredBecause: "All 3 Kitgum schools crossed the 90-day cadence threshold this week — engine consolidated into one trip to share transport.",
  },
];

// ────────── CPL — Next Best Decisions ──────────
//
// Leadership. Decisions are judgments: rebalance workload, choose between
// budget options, escalate or recognize. Each card surfaces the trade-off
// with the engine's recommendation marked.

const CPL_DECISIONS: Decision[] = [
  {
    id: "cpl-d-1",
    role: "CountryProgramLead",
    kind: "NextBestDecision",
    category: "WorkloadRebalance",
    headline: "Move 8 schools from Sarah Nakato to David Kimani",
    subhead: "Sarah is at 95th-percentile workload. David has capacity. Same district, same cluster.",
    subject: { kind: "Portfolio", id: "PF-SN-1", label: "Sarah Nakato's portfolio" },
    rationale: [
      { signal: "Sarah's Portfolio Complexity: 95th percentile (Overloaded band)", source: "fwi-engine",          weight: "primary",    tone: "red" },
      { signal: "Sarah covers 6 districts · 1,240km travel · 11 hotel trips",      source: "workload-guardrails", weight: "primary",    tone: "red" },
      { signal: "David's Complexity: 38th percentile — has headroom",              source: "fwi-engine",          weight: "primary",    tone: "green" },
      { signal: "8 candidate schools are all in Mukono — David's primary district", source: "geography",          weight: "supporting", tone: "green" },
      { signal: "Sarah's pace is 88% under heavy load — true top performer",       source: "support-quality",     weight: "supporting", tone: "green" },
      { signal: "Predicted post-rebalance: Sarah → 67th, David → 58th percentile", source: "fwi-engine",          weight: "context" },
    ],
    confidence: "High",
    confidenceWhy: "FWI engine's projection has been within ±5 percentile points across the last 11 rebalances.",
    recommendedOwner: {
      name: "David Kimani",
      role: "CCEO",
      reasoning: "Same district. Has driven Mukono cluster meetings already.",
      fairnessAdjusted: true,
    },
    projectedImpact: "Sarah's burnout risk drops from High to Low. David picks up 8 schools that move from At-Risk to On-Track within one quarter based on his prior pattern.",
    urgency: "ThisWeek",
    decideBy: "2026-05-31",
    priority: 1,
    tone: "red",
    primaryAction: { label: "Open rebalance plan", href: "/staff/sarah-nakato?rebalance=true", intent: "review" },
    secondaryAction: { label: "Talk to Sarah first", href: "/messages/sarah-nakato?topic=workload" },
    generatedAt: "2026-05-24T06:30:00Z",
    sourceSignals: ["fwi-engine", "workload-guardrails", "support-quality", "geography"],
    triggeredBecause: "Sarah crossed the 90-day high-workload threshold yesterday. HR is also flagging her in the support watchlist.",
  },
  {
    id: "cpl-d-2",
    role: "CountryProgramLead",
    kind: "NextBestDecision",
    category: "FundReallocation",
    headline: "Fund follow-up visits before new trainings this quarter",
    subhead: "Two ways to spend UGX 4.0M. Engine's pick: follow-up. Higher confidence, lower cost.",
    subject: { kind: "Budget", id: "BUD-Q2", label: "Q2 discretionary envelope" },
    rationale: [
      { signal: "35 schools received training but no follow-up this term",  source: "history",         weight: "primary",    tone: "amber" },
      { signal: "Follow-Up cohort historic outcome: 73% SSA improvement",   source: "support-quality", weight: "primary",    tone: "green" },
      { signal: "New training cohort historic outcome (no follow-up): 31%", source: "support-quality", weight: "primary",    tone: "amber" },
      { signal: "Field capacity for new trainings is at 80% — low headroom", source: "workload-guardrails", weight: "supporting", tone: "amber" },
    ],
    confidence: "High",
    confidenceWhy: "Backed by 3 quarters of comparable cohort outcomes — 42 schools per arm.",
    costEstimateUgx: 2_800_000,
    alternatives: [
      {
        label: "Follow Up 35 trained schools",
        costUgx: 2_800_000,
        expectedImpact: "High",
        projectedOutcome: "26 of 35 schools improve SSA by ≥1 point within 90 days.",
        risk: "Low",
        recommended: true,
        reasoning: "Cheaper, higher historical conversion, capacity already exists.",
      },
      {
        label: "Train 20 new schools",
        costUgx: 4_000_000,
        expectedImpact: "Medium",
        projectedOutcome: "Trainings delivered. SSA improvement depends on whether next quarter has follow-up capacity.",
        risk: "High",
        recommended: false,
        reasoning: "Field capacity at 80% — adding 20 new schools without follow-up plan repeats this term's gap.",
      },
    ],
    projectedImpact: "Convert ~26 trained schools from delivered to improved this quarter. Saves UGX 1.2M for next-quarter cushion.",
    urgency: "ThisMonth",
    decideBy: "2026-05-31",
    priority: 2,
    tone: "amber",
    primaryAction: { label: "Build follow-up plan", href: "/planning?focus=follow-up&q=Q2", intent: "act" },
    secondaryAction: { label: "Defer decision",     href: "/decisions/cpl-d-2/defer" },
    generatedAt: "2026-05-24T06:30:00Z",
    sourceSignals: ["history", "support-quality", "workload-guardrails"],
  },
  {
    id: "cpl-d-3",
    role: "CountryProgramLead",
    kind: "NextBestDecision",
    category: "RiskMitigation",
    headline: "Grace Primary is forecast to stay Critical — intervene this week",
    subhead: "Repeated signals, no follow-up after May 8 training. Without action, expect no movement at term review.",
    subject: { kind: "School", id: "S-GP-1", label: "Grace Primary School", district: "Mukono" },
    rationale: [
      { signal: "Teaching & Learning: 3/10 · Literacy: below district avg",      source: "ssa-planning",       weight: "primary",    tone: "red" },
      { signal: "Last visit 84 days ago — outside the 90-day cadence",          source: "history",            weight: "primary",    tone: "red" },
      { signal: "Assigned CCEO (Sarah Nakato) at 95th-percentile workload",     source: "workload-guardrails", weight: "primary",    tone: "amber" },
      { signal: "Partner LTU has Mukono coverage next week — capacity verified", source: "partner-health",     weight: "supporting", tone: "green" },
      { signal: "M&E verification rate for LTU: 91% (high-value partner)",      source: "partner-health",     weight: "supporting", tone: "green" },
    ],
    confidence: "Medium",
    confidenceWhy: "Forecast based on 11 schools with similar 80+ day gaps. 8 of 11 remained Critical without intervention.",
    recommendedOwner: {
      name: "Partner LTU (Sarah Kanyi)",
      role: "PartnerAdmin",
      reasoning: "Already scheduled in Mukono next week. Stronger partner reporting record than reassigning to another CCEO.",
      fairnessAdjusted: true,
    },
    costEstimateUgx: COST_GRACE_PARTNER.totalUgx,
    costBreakdown: breakdownToCostLines(COST_GRACE_PARTNER.lines),
    projectedImpact: "Move from Critical → At Risk within one term. Comparable interventions converted 5 of 6 similar schools within 60 days.",
    urgency: "ThisWeek",
    decideBy: "2026-05-30",
    priority: 3,
    tone: "red",
    primaryAction: { label: "Assign to Partner LTU", href: "/plans/new?schoolId=S-GP-1&assignTo=partner-ltu&suggestedBy=decision-engine", intent: "act" },
    secondaryAction: { label: "Escalate to CD",      href: "/messages/sarah-okello?topic=grace-primary" },
    generatedAt: "2026-05-24T06:30:00Z",
    sourceSignals: ["ssa-planning", "history", "workload-guardrails", "partner-health"],
  },
  {
    id: "cpl-d-4",
    role: "CountryProgramLead",
    kind: "NextBestAction",
    category: "Approval",
    headline: "5 plans are safe to bulk-approve",
    subhead: "All passed cost, route, fairness, and duplication checks. No issues flagged.",
    subject: { kind: "System", id: "approval-queue", label: "Approval queue" },
    rationale: [
      { signal: "5 of 7 plans classified SafeToApprove",          source: "approval-safety", weight: "primary",    tone: "green" },
      { signal: "Cost settings active · routes valid",            source: "approval-safety", weight: "supporting", tone: "green" },
      { signal: "No workload-bandwidth flags on any assignees",   source: "fwi-engine",      weight: "supporting", tone: "green" },
    ],
    confidence: "High",
    urgency: "Today",
    priority: 4,
    tone: "green",
    primaryAction: { label: "Review and approve", href: "/plans?filter=safe", intent: "approve" },
    secondaryAction: { label: "See full queue",    href: "/plans" },
    generatedAt: "2026-05-24T06:30:00Z",
    sourceSignals: ["approval-safety", "fwi-engine"],
  },
  {
    id: "cpl-d-5",
    role: "CountryProgramLead",
    kind: "NextBestDecision",
    category: "Recognition",
    headline: "Recognize David Kimani — hidden leader signal this month",
    subhead: "Quietly mentored two CCEOs to higher pace. No one has flagged this yet.",
    subject: { kind: "Staff", id: "U-DK-1", label: "David Kimani", role: "CCEO" },
    rationale: [
      { signal: "2 fellow CCEOs improved pace by +12% after pairing with David", source: "support-quality", weight: "primary",    tone: "green" },
      { signal: "David's pace: 96% with moderate load",                         source: "fwi-engine",      weight: "supporting", tone: "green" },
      { signal: "FWI band: HiddenLeader",                                       source: "fwi-engine",      weight: "primary",    tone: "green" },
      { signal: "No formal recognition logged in last 6 months",                source: "history",         weight: "context" },
    ],
    confidence: "Medium",
    confidenceWhy: "Mentorship effect is inferred from pace correlation, not directly observed.",
    urgency: "ThisMonth",
    priority: 5,
    tone: "green",
    primaryAction: { label: "Open recognition note", href: "/messages/david-kimani?template=recognition" },
    secondaryAction: { label: "Add to next debrief",  href: "/program-lead/weekly-report?add=david-kimani" },
    generatedAt: "2026-05-24T06:30:00Z",
    sourceSignals: ["support-quality", "fwi-engine", "history"],
  },
];

// ────────── Headers per role ──────────
//
// Static today; future enhancement can swap for an LLM-generated summary
// from the day's decision set.

function headerForRole(role: EdifyRole, decisionsCount: number) {
  const period = new Date().toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
  switch (role) {
    case "CCEO":
      return {
        greeting: "Good morning.",
        mission: "Walk the schools. Coach the teachers. Log it before sundown.",
        periodLabel: period,
        summary: decisionsCount > 0
          ? `${decisionsCount} decisions for today. Hope Primary's follow-up window closes Friday · Kitgum cluster needs a 2-day plan.`
          : "Nothing critical today. Use the time to catch up on evidence and prep this week's route.",
      };
    case "CountryProgramLead":
      return {
        greeting: "Good morning.",
        mission: "Coach the field. Close the gaps. Multiply the wins.",
        periodLabel: period,
        summary: decisionsCount > 0
          ? `1 staff overloaded · 1 school forecast Critical · 1 budget trade-off open · 5 approvals safe.`
          : "Inbox is empty. Good week.",
      };
    default:
      return {
        greeting: "Good morning.",
        mission: "What decision should you make next?",
        periodLabel: period,
        summary: decisionsCount > 0
          ? `${decisionsCount} decisions waiting on you.`
          : "No decisions need your attention right now.",
      };
  }
}

// ────────── Board assembly ──────────
//
// Pure: role in → DecisionBoard out. UI consumes this directly.

export function decisionBoardFor(role: EdifyRole): DecisionBoard {
  const decisions = decisionsForRole(role);
  const topDecision = decisions[0] ?? null;
  const rest = decisions.slice(1);
  const nextBestActions = rest.filter((d) => d.kind === "NextBestAction");
  const nextBestDecisions = rest.filter((d) => d.kind === "NextBestDecision");

  return {
    role,
    header: headerForRole(role, decisions.length),
    topDecision,
    nextBestActions,
    nextBestDecisions,
    emptyState: decisions.length === 0
      ? {
          headline: "No decisions need your attention.",
          body: "When the engine detects a school risk, an overloaded staff, a fund block, or an evidence gap — it'll land here. Until then, you've earned a quiet morning.",
        }
      : undefined,
  };
}

export function decisionsForRole(role: EdifyRole): Decision[] {
  switch (role) {
    case "CCEO":               return CCEO_DECISIONS;
    case "CountryProgramLead": return CPL_DECISIONS;
    case "Admin":              return CPL_DECISIONS;
    default:                   return [];
  }
}

// Exported for tests + the future engine wiring.
export const ALL_MOCK_DECISIONS: Decision[] = [
  ...CCEO_DECISIONS,
  ...CPL_DECISIONS,
];
