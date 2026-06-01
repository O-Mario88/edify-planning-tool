// Generic intake engine — field validation, School-ID linkage, CSV mapping.
// Uploads cover: SSA Performance, Activity Tracker, Exam Results. (Visits,
// Trainings, and Expenses are confirmed in existing workflows, not uploaded.)

import { describe, expect, it } from "vitest";
import { getIntakeTemplate, INTAKE_TEMPLATES } from "@/lib/intake/intake-templates";
import { validateIntakeValues, mapIntakeCsv } from "@/lib/intake/intake-validate";

const onboarded = new Set(["32791", "40118"]);

describe("templates", () => {
  it("school-linked templates all carry a School ID field", () => {
    for (const t of INTAKE_TEMPLATES) {
      if (t.schoolLinked) expect(t.fields.some((f) => f.key === "School ID" && f.idKind === "school")).toBe(true);
    }
  });
  it("does NOT include visits / trainings / expenses uploads (those live in their own workflows)", () => {
    const ids = INTAKE_TEMPLATES.map((t) => t.id);
    expect(ids).not.toContain("tpl-school-visits");
    expect(ids).not.toContain("tpl-trainings");
    expect(ids).not.toContain("tpl-expenses");
  });
});

describe("Exam Results — School-ID linkage + score bounds", () => {
  const t = getIntakeTemplate("tpl-exam-results")!;
  const good = { "School ID": "32791", "Exam Date": "2026-04-12", "Class/Level": "P7", "Subject": "Mathematics", "Score": "68", "Pass Rate": "74" };
  it("accepts a complete row linked to an onboarded school", () => {
    expect(validateIntakeValues(t, good, onboarded)).toEqual({});
  });
  it("rejects a School ID that isn't onboarded", () => {
    expect(validateIntakeValues(t, { ...good, "School ID": "99999" }, onboarded)["School ID"]).toMatch(/No onboarded school/);
  });
  it("Score must be 0–100", () => {
    expect(validateIntakeValues(t, { ...good, "Score": "120" }, onboarded)["Score"]).toMatch(/0–100/);
  });
});

describe("Activity tracker requireAnyOf", () => {
  const t = getIntakeTemplate("tpl-activity-tracker")!;
  it("needs at least one date", () => {
    expect(Object.values(validateIntakeValues(t, { "School ID": "32791" }, onboarded)).join()).toMatch(/At least one/);
    expect(validateIntakeValues(t, { "School ID": "32791", "Last Date of Visit": "2026-03-05" }, onboarded)).toEqual({});
  });
});

describe("mapIntakeCsv — exam results", () => {
  const t = getIntakeTemplate("tpl-exam-results")!;
  const HEADER = "School ID,Exam Date,Class/Level,Subject,Score,Pass Rate";
  it("validates each row, flagging unknown schools and bad scores", () => {
    const csv = [
      HEADER,
      "32791,2026-04-12,P7,Mathematics,68,74",
      "99999,2026-04-12,P7,English,55,60",      // unknown school
      "40118,2026-04-12,P6,Science,120,80",     // score > 100
    ].join("\n");
    const r = mapIntakeCsv(t, csv, onboarded);
    expect(r.rows).toHaveLength(3);
    expect(r.rows[0].valid).toBe(true);
    expect(r.rows[1].errors["School ID"]).toMatch(/No onboarded school/);
    expect(r.rows[2].errors["Score"]).toMatch(/0–100/);
    expect(r.validCount).toBe(1);
  });
  it("rejects a file missing required headers", () => {
    expect(mapIntakeCsv(t, "School ID,Subject\n32791,Math", onboarded).headerError).toMatch(/Missing required/);
  });
});
