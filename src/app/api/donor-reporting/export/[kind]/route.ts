import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDonorMetricSnapshot } from "@/lib/donor-metrics";
import {
  METRIC_GROUP_LABELS,
  METRIC_STATUS_LABELS,
  type DonorMetricSnapshot,
  type DonorRoleScope,
} from "@/lib/donor-metrics-types";

// GET /api/donor-reporting/export/[kind]
//
// Generates a donor-reporting CSV for the calling user's role scope.
// Every export is computed from the same DonorMetricSnapshot the
// analytics surface renders, so the file the donor receives matches
// the screen byte-for-byte.
//
// Supported kinds (the user-facing export menu lives in
// DonorReportingImpact):
//   donor-summary        — full KPI summary (label, value, status, source)
//   districts            — district coverage breakdown
//   interventions        — intervention area breakdown
//   schools-reached      — schools reached, one row per district
//   evidence-pending     — every gap that blocks the donor letter
//   teacher-training     — teacher / leader training attendance roll-up
//   student-impact       — student impact roll-up with enrollment caveat
//
// Header rows of every CSV include the reporting period, cycle, scope,
// generation timestamp, and verification gates so the file is
// self-describing once it leaves the system.

type ExportKind =
  | "donor-summary"
  | "districts"
  | "interventions"
  | "schools-reached"
  | "evidence-pending"
  | "teacher-training"
  | "student-impact";

const SUPPORTED: ExportKind[] = [
  "donor-summary",
  "districts",
  "interventions",
  "schools-reached",
  "evidence-pending",
  "teacher-training",
  "student-impact",
];

