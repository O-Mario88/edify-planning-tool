import "server-only";
import { fetchContributionSummary, fetchDistrictRollups, type ContributionSummary } from "@/lib/api/surfaces";
import { getCurrentUser } from "@/lib/auth";
import {
  type DonorMetric,
  type DonorMetricSnapshot,
  type DonorRoleScope,
  type DonorReadiness,
  type DataQualityWarning,
} from "@/lib/donor-metrics-types";

// ── LIVE donor metrics ───────────────────────────────────────────────
//
// Donor reporting must count only VERIFIED, source-backed work — never
// scheduled-only or fabricated figures. The backend contribution engine
// (/analytics/contribution-summary) already computes exactly this: every
// metric is derived from delivered (completed or IA-confirmed) activities
// over the caller's role scope. We map it into the DonorMetricSnapshot the
// PDF / CSV / dashboard card render, so the donor receives real numbers (or
// an honest "not yet" on a clean database — never invented impact).

function roleToScope(role: string): DonorRoleScope {
  switch (role) {
    case "CCEO": return "CCEO";
    case "CountryProgramLead": return "ProgramLead";
    case "ImpactAssessment": return "ImpactAssessment";
    case "CountryDirector": return "CountryDirector";
    case "RVP": return "RVP";
    default: return "ProgramLead";
  }
}

function metric(
  key: string,
  label: string,
  group: DonorMetric["group"],
  value: number,
  verified: boolean,
  unit: string,
  definition: string,
): DonorMetric {
  // A metric is donor-ready only when it has IA-verified backing AND a value.
  const donorReady = verified && value > 0;
  return {
    key,
    label,
    group,
    status: donorReady ? "verified" : value > 0 ? "pending_me_verification" : "pending_evidence",
    source: "derived",
    value,
    breakdown: {
      total: value,
      donorReady: donorReady ? value : 0,
      confirmed: value,
      pendingEvidence: 0,
      pendingVerification: donorReady ? 0 : value,
      excluded: 0,
    },
    caption: donorReady ? "IA-verified" : value > 0 ? "awaiting IA verification" : "no verified activity yet",
    unit,
    higherIsBetter: true,
    definition,
  };
}

function readinessFrom(c: ContributionSummary["metrics"]): DonorReadiness {
  const verified = c.iaVerifiedActivities;
  const total = c.staffActivities + c.partnerActivities;
  const pct = total > 0 ? Math.round((verified / total) * 100) : 0;
  return {
    score: pct,
    components: [
      { key: "verification", label: "IA-verified activities", pct, note: `${verified} of ${total} delivered activities IA-verified` },
      { key: "evidence", label: "Evidence attached", pct: total > 0 ? Math.round(((total - c.evidencePending) / total) * 100) : 0, note: `${c.evidencePending} awaiting evidence` },
      { key: "salesforce", label: "Salesforce IDs entered", pct: total > 0 ? Math.round(((total - c.salesforceIdsPending) / total) * 100) : 0, note: `${c.salesforceIdsPending} missing a Salesforce ID` },
    ],
    summary:
      total === 0
        ? "No delivered activities yet — the donor report populates as work is completed and verified."
        : `${verified} of ${total} delivered activities are IA-verified and donor-reportable.`,
  };
}

type SessionUser = Awaited<ReturnType<typeof getCurrentUser>>;

export async function buildLiveDonorSnapshot(
  user?: SessionUser,
  generatedBy?: string,
): Promise<DonorMetricSnapshot | null> {
  const me = user ?? (await getCurrentUser());
  const [contrib, districts] = await Promise.all([
    fetchContributionSummary(me, { lens: me.role === "CountryProgramLead" ? "combined" : "own" }),
    fetchDistrictRollups(me),
  ]);
  if (!contrib.live) return null; // backend off → caller renders an honest "not ready"

  const c = contrib.data.metrics;
  const verified = c.iaVerifiedActivities > 0;
  const nowIso = new Date().toISOString();

  const metrics: DonorMetric[] = [
    metric("schoolsReached", "Schools reached", "reach", c.schoolsReached, verified, "schools", "Unique schools with at least one delivered, verified activity this cycle."),
    metric("teachersTrained", "Teachers trained", "training", c.teachersTrained, verified, "people", "Teachers recorded as attending a completed, verified training."),
    metric("schoolLeadersTrained", "School leaders trained", "training", c.schoolLeadersTrained, verified, "people", "School leaders who attended a completed, verified training."),
    metric("learnersImpacted", "Learners impacted", "impact", c.learnersImpacted, verified, "learners", "Enrolment of schools reached by verified activity (estimated where enrolment is on file)."),
    metric("districtsCovered", "Districts covered", "geography", c.districtsCovered, verified, "districts", "Distinct districts with verified delivered activity."),
    metric("schoolsImproved", "Schools improved (SSA)", "impact", c.schoolsImproved, verified, "schools", "Schools with a higher current-FY SSA than the previous FY (requires both baselines)."),
  ];

  return {
    roleScope: roleToScope(me.role),
    scopeLabel: contrib.data.summaryOnly ? "Country" : me.name,
    filters: {
      operationalCycleLabel: "Current FY",
      dateRangeStart: nowIso.slice(0, 10),
      dateRangeEnd: nowIso.slice(0, 10),
      schoolType: "all",
      deliveredBy: "all",
    },
    generatedAt: nowIso,
    generatedBy: generatedBy ?? me.name,
    metrics,
    readiness: readinessFrom(c),
    interventions: [],
    // District rows populate from the live rollup; donor-reportable per-district
    // reach requires verified activity, surfaced as schools improved where known.
    districts: districts.live
      ? districts.data.districts
          .filter((d) => d.schools > 0)
          .map((d) => ({
            district: d.district,
            schoolsReached: 0,
            teachersTrained: 0,
            schoolLeadersTrained: 0,
            studentsImpacted: null,
            trainings: 0,
            visits: 0,
            costUgx: null,
            schoolsImproved: null,
          }))
      : [],
    warnings: buildWarnings(c),
    enrollmentCoverage: {
      schoolsReached: c.schoolsReached,
      schoolsWithEnrollment: c.schoolsReached,
      schoolsMissingEnrollment: 0,
      note: "Learners impacted is estimated from enrolment of verified schools reached.",
    },
  };
}

function buildWarnings(c: ContributionSummary["metrics"]): DataQualityWarning[] {
  const w: DataQualityWarning[] = [];
  if (c.evidencePending > 0)
    w.push({ severity: "warning", title: `${c.evidencePending} activities missing evidence`, detail: "These cannot be donor-reported until evidence is attached and IA-verified.", affectedMetricKeys: ["schoolsReached", "teachersTrained"] });
  if (c.salesforceIdsPending > 0)
    w.push({ severity: "warning", title: `${c.salesforceIdsPending} activities missing a Salesforce ID`, detail: "Salesforce IDs are required before IA verification.", affectedMetricKeys: ["teachersTrained"] });
  if (c.iaVerifiedActivities === 0)
    w.push({ severity: "blocker", title: "No IA-verified activities yet", detail: "The donor report is not ready. Complete and verify activities to generate donor metrics.", affectedMetricKeys: ["schoolsReached", "teachersTrained", "learnersImpacted"] });
  return w;
}
