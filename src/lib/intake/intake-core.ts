// Data-intake core — pure validation + FY/quarter derivation.
//
// Backs the IA/Admin "Add School" + "Upload SSA performance" workflows. Pure &
// client-safe (used by the drawers for inline validation AND by the server
// actions). Data intake is restricted to Impact Assessment + Admin — CD sets
// cost/price, not master data.

import { endYearForDate } from "@/lib/fy/fy-core";

/** Roles allowed to upload master data (schools, SSA). IA + Admin only. */
export const DATA_INTAKE_ROLES = ["ImpactAssessment", "Admin"] as const;

export function canIntakeData(role: string): boolean {
  return (DATA_INTAKE_ROLES as readonly string[]).includes(role);
}

/** The 8 SSA intervention areas (canonical, matches the geography/spec list). */
export const SSA_INTERVENTION_AREAS = [
  "Teaching & Learning",
  "Financial Health",
  "Christlike Behaviour",
  "Exposure to the Word of God",
  "Government Requirements & Compliance",
  "Leadership",
  "Education Technology",
  "Learning Environment",
] as const;

export type SsaInterventionArea = (typeof SSA_INTERVENTION_AREAS)[number];

export type SchoolType = "Client" | "Core" | "Potential Core" | "Other";

/** FY id ("2026") for an SSA/intake date — Oct 1 starts the next FY. */
export function deriveFyFromDate(iso: string): string {
  return String(endYearForDate(iso));
}

/** Quarter ("Q1".."Q4") for a date — Q1 Oct-Dec, Q2 Jan-Mar, Q3 Apr-Jun, Q4 Jul-Sep. */
export function deriveQuarterFromDate(iso: string): "Q1" | "Q2" | "Q3" | "Q4" {
  const m = Number(iso.slice(5, 7));
  if (m >= 10 && m <= 12) return "Q1";
  if (m >= 1 && m <= 3) return "Q2";
  if (m >= 4 && m <= 6) return "Q3";
  return "Q4";
}

export type NewSchoolInput = {
  schoolId: string;
  schoolName: string;
  region: string;
  district: string;
  subCounty?: string;
  parish?: string;
  schoolType: SchoolType;
  enrollment?: string | number;
  assignedCceo?: string;
  cluster?: string;
};

export type ValidationResult = { ok: boolean; errors: Record<string, string> };

function isNumericOk(v: string | number | undefined): boolean {
  if (v === undefined || v === "") return true; // optional
  const n = Number(v);
  return Number.isFinite(n) && n >= 0;
}

/** Validate a new-school submission against the existing school-id set. */
export function validateNewSchool(input: NewSchoolInput, existingIds: ReadonlySet<string>): ValidationResult {
  const errors: Record<string, string> = {};
  if (!input.schoolId?.trim()) errors.schoolId = "School ID is required.";
  else if (existingIds.has(input.schoolId.trim())) errors.schoolId = "A school with this ID already exists.";
  if (!input.schoolName?.trim()) errors.schoolName = "School name is required.";
  if (!input.region?.trim()) errors.region = "Region is required.";
  if (!input.district?.trim()) errors.district = "District is required.";
  if (!isNumericOk(input.enrollment)) errors.enrollment = "Enrollment must be a number.";
  return { ok: Object.keys(errors).length === 0, errors };
}

export type SsaUploadInput = {
  schoolId: string;
  ssaDate: string; // ISO
  newEnrollment?: string | number;
  scores: Partial<Record<SsaInterventionArea, number | string>>;
};

/** Validate an SSA upload — date required, every score 0–10, enrollment numeric. */
export function validateSsaUpload(input: SsaUploadInput): ValidationResult {
  const errors: Record<string, string> = {};
  if (!input.schoolId?.trim()) errors.schoolId = "Select a school.";
  if (!input.ssaDate?.trim()) errors.ssaDate = "Date of SSA is required.";
  if (!isNumericOk(input.newEnrollment)) errors.newEnrollment = "Enrollment must be a number.";
  for (const area of SSA_INTERVENTION_AREAS) {
    const raw = input.scores[area];
    if (raw === undefined || raw === "") {
      errors[area] = "Required.";
      continue;
    }
    const n = Number(raw);
    if (!Number.isFinite(n) || n < 0 || n > 10) errors[area] = "0–10 only.";
  }
  return { ok: Object.keys(errors).length === 0, errors };
}

/** Average of the 8 intervention scores (rounded to 1dp). */
export function ssaAverage(scores: Partial<Record<SsaInterventionArea, number | string>>): number {
  const vals = SSA_INTERVENTION_AREAS.map((a) => Number(scores[a])).filter((n) => Number.isFinite(n));
  if (vals.length === 0) return 0;
  return Math.round((vals.reduce((s, n) => s + n, 0) / vals.length) * 10) / 10;
}