function csvEscape(v: unknown): string {
  if (v === null || v === undefined) return "";
  const s = String(v);
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function rowsToCsv(rows: (string | number | null | undefined)[][]): string {
  return rows.map((r) => r.map(csvEscape).join(",")).join("\n") + "\n";
}

function preamble(snapshot: DonorMetricSnapshot, kind: ExportKind): (string | number)[][] {
  return [
    [`Edify Donor Reporting — ${kindTitle(kind)}`],
    [`Scope`,        snapshot.scopeLabel,    `Role`, snapshot.roleScope],
    [`Cycle`,        snapshot.filters.operationalCycleLabel],
    [`Period`,       `${snapshot.filters.dateRangeStart} → ${snapshot.filters.dateRangeEnd}`],
    [`Generated at`, snapshot.generatedAt,   `by`,   snapshot.generatedBy],
    [`Readiness`,    `${snapshot.readiness.score}%`, `Summary`, snapshot.readiness.summary],
    [], // blank line before the data table
  ];
}

function kindTitle(kind: ExportKind): string {
  switch (kind) {
    case "donor-summary":     return "Donor Summary";
    case "districts":         return "District Coverage";
    case "interventions":     return "Intervention Breakdown";
    case "schools-reached":   return "Schools Reached";
    case "evidence-pending":  return "Evidence Pending";
    case "teacher-training":  return "Teacher Training Attendance";
    case "student-impact":    return "Student Impact Summary";
  }
}

function roleToScope(role: string): DonorRoleScope {
  switch (role) {
    case "CCEO":               return "CCEO";
    case "CountryProgramLead": return "ProgramLead";
    case "ImpactAssessment":   return "ImpactAssessment";
    case "CountryDirector":    return "CountryDirector";
    case "RVP":                return "RVP";
    default:                   return "ProgramLead";
  }
}

// ── Per-kind builders ───────────────────────────────────────────────

function buildDonorSummary(snapshot: DonorMetricSnapshot): (string | number | null)[][] {
  const header = [
    "Metric",
    "Group",
    "Donor-ready value",
    "Unit",
    "Total",
    "Confirmed",
    "Pending evidence",
    "Pending verification",
    "Excluded",
    "Status",
    "Source",
    "Definition",
  ];
  const rows: (string | number | null)[][] = [header];
  for (const m of snapshot.metrics) {
    rows.push([
      m.label,
      METRIC_GROUP_LABELS[m.group],
      m.value ?? "",
      m.unit ?? "",
      m.breakdown?.total ?? "",
      m.breakdown?.confirmed ?? "",
      m.breakdown?.pendingEvidence ?? "",
      m.breakdown?.pendingVerification ?? "",
      m.breakdown?.excluded ?? "",
      METRIC_STATUS_LABELS[m.status],
      m.source,
      m.definition ?? "",
    ]);
  }
  return rows;
}

function buildDistricts(snapshot: DonorMetricSnapshot): (string | number | null)[][] {
  const header = [
    "District", "Schools reached", "Teachers trained", "School leaders trained",
    "Students impacted", "Trainings", "Visits", "Schools improved", "Cost (UGX)",
  ];
  const rows: (string | number | null)[][] = [header];
  for (const d of snapshot.districts) {
    rows.push([
      d.district,
      d.schoolsReached,
      d.teachersTrained,
      d.schoolLeadersTrained,
      d.studentsImpacted ?? "",
      d.trainings,
      d.visits,
      d.schoolsImproved ?? "",
      d.costUgx ?? "",
    ]);
  }
  return rows;
}

function buildInterventions(snapshot: DonorMetricSnapshot): (string | number | null)[][] {
  const header = [
    "Intervention", "Trainings", "Teachers trained", "School leaders trained",
    "Schools reached", "Students impacted", "Schools improved", "Cost (UGX)",
  ];
  const rows: (string | number | null)[][] = [header];
  for (const r of snapshot.interventions) {
    rows.push([
      r.area,
      r.trainings,
      r.teachersTrained,
      r.schoolLeadersTrained,
      r.schoolsReached,
      r.studentsImpacted ?? "",
      r.schoolsImproved ?? "",
      r.costUgx ?? "",
    ]);
  }
  return rows;
}

function buildSchoolsReached(snapshot: DonorMetricSnapshot): (string | number | null)[][] {
  // Per-school listing isn't in the roll-up snapshot, so the export
  // pivots through district. The granular per-record CSV (one row per
  // school) lands when the schools-reached list endpoint is wired to
  // the underlying source-item table.
  const header = [
    "District", "Schools reached", "Schools improved", "Students impacted",
    "Visits", "Trainings",
  ];
  const rows: (string | number | null)[][] = [header];
  for (const d of snapshot.districts) {
    rows.push([
      d.district,
      d.schoolsReached,
      d.schoolsImproved ?? "",
      d.studentsImpacted ?? "",
      d.visits,
      d.trainings,
    ]);
  }
  return rows;
}

function buildEvidencePending(snapshot: DonorMetricSnapshot): (string | number | null)[][] {
  const header = [
    "Metric", "Pending evidence", "Pending verification", "Confirmed",
    "Status", "Affected note",
  ];
  const rows: (string | number | null)[][] = [header];
  for (const m of snapshot.metrics) {
    if (!m.breakdown) continue;
    const pending =
      (m.breakdown.pendingEvidence ?? 0) + (m.breakdown.pendingVerification ?? 0);
    if (pending === 0) continue;
    rows.push([
      m.label,
      m.breakdown.pendingEvidence,
      m.breakdown.pendingVerification,
      m.breakdown.confirmed,
      METRIC_STATUS_LABELS[m.status],
      (m.dataQualityNotes ?? []).join(" | "),
    ]);
  }
  rows.push([]); // separator
  rows.push(["Data-quality warnings"]);
  rows.push(["Severity", "Title", "Detail", "Affected metrics"]);
  for (const w of snapshot.warnings) {
    rows.push([
      w.severity,
      w.title,
      w.detail,
      w.affectedMetricKeys.join(" | "),
    ]);
  }
  return rows;
}

function buildTeacherTraining(snapshot: DonorMetricSnapshot): (string | number | null)[][] {
  const teachers = snapshot.metrics.find((m) => m.key === "teachersTrained");
  const leaders  = snapshot.metrics.find((m) => m.key === "schoolLeadersTrained");
  const trainings = snapshot.metrics.find((m) => m.key === "trainingsDelivered");

  const rows: (string | number | null)[][] = [];
  rows.push(["Summary"]);
  rows.push(["Metric", "Donor-ready", "Confirmed", "Pending evidence", "Pending verification"]);
  for (const m of [teachers, leaders, trainings]) {
    if (!m) continue;
    rows.push([
      m.label,
      m.value ?? "",
      m.breakdown?.confirmed ?? "",
      m.breakdown?.pendingEvidence ?? "",
      m.breakdown?.pendingVerification ?? "",
    ]);
  }
  rows.push([]);
  rows.push(["Attendance by intervention"]);
  rows.push(["Intervention", "Trainings", "Teachers trained", "School leaders trained"]);
  for (const r of snapshot.interventions) {
    rows.push([r.area, r.trainings, r.teachersTrained, r.schoolLeadersTrained]);
  }
  rows.push([]);
  rows.push(["Attendance by district"]);
  rows.push(["District", "Trainings", "Teachers trained", "School leaders trained"]);
  for (const d of snapshot.districts) {
    rows.push([d.district, d.trainings, d.teachersTrained, d.schoolLeadersTrained]);
  }
  return rows;
}

function buildStudentImpact(snapshot: DonorMetricSnapshot): (string | number | null)[][] {
  const c = snapshot.enrollmentCoverage;
  const students = snapshot.metrics.find((m) => m.key === "studentsImpacted");
  const cps = snapshot.metrics.find((m) => m.key === "costPerStudentImpacted");
  const rows: (string | number | null)[][] = [];
  rows.push(["Headline"]);
  rows.push(["Metric", "Value", "Status", "Source"]);
  for (const m of [students, cps]) {
    if (!m) continue;
    rows.push([
      m.label,
      m.value ?? "",
      METRIC_STATUS_LABELS[m.status],
      m.source,
    ]);
  }
  rows.push([]);
  rows.push(["Enrollment coverage"]);
  rows.push(["Schools reached", c.schoolsReached]);
  rows.push(["Schools with enrollment", c.schoolsWithEnrollment]);
  rows.push(["Schools missing enrollment", c.schoolsMissingEnrollment]);
  rows.push(["Caveat", c.note]);
  rows.push([]);
  rows.push(["Students impacted by district"]);
  rows.push(["District", "Schools reached", "Students impacted"]);
  for (const d of snapshot.districts) {
    rows.push([d.district, d.schoolsReached, d.studentsImpacted ?? ""]);
  }
  return rows;
}

// ── Route handler ───────────────────────────────────────────────────

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ kind: string }> },
) {
  const { kind: rawKind } = await params;
  const kind = rawKind as ExportKind;
  if (!SUPPORTED.includes(kind)) {
    return NextResponse.json(
      { error: `Unknown export kind: ${rawKind}. Supported: ${SUPPORTED.join(", ")}.` },
      { status: 400 },
    );
  }

  const user = await getCurrentUser();
  const snapshot = getDonorMetricSnapshot({
    role: roleToScope(user.role),
    userName: user.name,
    generatedBy: user.name,
  });

  let body: (string | number | null)[][];
  switch (kind) {
    case "donor-summary":    body = buildDonorSummary(snapshot);    break;
    case "districts":        body = buildDistricts(snapshot);       break;
    case "interventions":    body = buildInterventions(snapshot);   break;
    case "schools-reached":  body = buildSchoolsReached(snapshot);  break;
    case "evidence-pending": body = buildEvidencePending(snapshot); break;
    case "teacher-training": body = buildTeacherTraining(snapshot); break;
    case "student-impact":   body = buildStudentImpact(snapshot);   break;
  }

  const csv = rowsToCsv([...preamble(snapshot, kind), ...body]);
  const stamp = snapshot.generatedAt.slice(0, 10);
  const safeName = `edify-donor-${kind}-${snapshot.roleScope}-${stamp}.csv`;

  return new NextResponse(csv, {
    status: 200,
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="${safeName}"`,
      "Cache-Control": "no-store",
    },
  });
}
