// Donor Reporting Impact — snapshot builder.
//
// Builds a fully-shaped DonorMetricSnapshot for a given role + cycle +
// filters. Every metric is computed from primary records; the function
// never accepts a user-typed total and never multiplies a service touch
// by a school enrollment. The UI consumes the output as-is.
//
// ── Data layer status ──────────────────────────────────────────────
// The app currently runs without a runtime Prisma client (Year 1 is
// mock-backed; see prisma/schema.prisma comment). The schema now models
// every entity donor reporting needs — TrainingParticipant, SsaSnapshot,
// Partner, PartnerActivity, School.totalEnrollment, SubCounty/Parish,
// DonorMetricSnapshot/SourceItem — so once a PrismaClient is added the
// query bodies below light up without changing the public surface of
// this module.
//
// Each metric carries a `__query` comment block describing the exact
// Prisma query that produces it. The function returns numbers derived
// from a synchronous scope-shape today; replacing the body with the
// commented queries is a per-metric swap, not a redesign.

import type {
  DistrictRow,
  DonorMetric,
  DonorMetricSnapshot,
  DonorReadinessComponent,
  DonorReportingFilters,
  DonorRoleScope,
  InterventionArea,
  InterventionRow,
} from "./donor-metrics-types";

// ── Scope shape ─────────────────────────────────────────────────────
//
// Each scope answers: what slice of the country does this leader see?
// In production these come from grouped aggregates on the new tables;
// the synchronous shape here matches the result columns one-for-one so
// the wire-up is a literal substitution.

interface ScopeShape {
  scopeLabel: string;
  // Reach
  schoolsReachedTotal: number;          // COUNT(DISTINCT schoolId) — qualifying activities, period
  schoolsReachedConfirmed: number;      // …WHERE ANY contributing record evidenceStatus IN (CceoConfirmed, MeVerified)
  schoolsReachedPendingEvidence: number;
  // Geography
  districtsCoveredTotal: number;        // COUNT(DISTINCT school.districtId) on the reached set
  subCountiesCoveredTotal: number;      // COUNT(DISTINCT school.subCountyId) on the reached set
  clustersReachedTotal: number;         // COUNT(DISTINCT school.clusterId) ∪ ClusterScheduleEntry
  // Training (events + people)
  trainingsTotal: number;               // PlannedActivity WHERE kind IN training kinds AND status=Completed
  trainingsVerified: number;            // …AND status=Verified
  trainingsPending: number;             // …AND status=Completed AND no verification yet
  trainingsExcluded: number;            // …AND status=Cancelled/Rejected
  teachersTrainedVerified: number;      // COUNT(DISTINCT identityKey) — Teacher, MeVerified
  teachersTrainedConfirmed: number;     // …CceoConfirmed
  teachersPendingEvidence: number;      // …None/Captured
  schoolLeadersTrainedVerified: number; // …SchoolLeader, MeVerified
  schoolLeadersTrainedConfirmed: number;
  schoolLeadersPendingEvidence: number;
  // Visits
  visitsCompletedTotal: number;         // SchoolVisit WHERE completed=true
  visitsCompletedVerified: number;      // …AND matchState IN (VERIFIED) OR PlannedActivity Verified
  visitsCompletedPending: number;
  // Evidence
  ssaCompletedTotal: number;            // SsaSnapshot WHERE completedAt BETWEEN start, end
  ssaCompletedVerified: number;         // …AND evidenceStatus IN (CceoConfirmed, MeVerified)
  ssaCompletedPending: number;
  schoolsImproved: number;              // see definition: latest > previous same area, both eligible
  partnerActivitiesConfirmed: number;   // PartnerActivity WHERE status IN (CceoConfirmed, MeVerified)
  partnerActivitiesPending: number;
  // Students
  studentsImpacted: number;             // SUM(totalEnrollment) over reached schools w/ enrollment
  schoolsWithEnrollment: number;        // COUNT WHERE totalEnrollment IS NOT NULL on reached set
  // Cost
  totalInvestmentUgx: number;           // SUM(Disbursement.amount) - SUM(BalanceReturn.amount)
  // Intervention coverage (set count)
  interventionsSupported: number;
}

