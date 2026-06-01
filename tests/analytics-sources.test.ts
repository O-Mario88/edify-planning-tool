// Source-mock integrity for the analytics engine.

import { describe, expect, it } from "vitest";
import { analyticsSchoolById, getAnalyticsSchools } from "@/lib/analytics/school-directory";
import { enrollmentHistoryMock } from "@/lib/analytics/sources/school-enrollment-history-mock";
import { trainingParticipantMock } from "@/lib/analytics/sources/training-participant-mock";
import { examPerformanceMock } from "@/lib/analytics/sources/exam-performance-mock";
import { mscMock } from "@/lib/analytics/sources/msc-mock";
import { salesforceVerificationMock } from "@/lib/analytics/sources/salesforce-verification-mock";
import { rawActivities, ACTIVITY_TYPE_LABEL } from "@/lib/planning/school-activity-mock";
import { salesforceKindFor, SF_PREFIX } from "@/lib/salesforce-id";

const KNOWN = new Set(getAnalyticsSchools().map((s) => s.schoolId));
const ACT_IDS = new Set(rawActivities.map((a) => a.id));

describe("every source row resolves to a directory school", () => {
  it("enrollment / participants / exam / msc schoolIds are known", () => {
    for (const r of enrollmentHistoryMock) expect(KNOWN.has(r.schoolId), r.schoolId).toBe(true);
    for (const r of trainingParticipantMock) expect(KNOWN.has(r.schoolId), r.schoolId).toBe(true);
    for (const r of examPerformanceMock) expect(KNOWN.has(r.schoolId), r.schoolId).toBe(true);
    for (const r of mscMock) expect(KNOWN.has(r.schoolId), r.schoolId).toBe(true);
  });
});

describe("salesforce verification records", () => {
  it("reference real activities and obey the SV-/TS- prefix rule", () => {
    for (const r of salesforceVerificationMock) {
      expect(ACT_IDS.has(r.activityId), r.activityId).toBe(true);
      const a = rawActivities.find((x) => x.id === r.activityId)!;
      const correct = SF_PREFIX[salesforceKindFor(ACTIVITY_TYPE_LABEL[a.activityType])];
      // isValid exactly when the prefix matches the activity's SF object kind.
      expect(r.isValid).toBe(r.prefix === correct);
      expect(r.salesforceId.startsWith(r.prefix)).toBe(true);
    }
  });
  it("includes at least one invalid (wrong-prefix) record to exercise the gate", () => {
    expect(salesforceVerificationMock.some((r) => !r.isValid)).toBe(true);
  });
});

describe("data-quality fixtures", () => {
  it("at least two schools have no enrollment row, and ≥2 exams uncollected", () => {
    const withEnrollment = new Set(enrollmentHistoryMock.map((r) => r.schoolId));
    const missing = getAnalyticsSchools().filter((s) => !withEnrollment.has(s.schoolId));
    expect(missing.length).toBeGreaterThanOrEqual(2);
    expect(examPerformanceMock.filter((e) => !e.collected).length).toBeGreaterThanOrEqual(2);
  });
  it("a participant identityKey repeats across two trainings (dedup target)", () => {
    const keys = trainingParticipantMock.map((p) => p.identityKey);
    expect(new Set(keys).size).toBeLessThan(keys.length);
  });
  it("directory resolves names", () => {
    expect(analyticsSchoolById("GAP-NTR-2")?.district).toBe("Mukono");
  });
});
