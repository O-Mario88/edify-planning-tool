// Generic intake engine — field validation, School-ID linkage, CSV mapping.

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
});

describe("School Visits — School-ID linkage + own ID format", () => {
  const t = getIntakeTemplate("tpl-school-visits")!;
  const good = { "Visit ID": "SVE-88273", "School ID": "32791", "Visit Date": "2026-03-05", "Visit Type": "Coaching", "Officer": "Aisha Dar", "Outcome": "ok" };
  it("accepts a complete row linked to an onboarded school", () => {
    expect(validateIntakeValues(t, good, onboarded)).toEqual({});
  });
  it("rejects a School ID that isn't onboarded", () => {
    const e = validateIntakeValues(t, { ...good, "School ID": "99999" }, onboarded);
    expect(e["School ID"]).toMatch(/No onboarded school/);
  });
  it("rejects a bad Visit ID format", () => {
    const e = validateIntakeValues(t, { ...good, "Visit ID": "88273" }, onboarded);
    expect(e["Visit ID"]).toMatch(/SVE-/);
  });
  it("rejects a Visit Type outside the option list", () => {
    const e = validateIntakeValues(t, { ...good, "Visit Type": "Party" }, onboarded);
    expect(e["Visit Type"]).toMatch(/one of/);
  });
});

describe("Trainings + Expenses own-ID formats", () => {
  it("Training ID must be TS-#####", () => {
    const t = getIntakeTemplate("tpl-trainings")!;
    const e = validateIntakeValues(t, { "Training ID": "TS-50294", "School ID": "32791", "Training Date": "2026-01-20", "Topic": "X", "Facilitator": "Y" }, onboarded);
    expect(e).toEqual({});
    expect(validateIntakeValues(t, { "Training ID": "50294", "School ID": "32791", "Training Date": "2026-01-20", "Topic": "X", "Facilitator": "Y" }, onboarded)["Training ID"]).toMatch(/TS-/);
  });
  it("Expense ID must be digits; Amount required", () => {
    const t = getIntakeTemplate("tpl-expenses")!;
    const e = validateIntakeValues(t, { "Expense ID": "6161", "School ID": "32791", "Date": "2026-02-18", "Category": "Materials", "Amount": "250000" }, onboarded);
    expect(e).toEqual({});
    expect(validateIntakeValues(t, { "Expense ID": "EXP-1", "School ID": "32791", "Date": "2026-02-18", "Category": "Materials", "Amount": "" }, onboarded)["Amount"]).toBeTruthy();
  });
});

describe("Exam Results score bounds + Activity requireAnyOf", () => {
  it("Score must be 0–100", () => {
    const t = getIntakeTemplate("tpl-exam-results")!;
    const e = validateIntakeValues(t, { "School ID": "32791", "Exam Date": "2026-04-12", "Class/Level": "P7", "Subject": "Math", "Score": "120" }, onboarded);
    expect(e["Score"]).toMatch(/0–100/);
  });
  it("Activity tracker needs at least one date", () => {
    const t = getIntakeTemplate("tpl-activity-tracker")!;
    const e = validateIntakeValues(t, { "School ID": "32791" }, onboarded);
    expect(Object.values(e).join()).toMatch(/At least one/);
    expect(validateIntakeValues(t, { "School ID": "32791", "Last Date of Visit": "2026-03-05" }, onboarded)).toEqual({});
  });
});

describe("mapIntakeCsv — visits", () => {
  const t = getIntakeTemplate("tpl-school-visits")!;
  const HEADER = "Visit ID,School ID,Visit Date,Visit Type,Officer,Outcome";
  it("validates each row and flags in-file duplicate Visit IDs", () => {
    const csv = [
      HEADER,
      "SVE-10001,32791,2026-03-05,Coaching,Aisha,ok",
      "SVE-10001,40118,2026-03-06,Routine,Dan,ok",   // dup visit id
      "SVE-10002,99999,2026-03-07,Routine,Sam,ok",   // unknown school
    ].join("\n");
    const r = mapIntakeCsv(t, csv, onboarded);
    expect(r.rows).toHaveLength(3);
    expect(r.rows[0].valid).toBe(true);
    expect(r.rows[1].errors["Visit ID"]).toMatch(/Duplicate/);
    expect(r.rows[2].errors["School ID"]).toMatch(/No onboarded school/);
    expect(r.validCount).toBe(1);
  });
  it("rejects a file missing required headers", () => {
    expect(mapIntakeCsv(t, "School ID,Visit Date\n32791,2026-03-05", onboarded).headerError).toMatch(/Missing required/);
  });
});