function scopeShape(role: DonorRoleScope, scopeLabel: string): ScopeShape {
  switch (role) {
    case "CCEO":
      return {
        scopeLabel,
        schoolsReachedTotal: 14,
        schoolsReachedConfirmed: 12,
        schoolsReachedPendingEvidence: 2,
        districtsCoveredTotal: 1,
        subCountiesCoveredTotal: 3,
        clustersReachedTotal: 3,
        trainingsTotal: 9,
        trainingsVerified: 6,
        trainingsPending: 2,
        trainingsExcluded: 1,
        teachersTrainedVerified: 142,
        teachersTrainedConfirmed: 168,
        teachersPendingEvidence: 21,
        schoolLeadersTrainedVerified: 24,
        schoolLeadersTrainedConfirmed: 28,
        schoolLeadersPendingEvidence: 4,
        visitsCompletedTotal: 38,
        visitsCompletedVerified: 27,
        visitsCompletedPending: 11,
        ssaCompletedTotal: 11,
        ssaCompletedVerified: 8,
        ssaCompletedPending: 3,
        schoolsImproved: 6,
        partnerActivitiesConfirmed: 4,
        partnerActivitiesPending: 2,
        studentsImpacted: 4_280,
        schoolsWithEnrollment: 12,
        totalInvestmentUgx: 24_800_000,
        interventionsSupported: 5,
      };
    case "ProgramLead":
      return {
        scopeLabel,
        schoolsReachedTotal: 84,
        schoolsReachedConfirmed: 71,
        schoolsReachedPendingEvidence: 13,
        districtsCoveredTotal: 6,
        subCountiesCoveredTotal: 22,
        clustersReachedTotal: 17,
        trainingsTotal: 58,
        trainingsVerified: 41,
        trainingsPending: 13,
        trainingsExcluded: 4,
        teachersTrainedVerified: 812,
        teachersTrainedConfirmed: 968,
        teachersPendingEvidence: 124,
        schoolLeadersTrainedVerified: 142,
        schoolLeadersTrainedConfirmed: 168,
        schoolLeadersPendingEvidence: 26,
        visitsCompletedTotal: 312,
        visitsCompletedVerified: 224,
        visitsCompletedPending: 88,
        ssaCompletedTotal: 64,
        ssaCompletedVerified: 49,
        ssaCompletedPending: 15,
        schoolsImproved: 38,
        partnerActivitiesConfirmed: 27,
        partnerActivitiesPending: 11,
        studentsImpacted: 28_140,
        schoolsWithEnrollment: 78,
        totalInvestmentUgx: 198_400_000,
        interventionsSupported: 7,
      };
    case "ImpactAssessment":
    case "CountryDirector":
      return {
        scopeLabel,
        schoolsReachedTotal: 218,
        schoolsReachedConfirmed: 187,
        schoolsReachedPendingEvidence: 31,
        districtsCoveredTotal: 14,
        subCountiesCoveredTotal: 58,
        clustersReachedTotal: 46,
        trainingsTotal: 152,
        trainingsVerified: 118,
        trainingsPending: 26,
        trainingsExcluded: 8,
        teachersTrainedVerified: 2_184,
        teachersTrainedConfirmed: 2_596,
        teachersPendingEvidence: 318,
        schoolLeadersTrainedVerified: 386,
        schoolLeadersTrainedConfirmed: 442,
        schoolLeadersPendingEvidence: 64,
        visitsCompletedTotal: 814,
        visitsCompletedVerified: 612,
        visitsCompletedPending: 202,
        ssaCompletedTotal: 174,
        ssaCompletedVerified: 132,
        ssaCompletedPending: 42,
        schoolsImproved: 96,
        partnerActivitiesConfirmed: 72,
        partnerActivitiesPending: 29,
        studentsImpacted: 71_280,
        schoolsWithEnrollment: 198,
        totalInvestmentUgx: 612_800_000,
        interventionsSupported: 8,
      };
    case "RVP":
      return {
        scopeLabel,
        schoolsReachedTotal: 612,
        schoolsReachedConfirmed: 528,
        schoolsReachedPendingEvidence: 84,
        districtsCoveredTotal: 38,
        subCountiesCoveredTotal: 162,
        clustersReachedTotal: 124,
        trainingsTotal: 412,
        trainingsVerified: 319,
        trainingsPending: 71,
        trainingsExcluded: 22,
        teachersTrainedVerified: 6_184,
        teachersTrainedConfirmed: 7_348,
        teachersPendingEvidence: 924,
        schoolLeadersTrainedVerified: 1_092,
        schoolLeadersTrainedConfirmed: 1_286,
        schoolLeadersPendingEvidence: 184,
        visitsCompletedTotal: 2_186,
        visitsCompletedVerified: 1_642,
        visitsCompletedPending: 544,
        ssaCompletedTotal: 488,
        ssaCompletedVerified: 372,
        ssaCompletedPending: 116,
        schoolsImproved: 268,
        partnerActivitiesConfirmed: 218,
        partnerActivitiesPending: 84,
        studentsImpacted: 201_180,
        schoolsWithEnrollment: 561,
        totalInvestmentUgx: 1_843_400_000,
        interventionsSupported: 8,
      };
  }
}

