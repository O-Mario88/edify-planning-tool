// School activity & investment mock — drives the
// SchoolActivityProfileDrawer ("View School"). One source of truth
// for every activity tied to a school: visits (staff + partner),
// trainings, cluster activities, SSA, coaching, follow-ups,
// classroom observations, resource delivery, projects.
//
// Each item carries cost + evidence + verification + payment status
// so the drawer can aggregate into the four summaries the spec asks
// for (totals, cost breakdown, evidence health, ssa snapshot) without
// needing a server round-trip per tab.
//
// Pure client-safe module. Salesforce migration swaps `rawActivities`
// for a fetcher; every helper below works against the same shape.

import { historyFor, snapshotFor, statusFor } from "@/lib/planning/ssa-performance-mock";

// ────────── Types ──────────

export type SchoolActivityType =
  | "staff_visit"
  | "partner_visit"
  | "training"
  | "cluster_meeting"
  | "school_improvement_training"
  | "ssa"
  | "coaching_visit"
  | "follow_up_visit"
  | "classroom_observation"
  | "resource_delivery"
  | "project"
  | "other";

export type DeliveredByRole = "CCEO" | "PL" | "IA" | "Partner" | "Staff" | "Admin";

export type EvidenceStatus =
  | "not_required"
  | "missing"
  | "partial"
  | "complete"
  | "returned"
  | "verified";

export type VerificationStatus =
  | "not_submitted"
  | "awaiting_review"
  | "verified"
  | "rejected"
  | "counted";

export type PaymentStatus =
  | "not_applicable"
  | "projected"
  | "awaiting_cceo_confirmation"
  | "awaiting_pl_approval"
  | "sent_to_accountant"
  | "paid_cleared";

export type CostSource =
  | "staff_cost"
  | "partner_payment"
  | "training_cost"
  | "cluster_allocated_cost"
  | "manual_project_cost";

export type SchoolActivityTimelineItem = {
  id:                       string;
  schoolId:                 string;
  activityType:             SchoolActivityType;
  title:                    string;
  date:                     string;  // ISO yyyy-mm-dd
  operationalCycle:         string;  // "FY2027"
  deliveredByName:          string;
  deliveredByRole:          DeliveredByRole;
  partnerName?:             string;
  staffMonitorName?:        string;
  purpose?:                 string;
  ssaInterventionAddressed?: string;
  cost:                     number;  // UGX
  costSource:               CostSource;
  /** True when the cost is the school's share of a multi-school
   *  activity. Used to show "(allocated)" in the cost cell. */
  costAllocated?:           boolean;
  /** Original total of the multi-school activity, when costAllocated. */
  costAllocationTotal?:     number;
  costAllocationSchoolCount?: number;
  evidenceStatus:           EvidenceStatus;
  verificationStatus:       VerificationStatus;
  paymentStatus?:           PaymentStatus;
  nextAction?:              string;
};

export type SchoolCategory = "client" | "core" | "other";

export type SchoolActivityInvestmentSummary = {
  schoolId:          string;
  schoolName:        string;
  district:          string;
  subCounty?:        string;
  parish?:           string;
  clusterName?:      string;
  schoolCategory:    SchoolCategory;
  operationalCycle:  string;
  totals: {
    totalActivities:    number;
    totalVisits:        number;
    staffVisits:        number;
    partnerVisits:      number;
    trainings:          number;
    clusterActivities:  number;
    ssaCompleted:       number;
    totalSpent:         number;
  };
  costBreakdown: {
    staffVisitCost:        number;
    partnerVisitCost:      number;
    trainingCost:          number;
    clusterAllocatedCost:  number;
    ssaCost:               number;
    projectCost:           number;
    otherCost:             number;
    totalSpent:            number;
  };
  activityBreakdown: {
    activityType: string;
    count:        number;
    cost:         number;
    lastDone?:    string;
  }[];
  /** Already filtered to the requested scope (cycle vs all-time). */
  timeline:        SchoolActivityTimelineItem[];
  evidenceSummary: {
    complete:                   number;
    missing:                    number;
    awaitingCceoConfirmation:   number;
    verifiedByME:               number;
    returnedForCorrection:      number;
  };
  ssaSummary?: {
    latestSsaDate:        string;
    averageScore:         number;
    weakestIntervention:  string;
    weakestScore:         number;
    strongestIntervention: string;
    strongestScore:       number;
    changeFromPrevious?:  number;
  };
  nextRecommendedAction?: {
    title:    string;
    reason:   string;
    ctaLabel: string;
    href?:    string;
    /** When set, the drawer routes the CTA through its onAction prop
     *  instead of a link. Matches SchoolGapAction so the parent can
     *  re-use existing handlers. */
    action?:  "schedule_ssa" | "schedule_support_visit" | "schedule_training" | "schedule_coaching" | "view_ssa";
  };
  /** Roll-up of who supported the school — staff vs partner. */
  contributors: {
    staff:   { name: string; visits: number; trainings: number; cost: number; lastDate?: string }[];
    partner: { name: string; visits: number; trainings: number; cost: number; lastDate?: string; paymentStatusHint?: PaymentStatus }[];
  };
};

