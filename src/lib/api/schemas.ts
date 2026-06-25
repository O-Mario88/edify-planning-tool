// Zod contract schemas for the live dashboard surfaces consumed by SERVER
// components. These are the enforcement boundary for the golden rule:
//
//   live: true  ⇒  payload is fully valid against the schema below.
//
// Normalization rules (the ONLY sanctioned place to default data):
//   • every array field is `.default([])` — a missing/undefined list becomes []
//     (never undefined reaching .map()). A NON-array (null, object) still fails,
//     which is a real contract violation, surfaced in System Health.
//   • scalar fields the UI reads are typed; cosmetic/optional fields stay loose
//     so a harmless backend addition never turns a working surface red.
//
// Unknown keys are stripped by default (zod) — UI reads typed fields only.

import { z } from "zod";

const arr = <T extends z.ZodTypeAny>(item: T) => z.array(item).default([]);

// ── Analytics dashboard (CountryAnalyticsLive) ──────────────────────
export const dashboardSchema = z.object({
  role: z.string(),
  scope: z.object({
    countryScope: z.boolean(),
    schoolsInScope: z.number().nullable(),
  }),
  schools: z.number(),
  coreSchools: z.number(),
  clientSchools: z.number(),
  planningReady: z.number(),
  unclustered: z.number(),
  ssaDone: z.number(),
});

export const activityPipelineSchema = z.object({
  total: z.number(),
  byStatus: arr(z.object({ status: z.string(), count: z.number() })),
  byDelivery: arr(z.object({ deliveryType: z.string(), count: z.number() })),
});

// ── Leadership summary (LeadershipKpiStrip) ─────────────────────────
const interventionAvg = z.object({ intervention: z.string(), average: z.number() });

export const leadershipSummarySchema = z.object({
  countryScope: z.boolean(),
  schools: z.number(),
  coreSchools: z.number(),
  clientSchools: z.number(),
  clustered: z.number(),
  unclustered: z.number(),
  ssaDone: z.number(),
  ssaPending: z.number(),
  ssaCompletePct: z.number(),
  ssaAverage: z.number(),
  byIntervention: arr(interventionAvg),
  weakestInterventions: arr(interventionAvg),
  pipeline: z.object({
    planned: z.number(),
    scheduled: z.number(),
    inProgress: z.number(),
    evidenceUploaded: z.number(),
    awaitingIa: z.number(),
    iaVerified: z.number(),
    completed: z.number(),
  }),
  activitiesTotal: z.number(),
  staffCount: z.number(),
  partnerCount: z.number(),
  fundRequests: z.number(),
  paymentsCleared: z.number(),
  disbursedTotalUgx: z.number(),
});

// ── Leadership decision engine (DecisionEngineEmbed) ────────────────
const decisionInsightSchema = z
  .object({
    id: z.string(),
    decisionType: z.string(),
    riskLevel: z.string(),
    confidenceLevel: z.string(),
    confidenceScore: z.number(),
    recommendation: z.string(),
    riskFlags: arr(z.string()),
    evidencePoints: arr(z.unknown()),
  })
  .passthrough();

const decisionBoardSchema = z.object({
  decisionType: z.string(),
  canReview: z.boolean(),
  insights: arr(decisionInsightSchema),
});

export const leadershipBoardsSchema = z.object({
  fy: z.string(),
  visibleBoards: arr(z.string()),
  boards: arr(decisionBoardSchema),
});

export const leadershipSnapshotSchema = z.object({
  fy: z.string(),
  strategicHeadline: z.string(),
  regionsReadyToExpand: arr(z.string().nullable()),
  regionsToPauseRecruitment: arr(z.string().nullable()),
  staffOverloadRisks: z.number(),
  partnerMouRisks: z.number(),
  partnerCapacityGaps: z.number(),
  dataConfidence: z.number(),
  highRiskDecisions: z.number(),
  totalInsights: z.number(),
});

// ── Budget intelligence (BudgetIntelligenceEmbed) ───────────────────
const budgetInsightSchema = z
  .object({
    id: z.string(),
    fy: z.string(),
    insightType: z.string(),
    recommendation: z.string(),
    riskLevel: z.string(),
    impactYield: z.string(),
    confidenceLevel: z.string(),
    confidenceScore: z.number(),
    amountAffected: z.number().nullable().optional(),
    alternatives: arr(z.string()),
    riskFlags: arr(z.string()),
  })
  .passthrough();

export const budgetBoardsSchema = z.object({
  fy: z.string(),
  insights: arr(budgetInsightSchema),
});

export const budgetSnapshotSchema = z.object({
  fy: z.string(),
  totalInsights: z.number(),
  lowYieldCount: z.number(),
  highYieldCount: z.number(),
  amountAtRisk: z.number(),
  headline: z.string(),
});