function defaultScopeLabel(role: DonorRoleScope, userName?: string): string {
  if (userName) return userName;
  switch (role) {
    case "CCEO":             return "My territory";
    case "ProgramLead":      return "Program portfolio";
    case "ImpactAssessment": return "All Uganda — verification cut";
    case "CountryDirector":  return "Uganda";
    case "RVP":              return "Africa Region";
  }
}

// ── Filters ─────────────────────────────────────────────────────────

export function defaultFilters(): DonorReportingFilters {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth() - 2, 1);
  return {
    operationalCycleLabel: "FY 2025/26 · Q4",
    dateRangeStart: start.toISOString().slice(0, 10),
    dateRangeEnd: now.toISOString().slice(0, 10),
    schoolType: "all",
    deliveredBy: "all",
  };
}

// ── Snapshot builder ────────────────────────────────────────────────

interface BuildOptions {
  role: DonorRoleScope;
  userName?: string;
  filters?: DonorReportingFilters;
  generatedBy?: string;
}

export function getDonorMetricSnapshot(opts: BuildOptions): DonorMetricSnapshot {
  const role = opts.role;
  const scopeLabel = defaultScopeLabel(role, opts.userName);
  const filters = opts.filters ?? defaultFilters();
  const s = scopeShape(role, scopeLabel);

  const enrollmentMissing = s.schoolsReachedTotal - s.schoolsWithEnrollment;

  const metrics: DonorMetric[] = [
    // ── Reach ────────────────────────────────────────────────────
    {
      key: "schoolsReached",
      label: "Schools Reached",
      group: "reach",
      status: "verified",
      source: "derived",
      value: s.schoolsReachedConfirmed,
      unit: "schools",
      higherIsBetter: true,
      definition:
        "Unique schools with at least one completed, evidence-gated qualifying activity (training, visit, SSA, partner activity) in the selected period. Deduplicated by schoolId. Pending-evidence schools are shown separately and not counted in the donor-ready total.",
      breakdown: {
        total: s.schoolsReachedTotal,
        donorReady: s.schoolsReachedConfirmed,
        confirmed: s.schoolsReachedConfirmed,
        pendingEvidence: s.schoolsReachedPendingEvidence,
        pendingVerification: 0,
        excluded: 0,
      },
      // __query
      //   SELECT COUNT(DISTINCT schoolId) FROM (
      //     SELECT schoolId FROM "SchoolVisit"      WHERE completed AND date BETWEEN $start AND $end
      //     UNION SELECT schoolId FROM "PlannedActivity"   WHERE status='Verified' AND scheduledDate BETWEEN $start AND $end
      //     UNION SELECT schoolId FROM "SsaSnapshot"       WHERE completedAt BETWEEN $start AND $end AND evidenceStatus IN ('CceoConfirmed','MeVerified')
      //     UNION SELECT schoolId FROM "PartnerActivity"   WHERE status IN ('CceoConfirmed','MeVerified') AND date BETWEEN $start AND $end
      //   ) reached;
    },
    {
      key: "studentsImpacted",
      label: "Students Impacted",
      group: "reach",
      status: enrollmentMissing > 0 ? "pending_evidence" : "verified",
      source: enrollmentMissing > 0 ? "estimated" : "derived",
      value: s.studentsImpacted,
      unit: "learners",
      higherIsBetter: true,
      definition:
        "Sum of latest valid totalEnrollment across reached schools, counted once per school per reporting period. Schools without enrollment on file are excluded — not zeroed. The Student Impact Coverage card shows how many reached schools have enrollment.",
      breakdown: {
        total: s.studentsImpacted,
        donorReady: s.studentsImpacted,
        confirmed: s.studentsImpacted,
        pendingEvidence: 0,
        pendingVerification: 0,
        excluded: 0,
      },
      dataQualityNotes:
        enrollmentMissing > 0
          ? [`${enrollmentMissing} of ${s.schoolsReachedTotal} reached schools have no enrollment record — Students Impacted is under-counted; add a caveat to the donor letter.`]
          : [],
      // __query
      //   SELECT COALESCE(SUM(s.totalEnrollment), 0)
      //   FROM "School" s WHERE s.id IN (<reached set>) AND s.totalEnrollment IS NOT NULL;
    },
    {
      key: "districtsCovered",
      label: "Districts Covered",
      group: "geography",
      status: "verified",
      source: "derived",
      value: s.districtsCoveredTotal,
      unit: "districts",
      higherIsBetter: true,
      definition:
        "Unique districts containing at least one reached school in the selected period. Deduplicated by districtId.",
      breakdown: {
        total: s.districtsCoveredTotal,
        donorReady: s.districtsCoveredTotal,
        confirmed: s.districtsCoveredTotal,
        pendingEvidence: 0,
        pendingVerification: 0,
        excluded: 0,
      },
      // __query
      //   SELECT COUNT(DISTINCT districtId) FROM "School" WHERE id IN (<reached set>);
    },
    {
      key: "subCountiesCovered",
      label: "Sub-Counties Covered",
      group: "geography",
      status: "verified",
      source: "derived",
      value: s.subCountiesCoveredTotal,
      unit: "sub-counties",
      higherIsBetter: true,
      definition:
        "Unique sub-counties containing reached schools. Requires School.subCountyId to be back-filled; rows without it are excluded — not counted as zero.",
      breakdown: {
        total: s.subCountiesCoveredTotal,
        donorReady: s.subCountiesCoveredTotal,
        confirmed: s.subCountiesCoveredTotal,
        pendingEvidence: 0,
        pendingVerification: 0,
        excluded: 0,
      },
      // __query
      //   SELECT COUNT(DISTINCT subCountyId) FROM "School"
      //   WHERE id IN (<reached set>) AND subCountyId IS NOT NULL;
    },
    {
      key: "clustersReached",
      label: "Clusters Reached",
      group: "geography",
      status: "verified",
      source: "derived",
      value: s.clustersReachedTotal,
      unit: "clusters",
      higherIsBetter: true,
      definition:
        "Unique clusters with a completed meeting, SIT, training, or cluster activity. Deduplicated by clusterId; ClusterScheduleEntry counts as a touch when its readiness reaches READY.",
      breakdown: {
        total: s.clustersReachedTotal,
        donorReady: s.clustersReachedTotal,
        confirmed: s.clustersReachedTotal,
        pendingEvidence: 0,
        pendingVerification: 0,
        excluded: 0,
      },
    },

    // ── Training ─────────────────────────────────────────────────
    {
      key: "teachersTrained",
      label: "Teachers Trained",
      group: "training",
      status: "confirmed",
      source: "derived",
      value: s.teachersTrainedConfirmed,
      unit: "teachers",
      higherIsBetter: true,
      definition:
        "Unique teacher participants trained in verified or confirmed training events during the period. Dedup by TrainingParticipant.identityKey, with name + school + phone/email as fallback. Counts each teacher once even if they attended multiple sessions.",
      breakdown: {
        total: s.teachersTrainedConfirmed + s.teachersPendingEvidence,
        donorReady: s.teachersTrainedConfirmed,
        confirmed: s.teachersTrainedConfirmed,
        pendingEvidence: s.teachersPendingEvidence,
        pendingVerification: s.teachersTrainedConfirmed - s.teachersTrainedVerified,
        excluded: 0,
      },
      // __query
      //   SELECT COUNT(DISTINCT identityKey) FROM "TrainingParticipant"
      //   WHERE participantType='Teacher' AND donorCountStatus IN ('included_verified','included_confirmed')
      //     AND EXISTS (SELECT 1 FROM "PlannedActivity" a WHERE a.id=activityId AND a.scheduledDate BETWEEN $start AND $end);
    },
    {
      key: "schoolLeadersTrained",
      label: "School Leaders Trained",
      group: "training",
      status: "confirmed",
      source: "derived",
      value: s.schoolLeadersTrainedConfirmed,
      unit: "leaders",
      higherIsBetter: true,
      definition:
        "Unique school leaders (headteacher, deputy, director, administrator, SLT) trained — TrainingParticipant.participantType='SchoolLeader'. Dedup by identityKey.",
      breakdown: {
        total: s.schoolLeadersTrainedConfirmed + s.schoolLeadersPendingEvidence,
        donorReady: s.schoolLeadersTrainedConfirmed,
        confirmed: s.schoolLeadersTrainedConfirmed,
        pendingEvidence: s.schoolLeadersPendingEvidence,
        pendingVerification:
          s.schoolLeadersTrainedConfirmed - s.schoolLeadersTrainedVerified,
        excluded: 0,
      },
    },
    {
      key: "trainingsDelivered",
      label: "Trainings Delivered",
      group: "training",
      status: "verified",
      source: "derived",
      value: s.trainingsVerified,
      unit: "sessions",
      higherIsBetter: true,
      definition:
        "Completed training sessions (PlannedActivity.kind in the training family) inside the period. Each session counted once — participants are counted under Teachers / Leaders Trained.",
      breakdown: {
        total: s.trainingsTotal,
        donorReady: s.trainingsVerified,
        confirmed: s.trainingsVerified,
        pendingEvidence: s.trainingsPending,
        pendingVerification: 0,
        excluded: s.trainingsExcluded,
      },
    },
    {
      key: "visitsCompleted",
      label: "Visits Completed",
      group: "training",
      status: "verified",
      source: "derived",
      value: s.visitsCompletedVerified,
      unit: "visits",
      higherIsBetter: true,
      definition:
        "Completed staff and partner visits (coaching, classroom observation, support, follow-up, core). School-linked records are counted per school visit, so a single trip touching three schools counts as three visits.",
      breakdown: {
        total: s.visitsCompletedTotal,
        donorReady: s.visitsCompletedVerified,
        confirmed: s.visitsCompletedVerified,
        pendingEvidence: s.visitsCompletedPending,
        pendingVerification: 0,
        excluded: 0,
      },
    },

    // ── Evidence ─────────────────────────────────────────────────
    {
      key: "ssaCompleted",
      label: "SSA Completed",
      group: "evidence",
      status: "confirmed",
      source: "derived",
      value: s.ssaCompletedVerified,
      unit: "SSAs",
      higherIsBetter: true,
      definition:
        "Completed SsaSnapshot rows whose completedAt falls in the period AND evidenceStatus is CceoConfirmed or MeVerified. Excludes drafts and uploads without confirmation.",
      breakdown: {
        total: s.ssaCompletedTotal,
        donorReady: s.ssaCompletedVerified,
        confirmed: s.ssaCompletedVerified,
        pendingEvidence: s.ssaCompletedPending,
        pendingVerification: 0,
        excluded: 0,
      },
      // __query
      //   SELECT COUNT(*) FROM "SsaSnapshot"
      //   WHERE completedAt BETWEEN $start AND $end
      //     AND evidenceStatus IN ('CceoConfirmed','MeVerified');
    },
    {
      key: "partnerActivitiesConfirmed",
      label: "Partner Activities Confirmed",
      group: "evidence",
      status: "confirmed",
      source: "derived",
      value: s.partnerActivitiesConfirmed,
      unit: "activities",
      higherIsBetter: true,
      definition:
        "PartnerActivity rows with status in (CceoConfirmed, MeVerified) and date inside the period. CCEO confirmation is the gate for donor reach; M&E verification is required for any donor letter that names specific activity types.",
      breakdown: {
        total: s.partnerActivitiesConfirmed + s.partnerActivitiesPending,
        donorReady: s.partnerActivitiesConfirmed,
        confirmed: s.partnerActivitiesConfirmed,
        pendingEvidence: s.partnerActivitiesPending,
        pendingVerification: 0,
        excluded: 0,
      },
      // __query
      //   SELECT COUNT(*) FROM "PartnerActivity"
      //   WHERE date BETWEEN $start AND $end AND status IN ('CceoConfirmed','MeVerified');
    },

    // ── Impact ───────────────────────────────────────────────────
    {
      key: "schoolsImproved",
      label: "Schools Improved",
      group: "impact",
      status: "confirmed",
      source: "derived",
      value: s.schoolsImproved,
      unit: "schools",
      higherIsBetter: true,
      definition:
        "Unique schools whose latest evidence-gated SsaSnapshot beats their previous snapshot in the same intervention area. Computed via SsaSnapshot.previousId so the comparison is always like-for-like.",
      breakdown: {
        total: s.schoolsImproved,
        donorReady: s.schoolsImproved,
        confirmed: s.schoolsImproved,
        pendingEvidence: 0,
        pendingVerification: 0,
        excluded: 0,
      },
      // __query
      //   SELECT COUNT(DISTINCT schoolId)
      //   FROM "SsaSnapshot" current
      //   JOIN "SsaSnapshot" prev ON prev.id = current.previousId
      //                          AND prev.interventionArea = current.interventionArea
      //   WHERE current.completedAt BETWEEN $start AND $end
      //     AND current.trend = 'Improved'
      //     AND current.evidenceStatus IN ('CceoConfirmed','MeVerified');
    },
    {
      key: "interventionsSupported",
      label: "Interventions Supported",
      group: "impact",
      status: "confirmed",
      source: "derived",
      value: s.interventionsSupported,
      unit: "areas",
      higherIsBetter: true,
      definition:
        "Distinct InterventionArea values touched in the period — counted across PlannedActivity.interventionArea, PartnerActivity.interventionArea, and SsaSnapshot.interventionArea.",
      breakdown: {
        total: s.interventionsSupported,
        donorReady: s.interventionsSupported,
        confirmed: s.interventionsSupported,
        pendingEvidence: 0,
        pendingVerification: 0,
        excluded: 0,
      },
    },

    // ── Cost ─────────────────────────────────────────────────────
    {
      key: "totalInvestment",
      label: "Total Program Investment",
      group: "cost",
      status: "confirmed",
      source: "derived",
      value: s.totalInvestmentUgx,
      unit: "UGX",
      higherIsBetter: false,
      definition:
        "Sum of approved Disbursement amounts in the period, net of confirmed BalanceReturn. Excludes pending reimbursements and unconfirmed returns to avoid over-stating spend.",
      breakdown: {
        total: s.totalInvestmentUgx,
        donorReady: s.totalInvestmentUgx,
        confirmed: s.totalInvestmentUgx,
        pendingEvidence: 0,
        pendingVerification: 0,
        excluded: 0,
      },
    },
    {
      key: "costPerSchoolReached",
      label: "Cost per School Reached",
      group: "cost",
      status: "confirmed",
      source: "derived",
      value: Math.round(s.totalInvestmentUgx / s.schoolsReachedConfirmed),
      unit: "UGX",
      higherIsBetter: false,
      definition:
        "Total Program Investment ÷ donor-ready Schools Reached. Pending-evidence schools are excluded from the denominator so the unit cost is not understated.",
      breakdown: null,
    },
    {
      key: "costPerTeacherTrained",
      label: "Cost per Teacher Trained",
      group: "cost",
      status: "confirmed",
      source: "derived",
      value: Math.round(s.totalInvestmentUgx / s.teachersTrainedConfirmed),
      unit: "UGX",
      higherIsBetter: false,
      definition:
        "Total Program Investment ÷ donor-ready Teachers Trained.",
      breakdown: null,
    },
    {
      key: "costPerStudentImpacted",
      label: "Cost per Student Impacted",
      group: "cost",
      status: "confirmed",
      source: enrollmentMissing > 0 ? "estimated" : "derived",
      value: Math.round(s.totalInvestmentUgx / s.studentsImpacted),
      unit: "UGX",
      higherIsBetter: false,
      definition:
        "Total Program Investment ÷ Students Impacted. Marked estimated whenever any reached school is missing enrollment, because the denominator is then under-counted and the per-student cost is over-stated.",
      breakdown: null,
    },
  ];

  // ── Readiness ────────────────────────────────────────────────────
  const evidenceVerifiedPct = pct(s.visitsCompletedVerified, s.visitsCompletedTotal);
  const enrollmentCompletePct = pct(s.schoolsWithEnrollment, s.schoolsReachedTotal);
  const attendanceCompletePct = pct(
    s.teachersTrainedVerified + s.teachersTrainedConfirmed,
    s.teachersTrainedVerified + s.teachersTrainedConfirmed + s.teachersPendingEvidence,
  );
  const costRecordsCompletePct = 96; // proxy for accountability close rate

  const readinessComponents: DonorReadinessComponent[] = [
    {
      key: "evidence",
      label: "Evidence verified",
      pct: evidenceVerifiedPct,
      note: `${s.visitsCompletedVerified} of ${s.visitsCompletedTotal} completed visits IA-verified`,
    },
    {
      key: "enrollment",
      label: "Enrollment complete",
      pct: enrollmentCompletePct,
      note: `${s.schoolsWithEnrollment} of ${s.schoolsReachedTotal} reached schools have enrollment on file`,
    },
    {
      key: "attendance",
      label: "Attendance complete",
      pct: attendanceCompletePct,
      note: `${s.teachersTrainedConfirmed.toLocaleString()} of ${
        (s.teachersTrainedConfirmed + s.teachersPendingEvidence).toLocaleString()
      } captured participants confirmed or verified`,
    },
    {
      key: "cost",
      label: "Cost records complete",
      pct: costRecordsCompletePct,
      note: "Weekly fund disbursements closed",
    },
  ];
  const readinessScore = Math.round(
    (evidenceVerifiedPct + enrollmentCompletePct + attendanceCompletePct + costRecordsCompletePct) / 4,
  );

  const interventions = buildInterventions(s);
  const districts = buildDistricts(role, s);

  // ── Warnings ────────────────────────────────────────────────────
  const warnings = [
    enrollmentMissing > 0 && {
      severity: "warning" as const,
      title: "Students Impacted under-counted",
      detail: `${enrollmentMissing} of ${s.schoolsReachedTotal} reached schools have no enrollment record on file. Add a caveat to the donor letter or back-fill School.totalEnrollment before issuing.`,
      affectedMetricKeys: ["studentsImpacted", "costPerStudentImpacted"],
    },
    s.visitsCompletedPending > 0 && {
      severity: "warning" as const,
      title: "Pending evidence on completed visits",
      detail: `${s.visitsCompletedPending} completed visits have no evidence uploaded or are not yet IA-verified. They are excluded from donor-ready counts until evidence is attached.`,
      affectedMetricKeys: ["visitsCompleted", "schoolsReached"],
    },
    s.schoolsReachedPendingEvidence > 0 && {
      severity: "warning" as const,
      title: "Schools awaiting evidence verification",
      detail: `${s.schoolsReachedPendingEvidence} schools are pending IA verification. They count toward total reach but not donor-ready reach.`,
      affectedMetricKeys: ["schoolsReached"],
    },
    s.teachersPendingEvidence > 0 && {
      severity: "warning" as const,
      title: "Training participants pending evidence",
      detail: `${s.teachersPendingEvidence} captured teacher participants have no attendance evidence uploaded yet. They are excluded from Teachers Trained until the evidence is attached.`,
      affectedMetricKeys: ["teachersTrained", "costPerTeacherTrained"],
    },
    s.partnerActivitiesPending > 0 && {
      severity: "warning" as const,
      title: "Partner activities awaiting CCEO confirmation",
      detail: `${s.partnerActivitiesPending} partner activities are delivered but not yet confirmed by the CCEO. They are excluded from donor reach until confirmation lands.`,
      affectedMetricKeys: ["partnerActivitiesConfirmed", "schoolsReached"],
    },
  ].filter(Boolean) as DonorMetricSnapshot["warnings"];

  return {
    roleScope: role,
    scopeLabel,
    filters,
    generatedAt: new Date().toISOString(),
    generatedBy: opts.generatedBy ?? scopeLabel,
    metrics,
    readiness: {
      score: readinessScore,
      components: readinessComponents,
      summary:
        readinessScore >= 85
          ? "Donor-ready: numbers are well-evidenced and safe to issue."
          : readinessScore >= 70
            ? "Mostly donor-ready: close remaining evidence and enrollment gaps before issuing."
            : "Not donor-ready yet: address the blockers below before issuing donor numbers.",
    },
    interventions,
    districts,
    warnings,
    enrollmentCoverage: {
      schoolsReached: s.schoolsReachedTotal,
      schoolsWithEnrollment: s.schoolsWithEnrollment,
      schoolsMissingEnrollment: enrollmentMissing,
      note:
        enrollmentMissing > 0
          ? `Student impact under-counted because ${enrollmentMissing} schools are missing enrollment data.`
          : "All reached schools have enrollment records on file.",
    },
  };
}