// ────────── Activity-type categorisation helpers ──────────

const VISIT_TYPES: SchoolActivityType[] = [
  "staff_visit", "partner_visit", "coaching_visit", "follow_up_visit", "classroom_observation",
];
const TRAINING_TYPES: SchoolActivityType[] = ["training", "school_improvement_training"];
const CLUSTER_TYPES: SchoolActivityType[]  = ["cluster_meeting"];

export const ACTIVITY_TYPE_LABEL: Record<SchoolActivityType, string> = {
  staff_visit:                 "Staff visit",
  partner_visit:               "Partner visit",
  training:                    "Training",
  cluster_meeting:             "Cluster meeting",
  school_improvement_training: "School Improvement Training",
  ssa:                         "SSA",
  coaching_visit:              "Coaching visit",
  follow_up_visit:             "Follow-Up visit",
  classroom_observation:       "Classroom observation",
  resource_delivery:           "Resource delivery",
  project:                     "Project",
  other:                       "Other",
};

export function isVisit(type: SchoolActivityType): boolean {
  return VISIT_TYPES.includes(type);
}
export function isStaffVisit(item: SchoolActivityTimelineItem): boolean {
  return isVisit(item.activityType) && item.deliveredByRole !== "Partner";
}
export function isPartnerActivity(item: SchoolActivityTimelineItem): boolean {
  return item.deliveredByRole === "Partner";
}
export function isTraining(type: SchoolActivityType): boolean {
  return TRAINING_TYPES.includes(type);
}
export function isClusterActivity(type: SchoolActivityType): boolean {
  return CLUSTER_TYPES.includes(type);
}

// ────────── Operational cycle ──────────

/** Oct 1 → Sep 30 cycle. ENGINE_TODAY anchors to 2027-06 for the mock
 *  data; production wires this to the real clock. */
export const ENGINE_TODAY_ISO = "2027-06-30";
export const CURRENT_CYCLE = "FY2027";

function isoToDate(iso: string): Date { return new Date(iso); }

/**
 * Test whether an ISO date falls within the *current* operational
 * cycle anchored to ENGINE_TODAY_ISO. Used by the cycle-vs-all-time
 * toggle in the drawer.
 */
export function isInCurrentCycle(iso: string): boolean {
  const today = isoToDate(ENGINE_TODAY_ISO);
  const start = today.getMonth() >= 9
    ? new Date(today.getFullYear(),     9, 1)
    : new Date(today.getFullYear() - 1, 9, 1);
  const end = new Date(start.getFullYear() + 1, 8, 30);
  const d = isoToDate(iso);
  return d >= start && d <= end;
}

// ────────── Summary builder ──────────

export type SummaryScope = "current_cycle" | "all_time";

