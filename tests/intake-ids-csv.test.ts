// ID formats + School Onboarding CSV parse/validate.

import { describe, expect, it } from "vitest";
import { isValidId, idFormatError } from "@/lib/intake/id-formats";
import { parseCsv, mapSchoolCsv } from "@/lib/intake/school-csv";

describe("ID formats", () => {
  it("School ID is digits only (e.g. 32791)", () => {
    expect(isValidId("school", "32791")).toBe(true);
    expect(isValidId("school", "6161")).toBe(true);
    expect(isValidId("school", "SCH-IA-2001")).toBe(false);
    expect(isValidId("school", "abc")).toBe(false);
    expect(isValidId("school", "12")).toBe(false); // too short
  });
  it("Visit ID is SVE-##### (e.g. SVE-88273)", () => {
    expect(isValidId("visit", "SVE-88273")).toBe(true);
    expect(isValidId("visit", "88273")).toBe(false);
    expect(isValidId("visit", "TS-88273")).toBe(false);
  });
  it("Training ID is TS-##### (e.g. TS-50294)", () => {
    expect(isValidId("training", "TS-50294")).toBe(true);
    expect(isValidId("training", "50294")).toBe(false);
  });
  it("Expense ID is digits only (e.g. 6161)", () => {
    expect(isValidId("expense", "6161")).toBe(true);
    expect(isValidId("expense", "EXP-6161")).toBe(false);
  });
  it("idFormatError returns a message or null", () => {
    expect(idFormatError("school", "")).toMatch(/required/);
    expect(idFormatError("school", "abc")).toMatch(/digits/);
    expect(idFormatError("school", "32791")).toBeNull();
  });
});

describe("parseCsv", () => {
  it("handles quotes, escaped quotes, and commas in fields", () => {
    const grid = parseCsv(`a,b\n"x,y","he said ""hi"""\n`);
    expect(grid).toEqual([["a", "b"], ["x,y", 'he said "hi"']]);
  });
  it("drops fully-empty rows", () => {
    expect(parseCsv("a,b\n\n\nc,d")).toEqual([["a", "b"], ["c", "d"]]);
  });
});

const HEADER = "Account Owner,School ID,School Name,District,Current Partner Type,Enrolment,Last Date of Enrolment";

describe("mapSchoolCsv", () => {
  it("rejects a file missing required headers", () => {
    const r = mapSchoolCsv("School Name,District\nFoo,Wakiso", new Set());
    expect(r.headerError).toMatch(/Missing required column/);
  });
  it("validates rows: good row passes, derives region from district", () => {
    const csv = `${HEADER}\nAisha Dar,51230,St. Mary,Wakiso,Client,320,2026-02-01`;
    const r = mapSchoolCsv(csv, new Set());
    expect(r.rows).toHaveLength(1);
    expect(r.rows[0].valid).toBe(true);
    expect(r.rows[0].input.region).toMatch(/Region/); // regionLabel(...)
    expect(r.validCount).toBe(1);
  });
  it("flags a bad School ID format", () => {
    const csv = `${HEADER}\nAisha Dar,SCH-IA-1,St. Mary,Wakiso,Client,320,2026-02-01`;
    const r = mapSchoolCsv(csv, new Set());
    expect(r.rows[0].valid).toBe(false);
    expect(r.rows[0].errors.schoolId).toMatch(/digits/);
  });
  it("flags an unknown district (region can't derive) and bad partner type", () => {
    const csv = `${HEADER}\nAisha Dar,51230,St. Mary,Atlantis,Sponsor,320,2026-02-01`;
    const r = mapSchoolCsv(csv, new Set());
    expect(r.rows[0].errors.district).toMatch(/Unknown district/);
    expect(r.rows[0].errors.schoolType).toMatch(/Client or Core/);
  });
  it("catches in-batch duplicate ids and existing ids", () => {
    const csv = `${HEADER}\nA,51230,One,Wakiso,Client,10,2026-02-01\nB,51230,Two,Wakiso,Core,20,2026-02-01`;
    const r = mapSchoolCsv(csv, new Set());
    expect(r.rows[0].valid).toBe(true);
    expect(r.rows[1].valid).toBe(false); // dup of row 1
    const r2 = mapSchoolCsv(`${HEADER}\nA,32791,One,Wakiso,Client,10,2026-02-01`, new Set(["32791"]));
    expect(r2.rows[0].errors.schoolId).toMatch(/already exists/);
  });
});
