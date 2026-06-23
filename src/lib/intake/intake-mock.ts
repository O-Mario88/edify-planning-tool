// Data-intake store — schools + SSA performance uploaded by IA/Admin.
//
// Mutable in-memory store (mock mode persists for the running server session;
// Year-2 swaps for Prisma writes). Client-safe so the intake surface can render
// the "recently added" lists without a round-trip.

import { ssaAverage, type SchoolType, type SsaInterventionArea } from "./intake-core";
import { clearSsaActivation } from "@/lib/school-directory/ssa-activation";

export type IntakeSchool = {
  schoolId: string;
  schoolName: string;
  region: string;
  district: string;
  subCounty?: string;
  parish?: string;
  schoolType: SchoolType;
  enrollment?: number;
  assignedCceo?: string;
  /** Cluster display name — kept in sync with `clusterId` by the cluster engine. */
  cluster?: string;
  /** Canonical cluster id (source of truth for the cluster gate). */
  clusterId?: string;
  /**
   * Cluster setup state. Drives the mandatory Cluster Assignment Gate:
   *   unclustered  → not yet in a cluster (next required setup action)
   *   clustered    → assigned to a cluster (cluster gate cleared)
   *   needs_review → IA flagged the cluster as wrong/inconsistent
   * Absent rows are treated as "unclustered".
   */
  clusterStatus?: "unclustered" | "clustered" | "needs_review";
  // Optional detail fields — completed at create or later via "Edit details".
  phone?: string;
  primaryContact?: string;
  shippingAddress?: string;
  lastEnrollmentDate?: string;
  status: "Active";
  ssaStatus: "SSA Not Done" | "SSA Done";
  planningLocked: boolean;
  dateAdded: string;
  addedBy: string;
};

/** Fields a staff/IA member can complete after upload (none block creation). */
export type IntakeSchoolEditable = Partial<Pick<IntakeSchool,
  "enrollment" | "assignedCceo" | "cluster" | "subCounty" | "phone" | "primaryContact" | "shippingAddress" | "lastEnrollmentDate"
>>;

/** Patch a school's optional detail fields. Returns the updated row. */
export function updateIntakeSchool(schoolId: string, patch: IntakeSchoolEditable): IntakeSchool | undefined {
  const s = intakeSchools.find((x) => x.schoolId === schoolId);
  if (!s) return undefined;
  for (const [k, v] of Object.entries(patch)) {
    if (v === undefined) continue;
    (s as Record<string, unknown>)[k] = v === "" ? undefined : v;
  }
  return s;
}

export type SsaUpload = {
  id: string;
  schoolId: string;
  ssaDate: string;
  fy: string;
  quarter: string;
  averageScore: number;
  scores: Record<string, number>;
  newEnrollment?: number;
  uploadedBy: string;
  createdAt: string;
};

// Seed fixtures are DEV/demo ONLY — never ship fabricated schools to production.
// In a production build (NODE_ENV=production) the store starts EMPTY and is
// populated only by real, backend-authoritative server actions (the post-write
// mirror). This is the single global guarantee that no mock school/SSA data
// renders in production, regardless of which of the many planning/analytics/
// directory surfaces reads this store. NODE_ENV is inlined into both the server
// and client bundles, so the guarantee holds on both sides.
const SEED_FIXTURES = process.env.NODE_ENV !== "production";