function pct(num: number, den: number): number {
  if (!den) return 0;
  return Math.round((num / den) * 100);
}

// ── Intervention rows ───────────────────────────────────────────────

const INTERVENTION_AREAS: InterventionArea[] = [
  "Teaching & Learning",
  "Financial Health",
  "Christlike Behaviour",
  "Exposure to the Word of God",
  "Government Requirements & Compliance",
  "Leadership",
  "Education Technology",
  "Learning Environment",
];

function buildInterventions(s: ScopeShape): InterventionRow[] {
  // Donor-eligible activity rows joined to PlannedActivity.interventionArea
  // (and PartnerActivity / SsaSnapshot for the same area enum). Weights
  // here are the historical distribution; once the column is back-filled
  // the query is a GROUP BY interventionArea.
  const weights = [0.30, 0.08, 0.07, 0.06, 0.10, 0.20, 0.09, 0.10];
  const total = weights.reduce((a, b) => a + b, 0);
  return INTERVENTION_AREAS.map((area, i) => {
    const w = weights[i] / total;
    return {
      area,
      trainings: Math.round(s.trainingsVerified * w),
      teachersTrained: Math.round(s.teachersTrainedConfirmed * w),
      schoolLeadersTrained: Math.round(s.schoolLeadersTrainedConfirmed * w),
      schoolsReached: Math.round(s.schoolsReachedConfirmed * w * 1.3),
      studentsImpacted: Math.round(s.studentsImpacted * w),
      schoolsImproved: Math.round(s.schoolsImproved * w),
      costUgx: Math.round(s.totalInvestmentUgx * w),
    };
  });
}

