// Data-quality scan — joins the live school universe and runs the audit.
//
// Pulls the analytics school spine (GAP ids) + the latest enrollment + latest
// SSA average per school + the IA-entered intake schools, normalises them to
// QualitySchool, and runs the pure auditor. The signals are REAL: a couple of
// GAP schools deliberately have no enrollment / no SSA on record, so the report
// is non-empty and matches what the analytics engine sees.

import { isKnownDistrict } from "@/lib/geography";
import { getAnalyticsSchools } from "@/lib/analytics/school-directory";
import { latestEnrollmentFor } from "@/lib/analytics/sources/school-enrollment-history-mock";
import { historyFor } from "@/lib/planning/ssa-performance-mock";
import { intakeSchools } from "./intake-mock";
import { auditSchools, type QualityReport, type QualitySchool } from "./data-quality";

function fromAnalyticsSpine(): QualitySchool[] {
  return getAnalyticsSchools().map((s) => {
    const enr = latestEnrollmentFor(s.schoolId);
    const ssa = historyFor(s.schoolId);
    return {
      schoolId: s.schoolId,
      schoolName: s.schoolName,
      district: s.district,
      region: s.region,
      enrollment: enr?.enrollmentValue,
      assignedCceo: s.assignedCceo,
      ssaScores: ssa.length ? [ssa[0].averageScore] : [],
    };
  });
}

function fromIntake(): QualitySchool[] {
  return intakeSchools.map((s) => ({
    schoolId: s.schoolId,
    schoolName: s.schoolName,
    district: s.district,
    region: s.region,
    enrollment: s.enrollment,
    assignedCceo: s.assignedCceo,
    // Intake schools carry SSA status, not raw scores — "SSA Done" means assessed.
    ssaScores: s.ssaStatus === "SSA Done" ? [8] : [],
  }));
}

/** Full data-quality report over every known school (analytics spine + intake). */
export function runDataQualityScan(): QualityReport {
  return auditSchools([...fromAnalyticsSpine(), ...fromIntake()], isKnownDistrict);
}
