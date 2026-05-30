// Partner Impact Measurement — types + engine + mock.
//
// The core question: did the school improve in the SSA intervention
// area the partner supported? This module captures the baseline SSA,
// the partner activity, the next SSA, and the delta — then classifies
// the result + attributes the improvement.

export type SsaInterventionArea =
  | "Teaching & Learning"
  | "Financial Health"
  | "Christlike Behaviour"
  | "Exposure to the Word of God"
  | "Government Requirements & Compliance"
  | "Leadership"
  | "Education Technology"
  | "Learning Environment";

export type ImpactRating =
  | "significant_decline"
  | "decline"
  | "no_change"
  | "small_improvement"
  | "meaningful_improvement"
  | "strong_improvement";

export type AttributionType =
  | "direct_partner_contribution"
  | "shared_staff_partner_contribution"
  | "partner_follow_up_contribution"
  | "indirect_partner_contribution"
  | "not_attributable";

export type ImpactStatus =
  | "baseline_captured"
  | "partner_support_delivered"
  | "evidence_confirmed"
  | "impact_tracking_eligible"
  | "awaiting_next_ssa"
  | "next_ssa_completed"
  | "improvement_detected"
  | "no_change_detected"
  | "decline_detected"
  | "impact_attributed"
  | "impact_closed";

export type EvidenceStatus = "missing" | "partial" | "complete" | "confirmed_by_cceo" | "verified_by_me";

export type PartnerImpactRecord = {
  id: string;
  partnerId: string;
  partnerName: string;
  schoolId: string;
  schoolName: string;
  district: string;
  subCounty?: string;
  parish?: string;
  activityId: string;
  activityType: string;
  activityDate: string;
  ssaInterventionArea: SsaInterventionArea;
  baselineSsaId: string;
  baselineSsaDate: string;
  baselineScore: number;        // 0-10
  nextSsaId?: string;
  nextSsaDate?: string;
  nextScore?: number;
  scoreChange?: number;
  impactRating?: ImpactRating;
  attributionType?: AttributionType;
  impactWindowStart: string;
  impactWindowEnd: string;
  evidenceStatus: EvidenceStatus;
  impactStatus: ImpactStatus;
  costOfSupport?: number;       // UGX
  costPerImprovementPoint?: number;
  notes?: string;
  // Bundle context: other activities in the impact window so the
  // attribution decision is auditable.
  bundleActivities?: { kind: string; by: string; date: string }[];
};

// ────────── Labels + tones ──────────

export const IMPACT_RATING_LABEL: Record<ImpactRating, string> = {
  significant_decline:    "Significant decline",
  decline:                "Decline",
  no_change:              "No change",
  small_improvement:      "Small improvement",
  meaningful_improvement: "Meaningful improvement",
  strong_improvement:     "Strong improvement",
};

export const ATTRIBUTION_LABEL: Record<AttributionType, string> = {
  direct_partner_contribution:       "Direct partner contribution",
  shared_staff_partner_contribution: "Shared staff + partner",
  partner_follow_up_contribution:    "Partner follow-up",
  indirect_partner_contribution:     "Indirect contribution",
  not_attributable:                  "Not attributable",
};

export const IMPACT_STATUS_LABEL: Record<ImpactStatus, string> = {
  baseline_captured:           "Baseline captured",
  partner_support_delivered:   "Support delivered",
  evidence_confirmed:          "Evidence confirmed",
  impact_tracking_eligible:    "Impact-tracking eligible",
  awaiting_next_ssa:           "Awaiting next SSA",
  next_ssa_completed:          "Next SSA completed",
  improvement_detected:        "Improvement detected",
  no_change_detected:          "No change",
  decline_detected:            "Decline",
  impact_attributed:           "Impact attributed",
  impact_closed:               "Impact closed",
};

// ────────── Engine ──────────

export function classifyImpactRating(change: number): ImpactRating {
  if (change <= -2) return "significant_decline";
  if (change === -1) return "decline";
  if (change === 0)  return "no_change";
  if (change === 1)  return "small_improvement";
  if (change === 2)  return "meaningful_improvement";
  return "strong_improvement";
}