// ── HR roster (StaffPerformanceLive) ────────────────────────────────
const rosterRowSchema = z
  .object({
    staffProfileId: z.string(),
    name: z.string(),
    role: z.string(),
    active: z.boolean(),
    primaryDistrict: z.string().nullable().optional(),
    schools: z.number().optional().default(0),
  })
  .passthrough();

export const rosterSchema = z.object({
  counts: z.object({ total: z.number(), active: z.number(), pending: z.number() }),
  staff: arr(rosterRowSchema),
});

// ── District rollups (geography filter universe) ────────────────────
export const districtRollupsSchema = z.object({
  districts: arr(
    z
      .object({ districtId: z.string(), district: z.string() })
      .passthrough(),
  ),
});

// ── Cluster planning intelligence — list endpoint /clusters/planning ──
// Open-ended cadence + coverage + recommendation. Mirrors `BeClusterPlanning`.
export const clusterPlanningSchema = arr(
  z
    .object({
      id: z.string(),
      clusterName: z.string(),
      district: z.string(),
      subCounty: z.string(),
      schoolsCount: z.number(),
      schoolsWithSsa: z.number(),
      meetingsThisFy: z.number(),
      meetingsScheduledThisFy: z.number().optional().default(0),
      trainingsThisFy: z.number().optional().default(0),
      lastMeetingDate: z.string().nullable(),
      nextScheduledMeetingDate: z.string().nullable().optional(),
      metThisQuarter: z.boolean(),
      schoolsNotVisited: z.number(),
      schoolsNotTrained: z.number(),
      schoolsNeitherVisitNorTraining: z.number(),
      gapCategory: z.string(),
      recommendationHeadline: z.string().nullable().optional(),
      recommendationReason: z.string().nullable().optional(),
      recommendationActivityLabel: z.string().nullable().optional(),
      recommendationFocusIntervention: z.string().nullable().optional(),
    })
    .passthrough(),
);

// ── Cluster intelligence — single cluster /clusters/:id/intelligence ──
const interventionPerformanceSchema = z
  .object({
    intervention: z.string(),
    averageScore: z.number(),
    schoolsAssessed: z.number(),
    schoolsMissingSsa: z.number().optional().default(0),
    previousAverage: z.number().optional(),
    delta: z.number().optional(),
    status: z.string(),
  })
  .passthrough();

const intelSchoolRowSchema = z
  .object({
    schoolId: z.string(),
    schoolName: z.string(),
    schoolType: z.string().optional(),
    hasCurrentFySsa: z.boolean(),
    latestSsa: z.number().nullable().optional(),
    weakestIntervention: z.string().nullable().optional(),
    visitedThisPeriod: z.boolean().optional().default(false),
    trainedThisPeriod: z.boolean().optional().default(false),
  })
  .passthrough();

export const clusterIntelligenceSchema = z.object({
  cluster: z.object({
    id: z.string(),
    name: z.string(),
    district: z.string().nullable(),
    subCounties: arr(z.string()),
    clusterType: z.string().optional(),
    clusterLeaderName: z.string().nullable().optional(),
  }),
  schools: arr(intelSchoolRowSchema),
  cadence: z.object({
    meetingsThisFy: z.number(),
    meetingsScheduledThisFy: z.number(),
    trainingsThisFy: z.number(),
    totalActivitiesThisFy: z.number(),
    lastMeetingDate: z.string().nullable(),
    nextScheduledDate: z.string().nullable(),
    metThisQuarter: z.boolean(),
    teachersTrained: z.number(),
    schoolLeadersTrained: z.number(),
  }),
  coverage: z.object({
    total: z.number(),
    withCurrentFySsa: z.number(),
    missingSsa: z.number(),
    notVisitedCount: z.number(),
    notTrainedCount: z.number(),
    neitherVisitNorTrainingCount: z.number(),
  }),
  ssaPerformance: arr(interventionPerformanceSchema),
  averageSsaScore: z.number(),
  weakestIntervention: interventionPerformanceSchema.nullable(),
  strongestIntervention: interventionPerformanceSchema.nullable(),
  improved: arr(
    z
      .object({
        intervention: z.string(),
        previousAverage: z.number(),
        latestAverage: z.number(),
        improvement: z.number(),
        schoolsImproved: z.number(),
      })
      .passthrough(),
  ),
  declined: arr(
    z
      .object({
        intervention: z.string(),
        previousAverage: z.number(),
        latestAverage: z.number(),
        drop: z.number(),
        schoolsDeclined: z.number(),
      })
      .passthrough(),
  ),
});

// ── Paginated envelope (activities / plan feeds) ────────────────────
// Guarantees `.data` is an array before a server component maps it. Rows stay
// loose (passthrough) so a harmless field change never reds out the surface —
// the invariant we enforce is "the list is a list", which is the crash vector.
export const paginatedEnvelopeSchema = z.object({
  data: arr(z.unknown()),
  total: z.number().optional(),
  page: z.number().optional(),
  pageSize: z.number().optional(),
  totalPages: z.number().optional(),
});