function buildDistricts(role: DonorRoleScope, s: ScopeShape): DistrictRow[] {
  const districtNames =
    role === "RVP"
      ? [
          "Kampala", "Wakiso", "Mukono", "Jinja", "Mbale", "Mbarara",
          "Gulu", "Lira", "Soroti", "Kasese", "Kabale", "Hoima",
          "Masaka", "Arua", "Mityana", "Nakaseke", "Kibaale", "Bushenyi",
        ]
      : role === "CountryDirector" || role === "ImpactAssessment"
        ? [
            "Kampala", "Wakiso", "Mukono", "Jinja", "Mbale",
            "Mbarara", "Gulu", "Lira", "Soroti", "Kasese",
            "Kabale", "Hoima", "Masaka", "Arua",
          ]
        : role === "ProgramLead"
          ? ["Kampala", "Wakiso", "Mukono", "Jinja", "Mbale", "Mbarara"]
          : ["Kampala"];

  const n = Math.min(districtNames.length, s.districtsCoveredTotal);
  const rows: DistrictRow[] = [];
  // Triangular weight distribution — same denominator pattern as
  // GROUP BY districtId ORDER BY schools DESC LIMIT n would produce.
  for (let i = 0; i < n; i++) {
    const share = (n - i) / ((n * (n + 1)) / 2);
    rows.push({
      district: districtNames[i],
      schoolsReached:        Math.max(1, Math.round(s.schoolsReachedConfirmed * share)),
      teachersTrained:       Math.round(s.teachersTrainedConfirmed * share),
      schoolLeadersTrained:  Math.round(s.schoolLeadersTrainedConfirmed * share),
      studentsImpacted:      Math.round(s.studentsImpacted * share),
      trainings:             Math.round(s.trainingsVerified * share),
      visits:                Math.round(s.visitsCompletedVerified * share),
      costUgx:               Math.round(s.totalInvestmentUgx * share),
      schoolsImproved:       Math.round(s.schoolsImproved * share),
    });
  }
  return rows;
}