// Recommended next decision per impact rating — surfaced as a banner
// on the impact records list so leadership doesn't have to invent the
// next step every time.
export type ImpactRecommendation = {
  tone: "good" | "warn" | "danger";
  headline: string;
  action: string;
};

export function recommendationFor(record: PartnerImpactRecord): ImpactRecommendation | null {
  if (!record.impactRating) return null;
  switch (record.impactRating) {
    case "strong_improvement":
    case "meaningful_improvement":
      return {
        tone: "good",
        headline: `${record.schoolName} improved ${record.ssaInterventionArea} by ${formatChange(record.scoreChange ?? 0)} points.`,
        action: "Schedule sustainment follow-up and consider similar support for nearby schools.",
      };
    case "small_improvement":
      return {
        tone: "good",
        headline: `${record.schoolName} improved ${record.ssaInterventionArea} by ${formatChange(record.scoreChange ?? 0)} point.`,
        action: "Plan a follow-up visit to reinforce gains.",
      };
    case "no_change":
      return {
        tone: "warn",
        headline: `${record.ssaInterventionArea} stayed at ${record.baselineScore}/10 after partner support.`,
        action: "Schedule CCEO follow-up visit and review partner training quality.",
      };
    case "decline":
    case "significant_decline":
      return {
        tone: "danger",
        headline: `${record.ssaInterventionArea} declined from ${record.baselineScore}/10 to ${record.nextScore}/10.`,
        action: "Escalate to PL. Conduct joint school support review.",
      };
  }
}

export function formatChange(n: number): string {
  if (n > 0) return `+${n}`;
  return String(n);
}

// ────────── Mock data ──────────
//
// 14 records covering improvement / no change / decline /
// awaiting-next-SSA / attribution variants so every chip type renders.

