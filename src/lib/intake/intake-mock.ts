// Data-intake store — schools + SSA performance uploaded by IA/Admin.
//
// Mutable in-memory store (mock mode persists for the running server session;
// Year-2 swaps for Prisma writes). Client-safe so the intake surface can render
// the "recently added" lists without a round-trip.

import { ssaAverage, type SchoolType, type SsaInterventionArea } from "./intake-core";

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
  cluster?: string;
  status: "Active";
  ssaStatus: "SSA Not Done" | "SSA Done";
  planningLocked: boolean;
  dateAdded: string;
  addedBy: string;
};

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

// A couple of seed rows so the surface isn't empty on first load.
export const intakeSchools: IntakeSchool[] = [
  {
    schoolId: "32791", schoolName: "Nakaseke Hill Primary", region: "Central Region", district: "Nakaseke",
    subCounty: "Nakaseke TC", schoolType: "Client", enrollment: 318, assignedCceo: "Aisha Dar",
    status: "Active", ssaStatus: "SSA Not Done", planningLocked: true, dateAdded: "2026-02-08", addedBy: "Grace Alimo",
  },
  {
    schoolId: "40118", schoolName: "Soroti Faith Junior", region: "Eastern Region", district: "Soroti",
    subCounty: "Soroti East", schoolType: "Client", enrollment: 402, status: "Active",
    ssaStatus: "SSA Done", planningLocked: false, dateAdded: "2026-03-14", addedBy: "Grace Alimo",
  },
];

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

export function addIntakeSchool(s: Omit<IntakeSchool, "status" | "ssaStatus" | "planningLocked">): IntakeSchool {
  const row: IntakeSchool = { ...s, status: "Active", ssaStatus: "SSA Not Done", planningLocked: true };
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
  }
  return row;
}
