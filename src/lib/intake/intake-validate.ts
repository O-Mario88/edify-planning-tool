// Generic intake validation — one validator for every field-described template.
//
// Drives BOTH the manual form (validate one row of values) and the CSV upload
// (parse + validate every row). The School-ID-linkage rule lives here: a
// school-linked template's School ID must already exist; an onboarding
// template's School ID must be new.

import { isValidId, ID_FORMATS } from "./id-formats";
import { parseCsv } from "./school-csv";
import { type IntakeTemplate, type TemplateField, requiredColumns } from "./intake-templates";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function fieldError(f: TemplateField, raw: string, t: IntakeTemplate, existingSchoolIds: ReadonlySet<string>): string | null {
  if (!raw) return f.required ? `${f.label} is required.` : null;

  switch (f.type) {
    case "id": {
      if (f.idKind && !isValidId(f.idKind, raw)) return `${f.label} must be ${ID_FORMATS[f.idKind].hint}.`;
      if (f.idKind === "school") {
        if (t.createsSchool && existingSchoolIds.has(raw)) return "A school with this ID already exists.";
        if (t.schoolLinked && !existingSchoolIds.has(raw)) return `No onboarded school with ID ${raw}. Add the school first.`;
      }
      return null;
    }
    case "score":
    case "number": {
      const n = Number(raw);
      const min = f.min ?? 0;
      const max = f.max ?? (f.type === "score" ? 10 : Infinity);
      if (!Number.isFinite(n) || n < min || n > max) {
        return max === Infinity ? `${f.label} must be a number ≥ ${min}.` : `${f.label} must be ${min}–${max}.`;
      }
      return null;
    }
    case "date":
      return DATE_RE.test(raw) ? null : `${f.label} must be a date (YYYY-MM-DD).`;
    case "select":
      return f.options && !f.options.includes(raw) ? `${f.label} must be one of: ${f.options.join(", ")}.` : null;
    default:
      return null;
  }
}

/** Validate one row of values for a template → { field: error }. Empty = valid. */
export function validateIntakeValues(
  t: IntakeTemplate,
  values: Record<string, string>,
  existingSchoolIds: ReadonlySet<string>,
): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const f of t.fields) {
    const e = fieldError(f, (values[f.key] ?? "").trim(), t, existingSchoolIds);
    if (e) errors[f.key] = e;
  }
  if (t.requireAnyOf && t.requireAnyOf.every((k) => !(values[k] ?? "").trim())) {
    errors[t.requireAnyOf[0]] = `At least one of: ${t.requireAnyOf.join(", ")} is required.`;
  }
  return errors;
}

export type ParsedIntakeRow = {
  rowNumber: number;
  values: Record<string, string>;
  errors: Record<string, string>;
  valid: boolean;
};

export type IntakeCsvResult = {
  headerError?: string;
  rows: ParsedIntakeRow[];
  validCount: number;
};

/** Parse + validate a CSV for a template against the existing school-id set. */
export function mapIntakeCsv(
  t: IntakeTemplate,
  text: string,
  existingSchoolIds: ReadonlySet<string>,
): IntakeCsvResult {
  const grid = parseCsv(text);
  if (grid.length === 0) return { headerError: "The file is empty.", rows: [], validCount: 0 };

  const header = grid[0].map((h) => h.trim());
  const missing = requiredColumns(t).filter((h) => !header.includes(h));
  if (missing.length > 0) {
    return { headerError: `Missing required column(s): ${missing.join(", ")}. Download the template for the exact headers.`, rows: [], validCount: 0 };
  }
  const idx = (name: string) => header.indexOf(name);
  const ownIds = new Set<string>();
  const rows: ParsedIntakeRow[] = [];

  for (let r = 1; r < grid.length; r++) {
    const cells = grid[r];
    const values: Record<string, string> = {};
    for (const f of t.fields) {
      const i = idx(f.key);
      values[f.key] = i >= 0 ? (cells[i] ?? "").trim() : "";
    }
    const errors = validateIntakeValues(t, values, existingSchoolIds);

    // In-file duplicate of this entity's own ID.
    if (t.ownIdField && !errors[t.ownIdField]) {
      const own = values[t.ownIdField];
      if (own && ownIds.has(own)) errors[t.ownIdField] = `Duplicate ${t.ownIdField} "${own}" earlier in this file.`;
      else if (own) ownIds.add(own);
    }

    rows.push({ rowNumber: r, values, errors, valid: Object.keys(errors).length === 0 });
  }

  return { rows, validCount: rows.filter((r) => r.valid).length };
}