// Owners are entered as names; the portfolio engine resolves them to registered
// staff. "James Okot" below is intentionally NOT on the roster — it demonstrates
// the IA owner-mapping (unmatched) queue.
const SEED_INTAKE_SCHOOLS: IntakeSchool[] = [
  {
    schoolId: "32791", schoolName: "Nakaseke Hill Primary", region: "Central Region", district: "Nakaseke",
    subCounty: "Nakaseke TC", schoolType: "Client", enrollment: 318, assignedCceo: "Paul Chinyama",
    status: "Active", ssaStatus: "SSA Not Done", planningLocked: true, dateAdded: "2026-02-08", addedBy: "Grace Alimo",
  },
  {
    schoolId: "40118", schoolName: "Soroti Faith Junior", region: "Eastern Region", district: "Soroti",
    subCounty: "Soroti East", schoolType: "Client", enrollment: 402, assignedCceo: "Aisha Dar", status: "Active",
    ssaStatus: "SSA Done", planningLocked: false, dateAdded: "2026-03-14", addedBy: "Grace Alimo",
  },
  {
    schoolId: "51884", schoolName: "Wakiso Grace Academy", region: "Central Region", district: "Wakiso",
    subCounty: "Nansana", schoolType: "Core", enrollment: 540, assignedCceo: "Paul Chinyama",
    status: "Active", ssaStatus: "SSA Done", planningLocked: false, dateAdded: "2026-04-19", addedBy: "Grace Alimo",
  },
  {
    schoolId: "52910", schoolName: "Mukono Light Primary", region: "Central Region", district: "Mukono",
    schoolType: "Client", enrollment: 276, assignedCceo: "Paul Chinyama",
    status: "Active", ssaStatus: "SSA Not Done", planningLocked: true, dateAdded: "2026-05-06", addedBy: "Grace Alimo",
  },
  {
    schoolId: "60233", schoolName: "Gulu Hope Junior", region: "Northern Region", district: "Gulu",
    schoolType: "Client", enrollment: 365, assignedCceo: "James Okot",
    status: "Active", ssaStatus: "SSA Not Done", planningLocked: true, dateAdded: "2026-05-22", addedBy: "Grace Alimo",
  },
  // Near-duplicate of "Nakaseke Hill Primary" (32791) — same district, almost
  // identical name. Both stay live; the duplicate review queue flags it.
  {
    schoolId: "32815", schoolName: "Nakaseke Hills Primary School", region: "Central Region", district: "Nakaseke",
    subCounty: "Nakaseke TC", schoolType: "Client", enrollment: 322, assignedCceo: "Paul Chinyama",
    status: "Active", ssaStatus: "SSA Not Done", planningLocked: true, dateAdded: "2026-05-29", addedBy: "Grace Alimo",
  },
  // ── Wider representative set so the School Directory (source of truth) has
  //    real volume across districts, types, owners, and workflow states. ──
  { schoolId: "61002", schoolName: "Lira Central Primary", region: "Northern Region", district: "Lira", subCounty: "Adyel", schoolType: "Client", enrollment: 410, assignedCceo: "Aisha Dar", status: "Active", ssaStatus: "SSA Not Done", planningLocked: true, dateAdded: "2026-02-11", addedBy: "Grace Alimo" },
  { schoolId: "61015", schoolName: "Lira Hope Junior", region: "Northern Region", district: "Lira", subCounty: "Agweng", schoolType: "Client", enrollment: 288, assignedCceo: "Aisha Dar", status: "Active", ssaStatus: "SSA Done", planningLocked: false, dateAdded: "2026-02-18", addedBy: "Grace Alimo" },
  { schoolId: "61140", schoolName: "Lira Core Demonstration", region: "Northern Region", district: "Lira", subCounty: "Amach", schoolType: "Core", enrollment: 612, assignedCceo: "Aisha Dar", status: "Active", ssaStatus: "SSA Not Done", planningLocked: true, dateAdded: "2026-03-02", addedBy: "Grace Alimo" },
  { schoolId: "70210", schoolName: "Soroti East Primary", region: "Eastern Region", district: "Soroti", subCounty: "Soroti East", schoolType: "Client", enrollment: 357, assignedCceo: "Aisha Dar", status: "Active", ssaStatus: "SSA Not Done", planningLocked: true, dateAdded: "2026-03-09", addedBy: "Grace Alimo" },
  { schoolId: "70233", schoolName: "Arapai Community School", region: "Eastern Region", district: "Soroti", subCounty: "Arapai", schoolType: "Client", enrollment: 244, assignedCceo: "Aisha Dar", status: "Active", ssaStatus: "SSA Done", planningLocked: false, dateAdded: "2026-03-20", addedBy: "Grace Alimo" },
  { schoolId: "33120", schoolName: "Mukono Central Primary", region: "Central Region", district: "Mukono", subCounty: "Mukono Central", schoolType: "Client", enrollment: 398, assignedCceo: "Paul Chinyama", status: "Active", ssaStatus: "SSA Not Done", planningLocked: true, dateAdded: "2026-03-25", addedBy: "Grace Alimo" },
  { schoolId: "33145", schoolName: "Goma Hill Academy", region: "Central Region", district: "Mukono", subCounty: "Goma Division", schoolType: "Core", enrollment: 505, assignedCceo: "Paul Chinyama", status: "Active", ssaStatus: "SSA Done", planningLocked: false, dateAdded: "2026-04-01", addedBy: "Grace Alimo" },
  { schoolId: "33180", schoolName: "Kasawo Junior", region: "Central Region", district: "Mukono", subCounty: "Kasawo", schoolType: "Client", enrollment: 263, assignedCceo: "Paul Chinyama", status: "Active", ssaStatus: "SSA Not Done", planningLocked: true, dateAdded: "2026-04-12", addedBy: "Grace Alimo" },
  { schoolId: "52040", schoolName: "Wakiso Hill Primary", region: "Central Region", district: "Wakiso", subCounty: "Nansana Division", schoolType: "Client", enrollment: 372, assignedCceo: "Paul Chinyama", status: "Active", ssaStatus: "SSA Not Done", planningLocked: true, dateAdded: "2026-04-22", addedBy: "Grace Alimo" },
  { schoolId: "52066", schoolName: "Kira View Academy", region: "Central Region", district: "Wakiso", subCounty: "Kira Division", schoolType: "Client", enrollment: 421, assignedCceo: "Paul Chinyama", status: "Active", ssaStatus: "SSA Done", planningLocked: false, dateAdded: "2026-04-28", addedBy: "Grace Alimo" },
  { schoolId: "80110", schoolName: "Kayunga Bbaale Primary", region: "Central Region", district: "Kayunga", subCounty: "Bbaale", schoolType: "Client", enrollment: 309, assignedCceo: "Sarah Nanyongo", status: "Active", ssaStatus: "SSA Not Done", planningLocked: true, dateAdded: "2026-05-02", addedBy: "Grace Alimo" },
  { schoolId: "80124", schoolName: "Galiraya Junior", region: "Central Region", district: "Kayunga", subCounty: "Galiraya", schoolType: "Client", enrollment: 217, assignedCceo: "Sarah Nanyongo", status: "Active", ssaStatus: "SSA Not Done", planningLocked: true, dateAdded: "2026-05-09", addedBy: "Grace Alimo" },
  { schoolId: "90050", schoolName: "Gulu Pece Primary", region: "Northern Region", district: "Gulu", subCounty: "Pece", schoolType: "Core", enrollment: 588, assignedCceo: "James Okot", status: "Active", ssaStatus: "SSA Not Done", planningLocked: true, dateAdded: "2026-05-15", addedBy: "Grace Alimo" },
  { schoolId: "40250", schoolName: "Arua Hill Primary", region: "Northern Region", district: "Arua", subCounty: "Arua Hill", schoolType: "Client", enrollment: 333, assignedCceo: "Daniel Mwangi", status: "Active", ssaStatus: "SSA Not Done", planningLocked: true, dateAdded: "2026-05-20", addedBy: "Grace Alimo" },
];

