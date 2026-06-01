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
    description: "A school's SSA assessment. FY + quarter are derived from the SSA Date. One row per assessment.",
    schoolLinked: true,
    fields: [
      schoolIdField,
      { key: "SSA Date", label: "SSA Date", type: "date", required: true, example: "2026-02-10" },
      ...ssaScoreFields,
      { key: "Enrolment", label: "Enrolment", type: "number", min: 0, required: true, example: 335 },
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
    id: "tpl-school-visits",
    name: "School Visits",
    // Visits are logged into Salesforce by the partner or staff who made them;
    // in the planning tool the IA/Admin just CONFIRMS the visit happened.
    description: "Confirm a visit already recorded in Salesforce — its ID, when it happened, why, and who visited.",
    schoolLinked: true,
    ownIdField: "Visit ID",
    fields: [
      { key: "Visit ID", label: "Visit ID", type: "id", idKind: "visit", required: true, example: "SVE-88273" },
      schoolIdField,
      { key: "Visit Date", label: "Date the visit happened", type: "date", required: true, example: "2026-03-05" },
      { key: "Reason", label: "Reason", type: "select", required: true, options: ["Routine Monitoring", "Coaching", "Courtesy Visit", "Follow-up", "SSA Assessment"], example: "Coaching" },
      { key: "Visited By", label: "Visited By", type: "select", required: true, options: ["Partner", "CCEO", "Program Lead", "Impact Assessment"], example: "CCEO" },
    ],
  },
  {
    id: "tpl-trainings",
    name: "Trainings",
    // A training is an event with attendance counts — not tied to one school.
    description: "A training event delivered — its name, what it covered, and how many teachers and leaders attended.",
    schoolLinked: false,
    ownIdField: "Training ID",
    fields: [
      { key: "Training ID", label: "Training ID", type: "id", idKind: "training", required: true, example: "TS-50294" },
      { key: "Training Name", label: "Training Name", type: "text", required: true, example: "Term 1 Leadership Institute" },
      { key: "Description", label: "Description", type: "text", example: "Two-day leadership best-practice workshop" },
      { key: "Teachers Trained", label: "# Teachers Trained", type: "number", min: 0, required: true, example: 24 },
      { key: "School Leaders Trained", label: "# School Leaders Trained", type: "number", min: 0, required: true, example: 6 },
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
  {
    id: "tpl-expenses",
    name: "Expenses",
    description: "Spend recorded against a school. One row per expense.",
    schoolLinked: true,
    ownIdField: "Expense ID",
    fields: [
      { key: "Expense ID", label: "Expense ID", type: "id", idKind: "expense", required: true, example: "6161" },
      schoolIdField,
      { key: "Date", label: "Date", type: "date", required: true, example: "2026-02-18" },
      { key: "Category", label: "Category", type: "select", required: true, options: ["Training", "Materials", "Transport", "Stipend", "Other"], example: "Materials" },
      { key: "Amount", label: "Amount", type: "number", min: 0, required: true, example: 250000 },
      { key: "Paid By", label: "Paid By", type: "text", example: "Grace Alimo" },
    ],
  },
];

export function getIntakeTemplate(id: string): IntakeTemplate | undefined {
  return INTAKE_TEMPLATES.find((t) => t.id === id);
}

export function requiredColumns(t: IntakeTemplate): string[] {
  return t.fields.filter((f) => f.required).map((f) => f.key);
}
export function optionalColumns(t: IntakeTemplate): string[] {
  return t.fields.filter((f) => !f.required).map((f) => f.key);
}