export const partnerImpactRecords: PartnerImpactRecord[] = [
  // Meaningful improvement, direct attribution
  buildRecord({
    id: "IMP-001",
    schoolName: "Hope Primary School", district: "Mukono", subCounty: "Ntenjeru", parish: "Ntenjeru",
    schoolId: "SCH-HOPE",
    activityType: "In-School Training", activityDate: "2026-06-12",
    area: "Teaching & Learning", baselineScore: 4, baselineSsaDate: "2026-03-12",
    nextScore: 6, nextSsaDate: "2026-08-20",
    attribution: "direct_partner_contribution",
    evidence: "verified_by_me",
    cost: 410_000,
    notes: "Partner delivered the primary intervention. No other major Teaching & Learning support in the impact window.",
  }),
  // Strong improvement
  buildRecord({
    id: "IMP-002",
    schoolName: "Grace Primary School", district: "Mukono", subCounty: "Nsumba",
    schoolId: "SCH-GRACE",
    activityType: "Numeracy Coaching", activityDate: "2026-05-15",
    area: "Teaching & Learning", baselineScore: 5, baselineSsaDate: "2026-02-10",
    nextScore: 8, nextSsaDate: "2026-08-12",
    attribution: "direct_partner_contribution",
    evidence: "verified_by_me",
    cost: 295_000,
  }),
  // Shared attribution
  buildRecord({
    id: "IMP-003",
    schoolName: "Kireka Primary School", district: "Mukono", subCounty: "Kireka",
    schoolId: "SCH-KIREKA",
    activityType: "Teacher Training Debrief", activityDate: "2026-04-22",
    area: "Leadership", baselineScore: 5, baselineSsaDate: "2026-01-15",
    nextScore: 7, nextSsaDate: "2026-08-05",
    attribution: "shared_staff_partner_contribution",
    evidence: "verified_by_me",
    cost: 280_000,
    bundle: [
      { kind: "Partner training",  by: "BFEP",  date: "Apr 22, 2026" },
      { kind: "CCEO coaching",     by: "Sarah Nanyongo", date: "May 11, 2026" },
    ],
  }),
  // Strong improvement, sustainment follow-up
  buildRecord({
    id: "IMP-004",
    schoolName: "Namilyango Primary", district: "Mukono", subCounty: "Namilyango",
    schoolId: "SCH-NAMI",
    activityType: "Resource Delivery", activityDate: "2026-05-06",
    area: "Learning Environment", baselineScore: 5, baselineSsaDate: "2026-02-20",
    nextScore: 8, nextSsaDate: "2026-08-15",
    attribution: "partner_follow_up_contribution",
    evidence: "verified_by_me",
    cost: 180_000,
  }),
  // No change
  buildRecord({
    id: "IMP-005",
    schoolName: "Maple Grove Primary", district: "Kayunga", subCounty: "Bbaale",
    schoolId: "SCH-MAPLE",
    activityType: "Literacy Coaching", activityDate: "2026-04-10",
    area: "Teaching & Learning", baselineScore: 4, baselineSsaDate: "2026-01-30",
    nextScore: 4, nextSsaDate: "2026-07-15",
    attribution: "indirect_partner_contribution",
    evidence: "verified_by_me",
    cost: 350_000,
    notes: "No measurable improvement. Review partner training quality and plan CCEO follow-up.",
  }),
  // Decline
  buildRecord({
    id: "IMP-006",
    schoolName: "Galiraaya Primary", district: "Kayunga", subCounty: "Galiraaya",
    schoolId: "SCH-GAL",
    activityType: "SSA Support Visit", activityDate: "2026-03-25",
    area: "Teaching & Learning", baselineScore: 4, baselineSsaDate: "2026-01-12",
    nextScore: 3, nextSsaDate: "2026-07-02",
    attribution: "not_attributable",
    evidence: "verified_by_me",
    cost: 480_000,
    notes: "Decline. Escalating to PL for joint school support review.",
  }),
  // Awaiting next SSA — strong evidence chain but no measurement yet
  buildRecord({
    id: "IMP-007",
    schoolName: "St. Mary's Primary", district: "Kayunga", subCounty: "Kayunga Central",
    schoolId: "SCH-STMARY",
    activityType: "Leadership Support Visit", activityDate: "2026-05-17",
    area: "Leadership", baselineScore: 5, baselineSsaDate: "2026-02-22",
    nextScore: undefined, nextSsaDate: undefined,
    attribution: undefined,
    evidence: "verified_by_me",
    cost: 320_000,
    awaitingWindowEnd: "2026-09-15",
  }),
  // Meaningful improvement — Financial Health
  buildRecord({
    id: "IMP-008",
    schoolName: "Bright Future PS", district: "Mukono", subCounty: "Bukoto",
    schoolId: "SCH-BRIGHT",
    activityType: "Financial Management Support", activityDate: "2026-03-10",
    area: "Financial Health", baselineScore: 5, baselineSsaDate: "2026-01-05",
    nextScore: 7, nextSsaDate: "2026-07-10",
    attribution: "direct_partner_contribution",
    evidence: "verified_by_me",
    cost: 230_000,
  }),
  // Small improvement, Christlike Behaviour
  buildRecord({
    id: "IMP-009",
    schoolName: "Eastview Junior", district: "Mukono", subCounty: "Nakifuma",
    schoolId: "SCH-EAST",
    activityType: "Values & Culture Session", activityDate: "2026-04-02",
    area: "Christlike Behaviour", baselineScore: 7, baselineSsaDate: "2026-01-20",
    nextScore: 8, nextSsaDate: "2026-07-22",
    attribution: "partner_follow_up_contribution",
    evidence: "verified_by_me",
    cost: 150_000,
  }),
  // Awaiting — Compliance
  buildRecord({
    id: "IMP-010",
    schoolName: "Mukono Central PS", district: "Mukono", subCounty: "Mukono Central",
    schoolId: "SCH-MUKONO",
    activityType: "Compliance Support Visit", activityDate: "2026-05-04",
    area: "Government Requirements & Compliance", baselineScore: 6, baselineSsaDate: "2026-02-14",
    nextScore: undefined,
    attribution: undefined,
    evidence: "confirmed_by_cceo",
    cost: 210_000,
    awaitingWindowEnd: "2026-09-04",
  }),
  // EdTech — strong improvement
  buildRecord({
    id: "IMP-011",
    schoolName: "Lakeview Primary", district: "Kayunga", subCounty: "Galiraaya",
    schoolId: "SCH-LAKE",
    activityType: "EdTech Training", activityDate: "2026-03-18",
    area: "Education Technology", baselineScore: 4, baselineSsaDate: "2026-01-10",
    nextScore: 7, nextSsaDate: "2026-07-30",
    attribution: "direct_partner_contribution",
    evidence: "verified_by_me",
    cost: 380_000,
  }),
  // Bible integration — meaningful
  buildRecord({
    id: "IMP-012",
    schoolName: "Eden Foundation School", district: "Mukono", subCounty: "Nakifuma",
    schoolId: "SCH-EDEN",
    activityType: "Bible Integration Support", activityDate: "2026-04-15",
    area: "Exposure to the Word of God", baselineScore: 6, baselineSsaDate: "2026-01-25",
    nextScore: 8, nextSsaDate: "2026-07-26",
    attribution: "direct_partner_contribution",
    evidence: "verified_by_me",
    cost: 165_000,
  }),
  // Hilltop — no change, T&L
  buildRecord({
    id: "IMP-013",
    schoolName: "Hilltop Basic School", district: "Mukono", subCounty: "Kireka",
    schoolId: "SCH-HILL",
    activityType: "Phonics Training", activityDate: "2026-04-08",
    area: "Teaching & Learning", baselineScore: 4, baselineSsaDate: "2026-01-22",
    nextScore: 4, nextSsaDate: "2026-07-18",
    attribution: "indirect_partner_contribution",
    evidence: "verified_by_me",
    cost: 410_000,
    notes: "Stagnation. CCEO follow-up scheduled to diagnose root cause.",
  }),
  // Sunrise — decline mild
  buildRecord({
    id: "IMP-014",
    schoolName: "Sunrise Junior School", district: "Mukono", subCounty: "Mukono Central",
    schoolId: "SCH-SUNRISE",
    activityType: "Reading Fluency Coaching", activityDate: "2026-03-22",
    area: "Teaching & Learning", baselineScore: 5, baselineSsaDate: "2026-01-08",
    nextScore: 4, nextSsaDate: "2026-07-08",
    attribution: "not_attributable",
    evidence: "verified_by_me",
    cost: 290_000,
    notes: "Decline by 1 point. Multiple external factors flagged — leadership transition mid-window.",
  }),
];