export const intakeSchools: IntakeSchool[] = SEED_FIXTURES ? [...SEED_INTAKE_SCHOOLS] : [];

export const ssaUploads: SsaUpload[] = [];

const KNOWN_ID = (id: string) => intakeSchools.some((s) => s.schoolId === id);

export function intakeSchoolIds(): Set<string> {
  return new Set(intakeSchools.map((s) => s.schoolId));
}

/** Set a school's Account Owner (assigned CCEO). IA school-assignment workflow. */
export function assignSchoolToCceo(schoolId: string, cceoName: string): IntakeSchool | undefined {
  const s = intakeSchools.find((x) => x.schoolId === schoolId);
  if (s) s.assignedCceo = cceoName;
  return s;
}

export function addIntakeSchool(
  s: Omit<IntakeSchool, "status" | "ssaStatus" | "planningLocked" | "clusterStatus">,
): IntakeSchool {
  // A freshly uploaded school is unclustered until staff assigns it to a
  // cluster — this is what surfaces it in the Unclustered Schools queue and
  // makes "assign to cluster" the next required setup action after upload.
  const row: IntakeSchool = {
    ...s,
    status: "Active",
    ssaStatus: "SSA Not Done",
    planningLocked: true,
    clusterStatus: s.clusterId ? "clustered" : "unclustered",
  };
  intakeSchools.unshift(row);
  return row;
}

export function addSsaUpload(input: {
  schoolId: string;
  ssaDate: string;
  fy: string;
  quarter: string;
  scores: Record<string, number>;
  newEnrollment?: number;
  uploadedBy: string;
  id: string;
}): SsaUpload {
  const row: SsaUpload = {
    id: input.id,
    schoolId: input.schoolId,
    ssaDate: input.ssaDate,
    fy: input.fy,
    quarter: input.quarter,
    averageScore: ssaAverage(input.scores as Partial<Record<SsaInterventionArea, number>>),
    scores: input.scores,
    newEnrollment: input.newEnrollment,
    uploadedBy: input.uploadedBy,
    createdAt: new Date().toISOString(),
  };
  ssaUploads.unshift(row);
  // SSA upload unlocks planning for an intake school + flips SSA status.
  if (KNOWN_ID(input.schoolId)) {
    const s = intakeSchools.find((x) => x.schoolId === input.schoolId)!;
    s.ssaStatus = "SSA Done";
    s.planningLocked = false;
    if (input.newEnrollment !== undefined) s.enrollment = input.newEnrollment;
    // The SSA is now uploaded — any in-progress SSA activation is fulfilled.
    clearSsaActivation(input.schoolId);
  }
  return row;
}