export function buildSchoolActivitySummary(
  school: {
    schoolId:        string;
    schoolName:      string;
    district:        string;
    subCounty?:      string;
    parish?:         string;
    clusterName?:    string;
    schoolCategory?: SchoolCategory;
  },
  scope: SummaryScope = "current_cycle",
): SchoolActivityInvestmentSummary {
  const raw = rawActivities.filter((a) => a.schoolId === school.schoolId);
  const scoped = scope === "current_cycle" ? raw.filter((a) => isInCurrentCycle(a.date)) : raw;

  // Totals.
  const totalVisits   = scoped.filter((a) => isVisit(a.activityType)).length;
  const staffVisits   = scoped.filter(isStaffVisit).length;
  const partnerVisits = scoped.filter((a) => isVisit(a.activityType) && isPartnerActivity(a)).length;
  const trainings     = scoped.filter((a) => isTraining(a.activityType)).length;
  const clusterCount  = scoped.filter((a) => isClusterActivity(a.activityType)).length;
  const ssaCompleted  = scoped.filter((a) => a.activityType === "ssa").length;
  const totalSpent    = scoped.reduce((sum, a) => sum + a.cost, 0);

  // Cost breakdown — split by costSource so the drawer's "Costs" tab
  // matches the line items the planner actually paid for.
  const sumWhere = (pred: (a: SchoolActivityTimelineItem) => boolean) =>
    scoped.filter(pred).reduce((sum, a) => sum + a.cost, 0);
  const costBreakdown = {
    staffVisitCost:        sumWhere((a) => isStaffVisit(a) && a.costSource === "staff_cost"),
    partnerVisitCost:      sumWhere((a) => isPartnerActivity(a) && a.costSource === "partner_payment"),
    trainingCost:          sumWhere((a) => isTraining(a.activityType) && a.costSource === "training_cost"),
    clusterAllocatedCost:  sumWhere((a) => a.costSource === "cluster_allocated_cost"),
    ssaCost:               sumWhere((a) => a.activityType === "ssa"),
    projectCost:           sumWhere((a) => a.costSource === "manual_project_cost"),
    otherCost:             sumWhere((a) => a.activityType === "other" || a.activityType === "resource_delivery"),
    totalSpent,
  };

  // Activity breakdown table.
  const byType = new Map<SchoolActivityType, { count: number; cost: number; lastDone?: string }>();
  for (const a of scoped) {
    const row = byType.get(a.activityType) ?? { count: 0, cost: 0 };
    row.count += 1;
    row.cost  += a.cost;
    if (!row.lastDone || a.date > row.lastDone) row.lastDone = a.date;
    byType.set(a.activityType, row);
  }
  const activityBreakdown = Array.from(byType.entries())
    .map(([t, v]) => ({ activityType: ACTIVITY_TYPE_LABEL[t], count: v.count, cost: v.cost, lastDone: v.lastDone }))
    .sort((a, b) => b.cost - a.cost);

  // Evidence summary.
  const evidenceSummary = {
    complete:                   scoped.filter((a) => a.evidenceStatus === "complete" || a.evidenceStatus === "verified").length,
    missing:                    scoped.filter((a) => a.evidenceStatus === "missing" || a.evidenceStatus === "partial").length,
    awaitingCceoConfirmation:   scoped.filter((a) => a.verificationStatus === "awaiting_review").length,
    verifiedByME:               scoped.filter((a) => a.verificationStatus === "verified" || a.verificationStatus === "counted").length,
    returnedForCorrection:      scoped.filter((a) => a.evidenceStatus === "returned" || a.verificationStatus === "rejected").length,
  };

  // SSA summary — pulls from SSA performance mock so the View School
  // drawer and View SSA drawer stay perfectly in sync.
  const history = historyFor(school.schoolId);
  const current = history[0];
  const previous = history[1];
  let ssaSummary: SchoolActivityInvestmentSummary["ssaSummary"];
  if (current) {
    const snap = snapshotFor(current);
    ssaSummary = {
      latestSsaDate:         current.ssaDate,
      averageScore:          current.averageScore,
      weakestIntervention:   snap.weakest.intervention,
      weakestScore:          snap.weakest.score,
      strongestIntervention: snap.best.intervention,
      strongestScore:        snap.best.score,
      changeFromPrevious:    previous ? round1(current.averageScore - previous.averageScore) : undefined,
    };
  }

  // Contributors — group by deliveredByName.
  const staffMap   = new Map<string, { visits: number; trainings: number; cost: number; lastDate?: string }>();
  const partnerMap = new Map<string, { visits: number; trainings: number; cost: number; lastDate?: string; paymentStatusHint?: PaymentStatus }>();
  for (const a of scoped) {
    const isStaff = !isPartnerActivity(a);
    const m  = isStaff ? staffMap : partnerMap;
    const k  = isStaff ? a.deliveredByName : (a.partnerName ?? a.deliveredByName);
    const row = m.get(k) ?? { visits: 0, trainings: 0, cost: 0 };
    if (isVisit(a.activityType))    row.visits    += 1;
    if (isTraining(a.activityType)) row.trainings += 1;
    row.cost += a.cost;
    if (!row.lastDate || a.date > row.lastDate) row.lastDate = a.date;
    if (!isStaff && a.paymentStatus && a.paymentStatus !== "not_applicable") {
      (row as { paymentStatusHint?: PaymentStatus }).paymentStatusHint = a.paymentStatus;
    }
    m.set(k, row);
  }
  const contributors = {
    staff:   Array.from(staffMap.entries()).map(([name, v]) => ({ name, ...v })).sort((a, b) => b.cost - a.cost),
    partner: Array.from(partnerMap.entries()).map(([name, v]) => ({ name, ...v })).sort((a, b) => b.cost - a.cost),
  };

  // Next recommended action — guarded by SSA completion. Without a
  // current-cycle SSA, planning stays locked.
  const ssaComplete = !!current;
  let nextRecommendedAction: SchoolActivityInvestmentSummary["nextRecommendedAction"];
  if (!ssaComplete) {
    nextRecommendedAction = {
      title:    "Complete current-cycle SSA",
      reason:   "This school has historical activity, but no current-cycle SSA. Planning remains locked until SSA is completed.",
      ctaLabel: "Schedule SSA",
      action:   "schedule_ssa",
    };
  } else if (current) {
    const weak = snapshotFor(current).weakest;
    nextRecommendedAction = {
      title:    `Schedule support visit focused on ${weak.intervention}.`,
      reason:   `${weak.intervention} remains the weakest SSA intervention at ${weak.score}/10. Schedule the next visit to keep the support cadence in cycle.`,
      ctaLabel: "Schedule support visit",
      action:   "schedule_support_visit",
    };
  }

  return {
    schoolId:        school.schoolId,
    schoolName:      school.schoolName,
    district:        school.district,
    subCounty:       school.subCounty,
    parish:          school.parish,
    clusterName:     school.clusterName,
    schoolCategory:  school.schoolCategory ?? "core",
    operationalCycle: CURRENT_CYCLE,
    totals: {
      totalActivities: scoped.length,
      totalVisits, staffVisits, partnerVisits, trainings,
      clusterActivities: clusterCount,
      ssaCompleted,
      totalSpent,
    },
    costBreakdown,
    activityBreakdown,
    timeline: [...scoped].sort((a, b) => b.date.localeCompare(a.date)),
    evidenceSummary,
    ssaSummary,
    nextRecommendedAction,
    contributors,
  };
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

// ────────── Status display tone (shared helper) ──────────

export const EVIDENCE_LABEL: Record<EvidenceStatus, string> = {
  not_required: "Not required",
  missing:      "Missing",
  partial:      "Partial",
  complete:     "Complete",
  returned:     "Returned",
  verified:     "Verified",
};
export const VERIFICATION_LABEL: Record<VerificationStatus, string> = {
  not_submitted:    "Not submitted",
  awaiting_review:  "Awaiting CCEO review",
  verified:         "Verified",
  rejected:         "Rejected",
  counted:          "Counted",
};
export const PAYMENT_LABEL: Record<PaymentStatus, string> = {
  not_applicable:              "N/A",
  projected:                   "Projected",
  awaiting_cceo_confirmation:  "Awaiting CCEO confirmation",
  awaiting_pl_approval:        "Awaiting PL approval",
  sent_to_accountant:          "Sent to accountant",
  paid_cleared:                "Paid · cleared",
};

// Re-export statusFor so the drawer can colour SSA badges without
// having to import from yet another module.
export { statusFor as ssaStatusFor };

// ────────── Raw mock activities ──────────
//
// Hand-tuned per school. Schools with rich SSA history get rich
// activity history too (so the drawer renders meaningfully); locked
// schools have an SSA-attempt + nothing else.
//
// Date ordering: ENGINE_TODAY_ISO = 2027-06-30 → current cycle is
// 2026-10-01 → 2027-09-30. Prior-cycle items are dated 2026-04 / 2025-12
// etc. so the cycle-toggle has something to switch between.

const rawActivities: SchoolActivityTimelineItem[] = [
  // ============================================================
  // GAP-NSSA-1 — locked, no SSA done. Only an SSA attempt this cycle.
  // ============================================================
  {
    id: "ACT-NSSA1-1", schoolId: "GAP-NSSA-1",
    activityType: "ssa", title: "SSA scheduling visit",
    date: "2027-05-22", operationalCycle: "FY2027",
    deliveredByName: "CCEO Sarah Lamunu", deliveredByRole: "CCEO",
    purpose: "Pre-SSA coordination — head teacher unavailable, rescheduled",
    cost: 80000, costSource: "staff_cost",
    evidenceStatus: "partial", verificationStatus: "awaiting_review",
  },

  // ============================================================
  // GAP-NTR-1 — single SSA + a couple of activities
  // ============================================================
  {
    id: "ACT-NTR1-1", schoolId: "GAP-NTR-1",
    activityType: "ssa", title: "SSA completion visit",
    date: "2027-06-12", operationalCycle: "FY2027",
    deliveredByName: "CCEO Sarah Lamunu", deliveredByRole: "CCEO",
    purpose: "Complete current-cycle SSA across 8 intervention areas",
    cost: 280000, costSource: "staff_cost",
    evidenceStatus: "complete", verificationStatus: "verified",
  },
  {
    id: "ACT-NTR1-2", schoolId: "GAP-NTR-1",
    activityType: "staff_visit", title: "Initial Core Visit",
    date: "2027-04-10", operationalCycle: "FY2027",
    deliveredByName: "CCEO Sarah Lamunu", deliveredByRole: "CCEO",
    purpose: "Onboarding, leadership orientation",
    ssaInterventionAddressed: "Leadership",
    cost: 310000, costSource: "staff_cost",
    evidenceStatus: "complete", verificationStatus: "verified",
  },

  // ============================================================
  // GAP-NTR-2 — Hope Primary School (rich history, drawer hero)
  // ============================================================
  {
    id: "ACT-NTR2-1", schoolId: "GAP-NTR-2",
    activityType: "ssa", title: "SSA completion visit",
    date: "2027-06-08", operationalCycle: "FY2027",
    deliveredByName: "CCEO Sarah Lamunu", deliveredByRole: "CCEO",
    purpose: "Complete current-cycle SSA",
    cost: 280000, costSource: "staff_cost",
    evidenceStatus: "complete", verificationStatus: "verified",
  },
  {
    id: "ACT-NTR2-2", schoolId: "GAP-NTR-2",
    activityType: "partner_visit", title: "Partner Follow-Up Visit",
    date: "2027-06-20", operationalCycle: "FY2027",
    deliveredByName: "Literacy Training Uganda", deliveredByRole: "Partner",
    partnerName: "Literacy Training Uganda",
    staffMonitorName: "CCEO Sarah Lamunu",
    purpose: "Follow Up after phonics training delivered last month",
    ssaInterventionAddressed: "Teaching & Learning",
    cost: 40000, costSource: "partner_payment",
    evidenceStatus: "complete", verificationStatus: "awaiting_review",
    paymentStatus: "awaiting_pl_approval",
    nextAction: "Schedule classroom observation in 30 days.",
  },
  {
    id: "ACT-NTR2-3", schoolId: "GAP-NTR-2",
    activityType: "school_improvement_training", title: "Teaching & Learning Improvement Training",
    date: "2027-05-24", operationalCycle: "FY2027",
    deliveredByName: "Literacy Training Uganda", deliveredByRole: "Partner",
    partnerName: "Literacy Training Uganda",
    staffMonitorName: "CCEO Sarah Lamunu",
    purpose: "Phonics-first reading methodology for P1-P3 teachers",
    ssaInterventionAddressed: "Teaching & Learning",
    cost: 950000, costSource: "training_cost",
    evidenceStatus: "complete", verificationStatus: "verified",
    paymentStatus: "paid_cleared",
  },
  {
    id: "ACT-NTR2-4", schoolId: "GAP-NTR-2",
    activityType: "cluster_meeting", title: "Pajimo Cluster · 2nd Meeting",
    date: "2027-05-12", operationalCycle: "FY2027",
    deliveredByName: "CCEO Sarah Lamunu", deliveredByRole: "CCEO",
    purpose: "Share school improvement plan progress",
    cost: 100000, costSource: "cluster_allocated_cost",
    costAllocated: true, costAllocationTotal: 800000, costAllocationSchoolCount: 8,
    evidenceStatus: "complete", verificationStatus: "verified",
  },
  {
    id: "ACT-NTR2-5", schoolId: "GAP-NTR-2",
    activityType: "staff_visit", title: "Leadership Support Visit",
    date: "2027-05-05", operationalCycle: "FY2027",
    deliveredByName: "CCEO Sarah Lamunu", deliveredByRole: "CCEO",
    purpose: "Support leadership routines after SSA score of 5/10",
    ssaInterventionAddressed: "Leadership",
    cost: 310000, costSource: "staff_cost",
    evidenceStatus: "complete", verificationStatus: "verified",
  },
  {
    id: "ACT-NTR2-6", schoolId: "GAP-NTR-2",
    activityType: "coaching_visit", title: "Classroom Coaching",
    date: "2027-04-18", operationalCycle: "FY2027",
    deliveredByName: "Literacy Training Uganda", deliveredByRole: "Partner",
    partnerName: "Literacy Training Uganda",
    staffMonitorName: "CCEO Sarah Lamunu",
    purpose: "P3 reading lesson observation + co-planning",
    ssaInterventionAddressed: "Teaching & Learning",
    cost: 90000, costSource: "partner_payment",
    evidenceStatus: "complete", verificationStatus: "verified",
    paymentStatus: "paid_cleared",
  },
  {
    id: "ACT-NTR2-7", schoolId: "GAP-NTR-2",
    activityType: "resource_delivery", title: "Reading Cards Pack Delivery",
    date: "2027-03-22", operationalCycle: "FY2027",
    deliveredByName: "Literacy Training Uganda", deliveredByRole: "Partner",
    partnerName: "Literacy Training Uganda",
    purpose: "200 phonics cards delivered for P1-P3",
    cost: 180000, costSource: "manual_project_cost",
    evidenceStatus: "complete", verificationStatus: "verified",
    paymentStatus: "paid_cleared",
  },
  {
    id: "ACT-NTR2-8", schoolId: "GAP-NTR-2",
    activityType: "cluster_meeting", title: "Pajimo Cluster · 1st Meeting",
    date: "2027-03-10", operationalCycle: "FY2027",
    deliveredByName: "CCEO Sarah Lamunu", deliveredByRole: "CCEO",
    purpose: "Cluster kick-off, agree on shared SIP priorities",
    cost: 100000, costSource: "cluster_allocated_cost",
    costAllocated: true, costAllocationTotal: 800000, costAllocationSchoolCount: 8,
    evidenceStatus: "complete", verificationStatus: "verified",
  },
  // ── Prior cycle (FY2026) — visible only in All-Time view ──
  {
    id: "ACT-NTR2-P1", schoolId: "GAP-NTR-2",
    activityType: "ssa", title: "FY2026 SSA",
    date: "2026-05-18", operationalCycle: "FY2026",
    deliveredByName: "IA James Otto", deliveredByRole: "IA",
    purpose: "FY2026 baseline SSA",
    cost: 240000, costSource: "staff_cost",
    evidenceStatus: "verified", verificationStatus: "counted",
  },
  {
    id: "ACT-NTR2-P2", schoolId: "GAP-NTR-2",
    activityType: "school_improvement_training", title: "Leadership Best Practice Training",
    date: "2026-08-04", operationalCycle: "FY2026",
    deliveredByName: "Bright Future Education Partners", deliveredByRole: "Partner",
    partnerName: "Bright Future Education Partners",
    staffMonitorName: "PL Mary Aciro",
    purpose: "Head teacher leadership routines",
    ssaInterventionAddressed: "Leadership",
    cost: 880000, costSource: "training_cost",
    evidenceStatus: "verified", verificationStatus: "counted",
    paymentStatus: "paid_cleared",
  },

  // ============================================================
  // GAP-NTR-3 — moderate history
  // ============================================================
  {
    id: "ACT-NTR3-1", schoolId: "GAP-NTR-3",
    activityType: "ssa", title: "SSA completion visit",
    date: "2027-05-30", operationalCycle: "FY2027",
    deliveredByName: "PL Mary Aciro", deliveredByRole: "PL",
    purpose: "Complete current-cycle SSA",
    cost: 280000, costSource: "staff_cost",
    evidenceStatus: "complete", verificationStatus: "verified",
  },
  {
    id: "ACT-NTR3-2", schoolId: "GAP-NTR-3",
    activityType: "staff_visit", title: "Initial Support Visit",
    date: "2027-04-08", operationalCycle: "FY2027",
    deliveredByName: "CCEO Sarah Lamunu", deliveredByRole: "CCEO",
    purpose: "Leadership baseline visit",
    ssaInterventionAddressed: "Leadership",
    cost: 310000, costSource: "staff_cost",
    evidenceStatus: "complete", verificationStatus: "awaiting_review",
  },
  {
    id: "ACT-NTR3-3", schoolId: "GAP-NTR-3",
    activityType: "follow_up_visit", title: "Leadership Follow-Up",
    date: "2027-05-20", operationalCycle: "FY2027",
    deliveredByName: "CCEO Sarah Lamunu", deliveredByRole: "CCEO",
    purpose: "Check on leadership routines and morning briefings",
    ssaInterventionAddressed: "Leadership",
    cost: 130000, costSource: "staff_cost",
    evidenceStatus: "partial", verificationStatus: "awaiting_review",
  },

  // ============================================================
  // GAP-NTR-4 — strong history, 3-year SSA series
  // ============================================================
  {
    id: "ACT-NTR4-1", schoolId: "GAP-NTR-4",
    activityType: "ssa", title: "FY2027 SSA",
    date: "2027-06-02", operationalCycle: "FY2027",
    deliveredByName: "CCEO Sarah Lamunu", deliveredByRole: "CCEO",
    purpose: "Complete current-cycle SSA",
    cost: 280000, costSource: "staff_cost",
    evidenceStatus: "complete", verificationStatus: "verified",
  },
  {
    id: "ACT-NTR4-2", schoolId: "GAP-NTR-4",
    activityType: "cluster_meeting", title: "Kitgum Cluster · 1st Meeting",
    date: "2027-04-22", operationalCycle: "FY2027",
    deliveredByName: "CCEO Sarah Lamunu", deliveredByRole: "CCEO",
    cost: 100000, costSource: "cluster_allocated_cost",
    costAllocated: true, costAllocationTotal: 800000, costAllocationSchoolCount: 8,
    evidenceStatus: "complete", verificationStatus: "verified",
  },
  {
    id: "ACT-NTR4-3", schoolId: "GAP-NTR-4",
    activityType: "staff_visit", title: "Mid-Cycle Coaching",
    date: "2027-05-10", operationalCycle: "FY2027",
    deliveredByName: "CCEO Sarah Lamunu", deliveredByRole: "CCEO",
    ssaInterventionAddressed: "Teaching & Learning",
    cost: 310000, costSource: "staff_cost",
    evidenceStatus: "complete", verificationStatus: "verified",
  },

  // ============================================================
  // GAP-NV-1 / NV-2 / NV-3 — visit-bucket schools (light activity)
  // ============================================================
  {
    id: "ACT-NV1-1", schoolId: "GAP-NV-1",
    activityType: "ssa", title: "SSA completion visit",
    date: "2027-05-10", operationalCycle: "FY2027",
    deliveredByName: "CCEO Sarah Lamunu", deliveredByRole: "CCEO",
    cost: 280000, costSource: "staff_cost",
    evidenceStatus: "complete", verificationStatus: "verified",
  },
  {
    id: "ACT-NV2-1", schoolId: "GAP-NV-2",
    activityType: "ssa", title: "SSA completion visit",
    date: "2027-04-28", operationalCycle: "FY2027",
    deliveredByName: "PL Mary Aciro", deliveredByRole: "PL",
    cost: 280000, costSource: "staff_cost",
    evidenceStatus: "complete", verificationStatus: "verified",
  },
  {
    id: "ACT-NV3-1", schoolId: "GAP-NV-3",
    activityType: "ssa", title: "SSA completion visit",
    date: "2027-05-04", operationalCycle: "FY2027",
    deliveredByName: "CCEO Sarah Lamunu", deliveredByRole: "CCEO",
    cost: 280000, costSource: "staff_cost",
    evidenceStatus: "complete", verificationStatus: "verified",
  },
  {
    id: "ACT-NV3-2", schoolId: "GAP-NV-3",
    activityType: "training", title: "Resource Use Training",
    date: "2027-03-15", operationalCycle: "FY2027",
    deliveredByName: "Numeracy First", deliveredByRole: "Partner",
    partnerName: "Numeracy First",
    staffMonitorName: "CCEO Sarah Lamunu",
    cost: 920000, costSource: "training_cost",
    evidenceStatus: "verified", verificationStatus: "verified",
    paymentStatus: "paid_cleared",
  },
];
