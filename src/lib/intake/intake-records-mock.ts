// Generic intake record store — holds rows for the field-described templates
// (visits, trainings, exam results, expenses, activity). School onboarding and
// SSA have their own stores/flows; everything else lands here keyed by template.
//
// Mutable in-memory (mock mode); Year-2 swaps for per-entity Salesforce writes.

export type IntakeRecord = {
  id: string;
  templateId: string;
  schoolId: string;
  values: Record<string, string>;
  uploadedBy: string;
  createdAt: string;
};

export const intakeRecords: IntakeRecord[] = [];

let seq = 0;
function nextId(prefix: string): string {
  seq += 1;
  return `${prefix}-${seq}`;
}

export function addIntakeRecords(
  templateId: string,
  rows: Array<Record<string, string>>,
  uploadedBy: string,
): IntakeRecord[] {
  const created = rows.map((values) => ({
    id: nextId("rec"),
    templateId,
    schoolId: values["School ID"] ?? "",
    values,
    uploadedBy,
    createdAt: "2026-06-01T00:00:00.000Z",
  }));
  intakeRecords.unshift(...created);
  return created;
}

export function recordsForTemplate(templateId: string): IntakeRecord[] {
  return intakeRecords.filter((r) => r.templateId === templateId);
}

export function recordCountByTemplate(): Record<string, number> {
  const out: Record<string, number> = {};
  for (const r of intakeRecords) out[r.templateId] = (out[r.templateId] ?? 0) + 1;
  return out;
}