// ────────── Helpers ──────────

type BuildInput = {
  id: string;
  schoolId: string;
  schoolName: string;
  district: string;
  subCounty?: string;
  parish?: string;
  activityType: string;
  activityDate: string;
  area: SsaInterventionArea;
  baselineScore: number;
  baselineSsaDate: string;
  nextScore?: number;
  nextSsaDate?: string;
  attribution?: AttributionType;
  evidence: EvidenceStatus;
  cost?: number;
  notes?: string;
  bundle?: { kind: string; by: string; date: string }[];
  awaitingWindowEnd?: string;
};

function buildRecord(i: BuildInput): PartnerImpactRecord {
  const scoreChange = i.nextScore != null ? i.nextScore - i.baselineScore : undefined;
  const rating = scoreChange != null ? classifyImpactRating(scoreChange) : undefined;
  const status: ImpactStatus = scoreChange == null
    ? "awaiting_next_ssa"
    : scoreChange > 0
      ? "improvement_detected"
      : scoreChange < 0
        ? "decline_detected"
        : "no_change_detected";

  const activityDate = new Date(i.activityDate);
  const start = new Date(activityDate);
  start.setDate(start.getDate() + 30);
  const end = new Date(activityDate);
  end.setDate(end.getDate() + 120);

  const costPerPoint =
    i.cost != null && scoreChange != null && scoreChange > 0
      ? Math.round(i.cost / scoreChange)
      : undefined;

  return {
    id: i.id,
    partnerId: "P-BFEP",
    partnerName: "Bright Future Education Partners",
    schoolId: i.schoolId,
    schoolName: i.schoolName,
    district: i.district,
    subCounty: i.subCounty,
    parish: i.parish,
    activityId: `${i.id}-ACT`,
    activityType: i.activityType,
    activityDate: i.activityDate,
    ssaInterventionArea: i.area,
    baselineSsaId: `${i.id}-BSL`,
    baselineSsaDate: i.baselineSsaDate,
    baselineScore: i.baselineScore,
    nextSsaId: i.nextSsaDate ? `${i.id}-NXT` : undefined,
    nextSsaDate: i.nextSsaDate,
    nextScore: i.nextScore,
    scoreChange,
    impactRating: rating,
    attributionType: i.attribution,
    impactWindowStart: i.awaitingWindowEnd
      ? i.activityDate
      : start.toISOString().slice(0, 10),
    impactWindowEnd: i.awaitingWindowEnd ?? end.toISOString().slice(0, 10),
    evidenceStatus: i.evidence,
    impactStatus: status,
    costOfSupport: i.cost,
    costPerImprovementPoint: costPerPoint,
    notes: i.notes,
    bundleActivities: i.bundle,
  };
}

