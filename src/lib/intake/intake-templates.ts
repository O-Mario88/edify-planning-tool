// Generic intake template model — the single source of truth for the data the
// IA team uploads, beyond school onboarding.
//
// Every template here is field-described, so ONE generic engine can render both
// a manual form AND a CSV preview/validator for it (see intake-validate.ts and
// the IntakeUploadDrawer). Rule the program enforces: any data ABOUT a school
// must carry the School ID so it links to an already-onboarded school.

import { SSA_INTERVENTION_AREAS } from "./intake-core";
import type { IdKind } from "./id-formats";

export type FieldType = "text" | "number" | "date" | "select" | "score" | "id";

export type TemplateField = {
  key: string;            // column header AND form key, e.g. "School ID"
  label: string;
  type: FieldType;
  required?: boolean;
  options?: readonly string[]; // for select
  idKind?: IdKind;             // for type "id" — which format to enforce
  min?: number;
  max?: number;
  placeholder?: string;
  example?: string | number;
};

export type IntakeTemplate = {
  id: string;
  name: string;
  description: string;
  /** This data is ABOUT a school → its School ID must match an onboarded school. */
  schoolLinked: boolean;
  /** This template CREATES schools → its School ID must be new/unique (onboarding). */
  createsSchool?: boolean;
  /** Key of this entity's own ID (Visit/Training/Expense) for in-file dup checks. */
  ownIdField?: string;
  /** At least one of these keys must be present per row (e.g. activity dates). */
  requireAnyOf?: string[];
  fields: TemplateField[];
};

const schoolIdField: TemplateField = {
  key: "School ID", label: "School ID", type: "id", idKind: "school", required: true, example: "32791",
};

const ssaScoreFields: TemplateField[] = SSA_INTERVENTION_AREAS.map((area) => ({
  key: area, label: area, type: "score", required: true, min: 0, max: 10, example: 7,
}));

export const INTAKE_TEMPLATES: IntakeTemplate[] = [
  {
    id: "tpl-ssa-performance",
    name: "SSA Performance",
    description: "A school's SSA assessment. FY + quarter are derived from the Assessment Date. One row per assessment.",
    schoolLinked: true,
    fields: [
      schoolIdField,
      { key: "Assessment Date", label: "Assessment Date", type: "date", required: true, example: "2026-02-10" },
      ...ssaScoreFields,
      { key: "Enrolment", label: "Enrolment", type: "number", min: 0, required: false, example: 335 },
    ],
  },
  {
    id: "tpl-activity-tracker",
    name: "Activity & Engagement Tracker",
    description: "Latest engagement dates per school — these drive the FY operating cycle (reset every October 1).",
    schoolLinked: true,
    requireAnyOf: ["Last Date of Training", "Last Date of Visit", "Last Date of Exam Result"],
    fields: [
      schoolIdField,
      { key: "Last Date of Training", label: "Last Date of Training", type: "date", example: "2026-01-20" },
      { key: "Last Date of Visit", label: "Last Date of Visit", type: "date", example: "2026-03-05" },
      { key: "Last Date of Exam Result", label: "Last Date of Exam Result", type: "date", example: "2026-04-12" },
    ],
  },
  {
    id: "tpl-exam-results",
    name: "Exam Results",
    description: "Exam outcomes for a school. One row per subject/sitting.",
    schoolLinked: true,
    fields: [
      schoolIdField,
      { key: "Exam Date", label: "Exam Date", type: "date", required: true, example: "2026-04-12" },
      { key: "Class/Level", label: "Class / Level", type: "text", required: true, example: "P7" },
      { key: "Subject", label: "Subject", type: "text", required: true, example: "Mathematics" },
      { key: "Score", label: "Score (%)", type: "number", min: 0, max: 100, required: true, example: 68 },
      { key: "Pass Rate", label: "Pass Rate (%)", type: "number", min: 0, max: 100, example: 74 },
    ],
  },
];

// Visits, Trainings, and Expenses are NOT uploaded here — they're confirmed
// inside existing workflows (visits/trainings in Salesforce; expenses in the
// fund-accountability workflow, reconciled against NetSuite). See
// FundAccountabilityCenter for the expense/NetSuite-ID capture.

export function getIntakeTemplate(id: string): IntakeTemplate | undefined {
  return INTAKE_TEMPLATES.find((t) => t.id === id);
}

export function requiredColumns(t: IntakeTemplate): string[] {
  return t.fields.filter((f) => f.required).map((f) => f.key);
}
export function optionalColumns(t: IntakeTemplate): string[] {
  return t.fields.filter((f) => !f.required).map((f) => f.key);
}
