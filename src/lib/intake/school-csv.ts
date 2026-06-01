// School-onboarding CSV — pure parse + map + per-row validation.
//
// Backs the "Add school → CSV upload" path for long lists. Parses the School
// Onboarding Register template (headers + rows), maps each row to a
// NewSchoolInput (deriving region from district), and validates it — including
// the School ID format and in-batch duplicate detection. Pure & client-safe so
// the drawer can preview before anything is sent to the server.

import { regionForDistrict, regionLabel } from "@/lib/geography";
import { validateNewSchool, type NewSchoolInput, type SchoolType } from "./intake-core";

/** Header → NewSchoolInput field. Matches the School Onboarding template. */
export const SCHOOL_CSV_HEADERS = [
  "Account Owner",
  "School ID",
  "School Name",
  "District",
  "Current Partner Type",
  "Enrolment",
  "Last Date of Enrolment",
  "Phone",
  "Primary Contact",
  "School Shipping Address",
] as const;

export type ParsedSchoolRow = {
  rowNumber: number;           // 1-based, excludes the header row
  input: NewSchoolInput;
  raw: Record<string, string>;
  errors: Record<string, string>;
  valid: boolean;
};

export type SchoolCsvResult = {
  headerError?: string;
  rows: ParsedSchoolRow[];
  validCount: number;
};

/** Minimal RFC-4180-ish CSV parser: handles quotes, escaped quotes, commas, CRLF. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else field += c;
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      row.push(field); field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field); field = "";
      rows.push(row); row = [];
    } else field += c;
  }
  if (field.length > 0 || row.length > 0) { row.push(field); rows.push(row); }
  // Drop fully-empty trailing rows.
  return rows.filter((r) => r.some((c) => c.trim() !== ""));
}

function partnerType(raw: string): SchoolType | undefined {
  const v = raw.trim().toLowerCase();
  if (v === "client") return "Client";
  if (v === "core") return "Core";
  return undefined;
}

/** Parse + validate a School Onboarding CSV against the existing school-id set. */
export function mapSchoolCsv(text: string, existingIds: ReadonlySet<string>): SchoolCsvResult {
  const grid = parseCsv(text);
  if (grid.length === 0) return { headerError: "The file is empty.", rows: [], validCount: 0 };

  const header = grid[0].map((h) => h.trim());
  const required = ["School ID", "School Name", "District", "Current Partner Type"];
  const missing = required.filter((h) => !header.includes(h));
  if (missing.length > 0) {
    return { headerError: `Missing required column(s): ${missing.join(", ")}. Download the template for the exact headers.`, rows: [], validCount: 0 };
  }
  const col = (name: string) => header.indexOf(name);
  const cell = (cells: string[], name: string) => (col(name) >= 0 ? (cells[col(name)] ?? "").trim() : "");

  // Track ids seen earlier in THIS file so duplicates inside the batch are caught.
  const seenInBatch = new Set<string>(existingIds);
  const rows: ParsedSchoolRow[] = [];

  for (let r = 1; r < grid.length; r++) {
    const cells = grid[r];
    const district = cell(cells, "District");
    const region = regionForDistrict(district);
    const type = partnerType(cell(cells, "Current Partner Type"));

    const input: NewSchoolInput = {
      schoolId: cell(cells, "School ID"),
      schoolName: cell(cells, "School Name"),
      district,
      region: region ? regionLabel(region) : "",
      schoolType: type ?? "Other",
      enrollment: cell(cells, "Enrolment"),
      assignedCceo: cell(cells, "Account Owner"),
    };

    const v = validateNewSchool(input, seenInBatch);
    const errors = { ...v.errors };
    if (!region && district) errors.district = `Unknown district "${district}" — region can't be derived.`;
    if (!type) errors.schoolType = "Current Partner Type must be Client or Core.";

    const valid = Object.keys(errors).length === 0;
    if (valid) seenInBatch.add(input.schoolId.trim());

    rows.push({
      rowNumber: r,
      input,
      raw: Object.fromEntries(SCHOOL_CSV_HEADERS.map((h) => [h, cell(cells, h)])),
      errors,
      valid,
    });
  }

  return { rows, validCount: rows.filter((r) => r.valid).length };
}