// ────────── Aggregates ──────────

export type ImpactSummary = {
  schoolsSupported: number;
  schoolsWithNextSsa: number;
  schoolsImproved: number;
  schoolsNoChange: number;
  schoolsDeclined: number;
  schoolsAwaiting: number;
  avgChange: number;        // across schools with a next SSA
  strongImprovementCount: number;
  movedBandUpCount: number; // baseline < 6 → next ≥ 6
};

export function summarise(records: PartnerImpactRecord[]): ImpactSummary {
  const measured = records.filter((r) => r.scoreChange != null);
  const improved = measured.filter((r) => (r.scoreChange ?? 0) > 0).length;
  const decline = measured.filter((r) => (r.scoreChange ?? 0) < 0).length;
  const noChange = measured.filter((r) => (r.scoreChange ?? 0) === 0).length;
  const awaiting = records.filter((r) => r.scoreChange == null).length;
  const avg = measured.length === 0
    ? 0
    : Math.round((measured.reduce((s, r) => s + (r.scoreChange ?? 0), 0) / measured.length) * 10) / 10;
  const strong = measured.filter((r) => r.impactRating === "strong_improvement").length;
  const bandUp = measured.filter((r) =>
    r.baselineScore < 6 && (r.nextScore ?? 0) >= 6,
  ).length;
  return {
    schoolsSupported: records.length,
    schoolsWithNextSsa: measured.length,
    schoolsImproved: improved,
    schoolsNoChange: noChange,
    schoolsDeclined: decline,
    schoolsAwaiting: awaiting,
    avgChange: avg,
    strongImprovementCount: strong,
    movedBandUpCount: bandUp,
  };
}

export type ByAreaRow = {
  area: SsaInterventionArea;
  supported: number;
  measured: number;
  avgChange: number;
  improved: number;
  declined: number;
};

export function summariseByArea(records: PartnerImpactRecord[]): ByAreaRow[] {
  const map = new Map<SsaInterventionArea, PartnerImpactRecord[]>();
  for (const r of records) {
    const arr = map.get(r.ssaInterventionArea) ?? [];
    arr.push(r);
    map.set(r.ssaInterventionArea, arr);
  }
  const rows: ByAreaRow[] = [];
  for (const [area, arr] of map.entries()) {
    const measured = arr.filter((r) => r.scoreChange != null);
    const avg = measured.length === 0
      ? 0
      : Math.round((measured.reduce((s, r) => s + (r.scoreChange ?? 0), 0) / measured.length) * 10) / 10;
    rows.push({
      area,
      supported: arr.length,
      measured: measured.length,
      avgChange: avg,
      improved: measured.filter((r) => (r.scoreChange ?? 0) > 0).length,
      declined: measured.filter((r) => (r.scoreChange ?? 0) < 0).length,
    });
  }
  return rows.sort((a, b) => b.avgChange - a.avgChange);
}
