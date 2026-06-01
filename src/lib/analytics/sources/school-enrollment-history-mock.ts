// School enrollment history — time-series enrollment per school.
//
// "Learners impacted" sums the LATEST valid enrollment over the unique reached
// schools (no double-count per activity). Two schools intentionally have NO row
// so the engine can report a real "missing enrollment" data-quality count.
// Tagged to FY2026 so it aligns with the current operational filter. Pure.

export type EnrollmentSource = "SSA_UPLOAD" | "IMPORT" | "MANUAL";

export type SchoolEnrollmentHistory = {
  id: string;
  schoolId: string;
  enrollmentValue: number;
  enrollmentDate: string; // ISO
  fy: string; // "FY2026"
  quarter: "Q1" | "Q2" | "Q3" | "Q4";
  source: EnrollmentSource;
  uploadedBy: string;
};

// One or two rows per school (a Q1 import + a Q3 SSA-upload refresh on some).
// GAP-NSSA-3 and GAP-NC-2 deliberately omitted → missing-enrollment path.
export const enrollmentHistoryMock: SchoolEnrollmentHistory[] = [
  { id: "ENR-1",  schoolId: "GAP-NSSA-1", enrollmentValue: 412, enrollmentDate: "2025-11-04", fy: "FY2026", quarter: "Q1", source: "IMPORT", uploadedBy: "IA James Otto" },
  { id: "ENR-2",  schoolId: "GAP-NSSA-2", enrollmentValue: 388, enrollmentDate: "2025-11-04", fy: "FY2026", quarter: "Q1", source: "IMPORT", uploadedBy: "IA James Otto" },
  { id: "ENR-3",  schoolId: "GAP-NTR-1",  enrollmentValue: 521, enrollmentDate: "2025-11-08", fy: "FY2026", quarter: "Q1", source: "IMPORT", uploadedBy: "IA James Otto" },
  { id: "ENR-4",  schoolId: "GAP-NTR-1",  enrollmentValue: 540, enrollmentDate: "2026-04-18", fy: "FY2026", quarter: "Q3", source: "SSA_UPLOAD", uploadedBy: "IA James Otto" },
  { id: "ENR-5",  schoolId: "GAP-NTR-2",  enrollmentValue: 603, enrollmentDate: "2025-11-08", fy: "FY2026", quarter: "Q1", source: "IMPORT", uploadedBy: "IA James Otto" },
  { id: "ENR-6",  schoolId: "GAP-NTR-2",  enrollmentValue: 618, enrollmentDate: "2026-05-02", fy: "FY2026", quarter: "Q3", source: "SSA_UPLOAD", uploadedBy: "IA James Otto" },
  { id: "ENR-7",  schoolId: "GAP-NTR-3",  enrollmentValue: 447, enrollmentDate: "2025-11-08", fy: "FY2026", quarter: "Q1", source: "IMPORT", uploadedBy: "IA James Otto" },
  { id: "ENR-8",  schoolId: "GAP-NTR-4",  enrollmentValue: 392, enrollmentDate: "2025-11-12", fy: "FY2026", quarter: "Q1", source: "IMPORT", uploadedBy: "IA James Otto" },
  { id: "ENR-9",  schoolId: "GAP-NV-1",   enrollmentValue: 274, enrollmentDate: "2025-11-12", fy: "FY2026", quarter: "Q1", source: "IMPORT", uploadedBy: "IA James Otto" },
  { id: "ENR-10", schoolId: "GAP-NV-2",   enrollmentValue: 356, enrollmentDate: "2025-11-12", fy: "FY2026", quarter: "Q1", source: "IMPORT", uploadedBy: "IA James Otto" },
  { id: "ENR-11", schoolId: "GAP-NV-3",   enrollmentValue: 401, enrollmentDate: "2025-11-15", fy: "FY2026", quarter: "Q1", source: "IMPORT", uploadedBy: "IA James Otto" },
  // GAP-NC-1 (reached via training), GAP-NSSA-3, and GAP-NC-2 intentionally
  // have NO enrollment row → exercises the missing-enrollment data-quality path.
];

const BY_SCHOOL = new Map<string, SchoolEnrollmentHistory[]>();
for (const r of enrollmentHistoryMock) {
  const list = BY_SCHOOL.get(r.schoolId) ?? [];
  list.push(r);
  BY_SCHOOL.set(r.schoolId, list);
}

/** Latest enrollment for a school on/before `asOf` (ISO). Undefined = no data. */
export function latestEnrollmentFor(
  schoolId: string,
  asOf?: string,
): SchoolEnrollmentHistory | undefined {
  const list = BY_SCHOOL.get(schoolId);
  if (!list || list.length === 0) return undefined;
  const eligible = asOf ? list.filter((r) => r.enrollmentDate <= asOf) : list;
  const pool = eligible.length > 0 ? eligible : list;
  return pool.slice().sort((a, b) => b.enrollmentDate.localeCompare(a.enrollmentDate))[0];
}
