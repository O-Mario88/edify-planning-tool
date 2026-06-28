// Data Intake & Readiness Engine.
//
// Contract:
//   • The platform must not depend on random uploads.
//   • Templates are SYSTEM-GENERATED — users do not invent columns.
//   • Uploads are: Uploaded → Validated → Needs Correction / Ready for Review →
//     Approved for Import → Imported → Available to Planning Engine.
//   • Unapproved data CANNOT feed dashboards, recommendations, budgets,
//     targets, leaderboards, or fund requests.
//   • Planning Data Readiness must block / limit the Annual Operating Cycle
//     when critical data is missing.

import "server-only";
import { activeFinancialYear } from "@/lib/fy-engine";
import { validateCountryCostSettings } from "@/lib/cost-settings-mock";
import {
  getIntakeTemplate,
  requiredColumns as reqCols,
  optionalColumns as optCols,
  type IntakeTemplate,
} from "@/lib/intake/intake-templates";

// ────────── Template data type ──────────

export type DataType =
  | "School Register"
  | "Staff Register"
  | "Partner Register"
  | "CCEO Assignment"
  | "Program Lead Assignment"
  | "SSA Results"
  | "Training Records"
  | "Visit Records"
  | "Exam Results"
  | "Enrollment Updates"
  | "MSC Stories"
  | "Core School Package"
  | "Special Projects"
  | "Country Cost Settings"
  | "Target Settings"
  | "Public Holidays"
  | "Leave Blackout Dates"
  | "Salesforce Verification"
  | "Evidence Records"
  | "Activity Tracker"
  | "Expenses";

export const ALL_DATA_TYPES: DataType[] = [
  "School Register", "Staff Register", "Partner Register",
  "CCEO Assignment", "Program Lead Assignment",
  "SSA Results", "Training Records", "Visit Records",
  "Exam Results", "Enrollment Updates", "MSC Stories",
  "Core School Package", "Special Projects",
  "Country Cost Settings", "Target Settings",
  "Public Holidays", "Leave Blackout Dates",
  "Salesforce Verification", "Evidence Records",
];

export type DataTemplate = {
  id:              string;
  name:            string;
  dataType:        DataType;
  description:     string;
  requiredColumns: string[];
  optionalColumns: string[];
  dropdownColumns: Record<string, string[]>;
  exampleRows:     Record<string, string | number>[];
  validationRules: string[];
  createdBy:       string;
  updatedAt:       string;
};

// ────────── Template catalog ──────────

export const dataTemplates: DataTemplate[] = [
  // Three consolidated IA uploads. The platform deliberately keeps the number
  // of uploads small so the Impact Assessment team isn't overwhelmed: one
  // school-onboarding sheet, one SSA-performance sheet, one activity-tracker
  // sheet. Everything the planning engine needs flows from these three.
  {
    id: "tpl-school-onboarding",
    name: "School Onboarding Register",
    dataType: "School Register",
    description: "Onboard schools into the planning engine. Only 4 fields are required to create a school — School ID, School Name, District, and Current Partner Type. Everything else (owner, enrolment, contact, address) can be added later by IA or staff. One row per school.",
    requiredColumns: [
      "School ID",
      "School Name",
      "District",
      "Current Partner Type",
    ],
    optionalColumns: [
      // Added later by IA / staff once the school exists — a row need not carry these.
      "Staff Name",
      "Enrolment",
      "Last Date of Enrolment",
      "Phone",
      "Primary Contact",
      "School Shipping Address",
    ],
    dropdownColumns: {
      "Current Partner Type": ["Client", "Core"],
    },
    exampleRows: [
      {
        "Staff Name": "Aisha Dar",
        "School ID": "51230",
        "School Name": "St. Mary Primary School",
        "District": "Wakiso",
        "Current Partner Type": "Client",
        "Enrolment": 320,
        "Last Date of Enrolment": "2026-02-01",
        "Phone": "+256 700 123456",
        "Primary Contact": "Head Teacher Jane Akello",
        "School Shipping Address": "P.O. Box 12, Wakiso Town",
      },
    ],
    validationRules: [
      "REQUIRED: School ID (digits only, e.g. 32791, unique), School Name, District, Current Partner Type (Client or Core)",
      "OPTIONAL — can be added later by IA or staff: Staff Name, Enrolment, Last Date of Enrolment, Phone, Primary Contact, School Shipping Address",
      "Region is derived automatically from District — you don't enter it",
      "When provided: Enrolment must be a whole number ≥ 0; Last Date of Enrolment must be a valid date; Staff Name should match an active CCEO/PL (unmatched names are queued for Admin setup)",
    ],
    createdBy: "Edify HQ",
    updatedAt: "2026-06-01",
  },
  {
    id: "tpl-ssa-performance",
    name: "SSA Performance",
    dataType: "SSA Results",
    description: "Upload a school's SSA assessment. The fiscal year and quarter are derived automatically from the Assessment Date. One row per assessment.",
    requiredColumns: [
      "School ID",
      "Assessment Date",
      "Teaching & Learning",
      "Financial Health",
      "Christlike Behaviour",
      "Exposure to the Word of God",
      "Government Requirements & Compliance",
      "Leadership",
      "Education Technology",
      "Learning Environment",
    ],
    optionalColumns: [
      "Enrolment",
    ],
    dropdownColumns: {},
    exampleRows: [
      {
        "School ID": "32791",
        "Assessment Date": "2026-02-10",
        "Teaching & Learning": 7,
        "Financial Health": 6,
        "Christlike Behaviour": 8,
        "Exposure to the Word of God": 7,
        "Government Requirements & Compliance": 5,
        "Leadership": 8,
        "Education Technology": 5,
        "Learning Environment": 6,
        "Enrolment": 335,
      },
    ],
    validationRules: [
      "School ID must exist in the School Onboarding Register",
      "Assessment Date must be a valid date — FY and quarter are derived from it",
      "Every performance score must be between 0 and 10",
      "Enrolment must be a whole number ≥ 0",
    ],
    createdBy: "Edify HQ",
    updatedAt: "2026-06-01",
  },
  {
    id: "tpl-activity-tracker",
    name: "Activity & Engagement Tracker",
    dataType: "Activity Tracker",
    description: "Record the latest engagement dates per school — the last training, visit, and exam result. One row per school; leave a cell blank if it hasn't happened yet.",
    requiredColumns: [
      "School ID",
      "Last Date of Training",
      "Last Date of Visit",
      "Last Date of Exam Result",
    ],
    optionalColumns: [],
    dropdownColumns: {},
    exampleRows: [
      {
        "School ID": "32791",
        "Last Date of Training": "2026-01-20",
        "Last Date of Visit": "2026-03-05",
        "Last Date of Exam Result": "2026-04-12",
      },
    ],
    validationRules: [
      "School ID must be digits only, e.g. 32791, and exist in the School Onboarding Register",
      "All dates must be valid and not in the future",
      "Linked IDs follow their formats — Visit SVE-88273, Training TS-50294, Expense 6161",
      "At least one date must be present per row",
    ],
    createdBy: "Edify HQ",
    updatedAt: "2026-06-01",
  },
];

// The school-linked record templates (visits, trainings, exams, expenses) are
// field-described in intake-templates.ts so ONE engine can do manual + CSV. We
// derive their catalog/CSV entries here so the Template Builder + CSV download
// route stay one list with the rest.
const GENERATED_DATA_TYPE: Record<string, DataType> = {
  "tpl-exam-results": "Exam Results",
};

function buildDataTemplate(t: IntakeTemplate, dataType: DataType): DataTemplate {
  const dropdownColumns: Record<string, string[]> = {};
  for (const f of t.fields) if (f.type === "select" && f.options) dropdownColumns[f.key] = [...f.options];
  const exampleRow: Record<string, string | number> = {};
  for (const f of t.fields) if (f.example !== undefined) exampleRow[f.key] = f.example;
  const rules: string[] = [];
  if (t.schoolLinked) rules.push("School ID must be digits only, e.g. 32791, and exist in the School Onboarding Register");
  if (t.ownIdField) {
    const idf = t.fields.find((f) => f.key === t.ownIdField);
    if (idf?.example) rules.push(`${t.ownIdField} must follow its format, e.g. ${idf.example}, and be unique in the file`);
  }
  for (const f of t.fields) {
    if (f.type === "select" && f.options) rules.push(`${f.label} must be one of: ${f.options.join(" / ")}`);
    if ((f.type === "number" || f.type === "score") && (f.min !== undefined || f.max !== undefined)) {
      rules.push(`${f.label} must be ${f.min ?? 0}–${f.max ?? "∞"}`);
    }
  }
  return {
    id: t.id,
    name: t.name,
    dataType,
    description: t.description,
    requiredColumns: reqCols(t),
    optionalColumns: optCols(t),
    dropdownColumns,
    exampleRows: Object.keys(exampleRow).length ? [exampleRow] : [],
    validationRules: rules,
    createdBy: "Edify HQ",
    updatedAt: "2026-06-01",
  };
}

for (const [id, dataType] of Object.entries(GENERATED_DATA_TYPE)) {
  const t = getIntakeTemplate(id);
  if (t) dataTemplates.push(buildDataTemplate(t, dataType));
}

export function getTemplate(id: string): DataTemplate | undefined {
  return dataTemplates.find((t) => t.id === id);
}

// ────────── Import batches ──────────

export type ImportBatchStatus =
  | "Uploaded"
  | "Validated"
  | "Needs Correction"
  | "Ready for Review"
  | "Approved for Import"
  | "Imported"
  | "Rejected";

export type DataImportBatch = {
  id:               string;
  templateId:       string;
  dataType:         DataType;
  sourceFileName:   string;
  uploadedBy:       string;
  uploadedAt:       string;
  status:           ImportBatchStatus;
  totalRows:        number;
  validRows:        number;
  errorRows:        number;
  warningRows:      number;
  reviewedBy?:      string;
  reviewedAt?:      string;
  importedBy?:      string;
  importedAt?:      string;
  validationSummary:{
    missingRequiredFields: number;
    duplicateRecords:      number;
    invalidMappings:       number;
    warnings:              number;
  };
  notes?:           string;
};

export const dataImportBatches: DataImportBatch[] = [
  { id: "imp-1", templateId: "tpl-school-register", dataType: "School Register",       sourceFileName: "SchoolRegister_Q1_FY2526.xlsx", uploadedBy: "Grace Alimo", uploadedAt: "Nov 12, 2025 · 09:15", status: "Imported",            totalRows: 358, validRows: 358, errorRows:   0, warningRows: 4,  reviewedBy: "Grace Alimo", reviewedAt: "Nov 12, 2025 · 11:00", importedBy: "Grace Alimo", importedAt: "Nov 12, 2025 · 11:05", validationSummary: { missingRequiredFields: 0, duplicateRecords: 0, invalidMappings: 0, warnings: 4 } },
  { id: "imp-2", templateId: "tpl-staff-register",  dataType: "Staff Register",        sourceFileName: "StaffRegister_FY2526.xlsx",      uploadedBy: "Grace Alimo", uploadedAt: "Nov 12, 2025 · 09:32", status: "Imported",            totalRows: 142, validRows: 142, errorRows:   0, warningRows: 0,  reviewedBy: "Grace Alimo", reviewedAt: "Nov 12, 2025 · 10:10", importedBy: "Grace Alimo", importedAt: "Nov 12, 2025 · 10:12", validationSummary: { missingRequiredFields: 0, duplicateRecords: 0, invalidMappings: 0, warnings: 0 } },
  { id: "imp-3", templateId: "tpl-cost-settings",   dataType: "Country Cost Settings", sourceFileName: "CostSettings_FY2526_v3.xlsx",    uploadedBy: "Moses Tindi", uploadedAt: "Nov 13, 2025 · 14:40", status: "Ready for Review",    totalRows:  17, validRows:  15, errorRows:   0, warningRows: 2,  validationSummary: { missingRequiredFields: 0, duplicateRecords: 0, invalidMappings: 0, warnings: 2 }, notes: "Evidence verification + Partner travel support left Draft." },
  { id: "imp-4", templateId: "tpl-ssa-results",     dataType: "SSA Results",           sourceFileName: "SSA_Nov2025_Batch1.xlsx",         uploadedBy: "Grace Alimo", uploadedAt: "Nov 14, 2025 · 11:05", status: "Validated",           totalRows: 122, validRows: 119, errorRows:   3, warningRows: 8,  validationSummary: { missingRequiredFields: 1, duplicateRecords: 0, invalidMappings: 2, warnings: 8 } },
  { id: "imp-5", templateId: "tpl-training-records",dataType: "Training Records",      sourceFileName: "Trainings_Oct2025.xlsx",         uploadedBy: "Grace Alimo", uploadedAt: "Nov 10, 2025 · 16:20", status: "Needs Correction",    totalRows:  64, validRows:  58, errorRows:   6, warningRows: 2,  validationSummary: { missingRequiredFields: 3, duplicateRecords: 1, invalidMappings: 2, warnings: 2 }, notes: "6 rows reference Salesforce IDs that don't exist." },
  { id: "imp-6", templateId: "tpl-partner-register",dataType: "Partner Register",      sourceFileName: "Partners_FY2526.xlsx",            uploadedBy: "Grace Alimo", uploadedAt: "Nov 09, 2025 · 12:00", status: "Imported",            totalRows:  18, validRows:  18, errorRows:   0, warningRows: 0,  reviewedBy: "Grace Alimo", reviewedAt: "Nov 09, 2025 · 12:30", importedBy: "Grace Alimo", importedAt: "Nov 09, 2025 · 12:31", validationSummary: { missingRequiredFields: 0, duplicateRecords: 0, invalidMappings: 0, warnings: 0 } },
  { id: "imp-7", templateId: "tpl-public-holidays", dataType: "Public Holidays",       sourceFileName: "PublicHolidays_2025.xlsx",        uploadedBy: "Edify HQ",    uploadedAt: "Sep 25, 2025 · 09:00", status: "Imported",            totalRows:  11, validRows:  11, errorRows:   0, warningRows: 0,  reviewedBy: "Edify HQ",    reviewedAt: "Sep 25, 2025 · 09:10", importedBy: "Edify HQ",    importedAt: "Sep 25, 2025 · 09:11", validationSummary: { missingRequiredFields: 0, duplicateRecords: 0, invalidMappings: 0, warnings: 0 } },
  { id: "imp-8", templateId: "tpl-targets",         dataType: "Target Settings",       sourceFileName: "Targets_FY2526_Draft.xlsx",      uploadedBy: "Moses Tindi", uploadedAt: "Nov 14, 2025 · 08:30", status: "Uploaded",            totalRows:  84, validRows:   0, errorRows:   0, warningRows: 0,  validationSummary: { missingRequiredFields: 0, duplicateRecords: 0, invalidMappings: 0, warnings: 0 } },
];

// ────────── Readiness ──────────

export type ReadinessStatus = "Ready" | "Needs Attention" | "Blocked";

export type DataReadinessRow = {
  area:              string;
  status:            ReadinessStatus;
  latestBatchStatus: ImportBatchStatus | "—";
  note:              string;
};

const FY = activeFinancialYear();

// Compute the readiness status for each required area by looking at the
// latest import batch + the cost-settings validator.
function latestBatchFor(dataType: DataType): DataImportBatch | undefined {
  return [...dataImportBatches]
    .filter((b) => b.dataType === dataType)
    .sort((a, b) => (a.uploadedAt < b.uploadedAt ? 1 : -1))[0];
}

function statusFromBatch(b?: DataImportBatch): { status: ReadinessStatus; note: string } {
  if (!b)                              return { status: "Blocked",         note: "No data uploaded yet" };
  if (b.status === "Imported")         return { status: "Ready",           note: `${b.validRows} rows imported · ${b.warningRows} warnings` };
  if (b.status === "Ready for Review") return { status: "Needs Attention", note: `${b.validRows}/${b.totalRows} rows ready · awaiting review` };
  if (b.status === "Validated")        return { status: "Needs Attention", note: `${b.errorRows} errors · ${b.warningRows} warnings` };
  if (b.status === "Needs Correction") return { status: "Blocked",         note: `${b.errorRows} errors to fix` };
  if (b.status === "Uploaded")         return { status: "Needs Attention", note: "Awaiting validation" };
  if (b.status === "Rejected")         return { status: "Blocked",         note: b.notes ?? "Rejected" };
  return                                    { status: "Needs Attention", note: "Awaiting next step" };
}

export function planningDataReadiness(): {
  rows:           DataReadinessRow[];
  overall:        ReadinessStatus;
  blockingIssues: string[];
} {
  const rows: DataReadinessRow[] = [];
  const blockingIssues: string[] = [];

  const push = (area: string, dt: DataType) => {
    const b   = latestBatchFor(dt);
    const r   = statusFromBatch(b);
    rows.push({ area, status: r.status, latestBatchStatus: b?.status ?? "—", note: r.note });
    if (r.status === "Blocked") blockingIssues.push(`${area}: ${r.note}`);
  };

  push("School Register",     "School Register");
  push("Staff Register",      "Staff Register");
  push("Partner Register",    "Partner Register");
  push("SSA Data",            "SSA Results");
  push("Training Records",    "Training Records");
  push("Public Holidays",     "Public Holidays");
  push("Target Settings",     "Target Settings");

  // Cost settings: use the dedicated validator instead of relying on a batch.
  const cs = validateCountryCostSettings();
  rows.push({
    area:               "Country Cost Settings",
    status:             cs.ready ? "Ready" : "Needs Attention",
    latestBatchStatus:  cs.ready ? "Imported" : "Ready for Review",
    note:               cs.ready ? `All ${cs.total} cost items Active` : `${cs.missing.length} of ${cs.total} cost items still Draft`,
  });
  if (!cs.ready) blockingIssues.push(`Country Cost Settings: ${cs.missing.length} items missing`);

  const overall: ReadinessStatus =
    rows.some((r) => r.status === "Blocked")         ? "Blocked" :
    rows.some((r) => r.status === "Needs Attention") ? "Needs Attention" :
                                                       "Ready";

  return { rows, overall, blockingIssues };
}

export type DataReadinessStatus = {
  id:                     string;
  financialYear:          string;
  country:                string;
  schoolRegisterStatus:   ReadinessStatus;
  staffAssignmentStatus:  ReadinessStatus;
  partnerStatus:          ReadinessStatus;
  ssaDataStatus:          ReadinessStatus;
  costSettingsStatus:     ReadinessStatus;
  targetSettingsStatus:   ReadinessStatus;
  holidayCalendarStatus:  ReadinessStatus;
  overallStatus:          ReadinessStatus;
  blockingIssues:         string[];
  recommendedActions:     string[];
};

export function dataReadinessForCountry(): DataReadinessStatus {
  const r = planningDataReadiness();
  const pickStatus = (area: string): ReadinessStatus =>
    r.rows.find((x) => x.area === area)?.status ?? "Blocked";
  return {
    id:                     `readiness-uganda-${FY.id}`,
    financialYear:          FY.label,
    country:                "Uganda",
    schoolRegisterStatus:   pickStatus("School Register"),
    staffAssignmentStatus:  pickStatus("Staff Register"),
    partnerStatus:          pickStatus("Partner Register"),
    ssaDataStatus:          pickStatus("SSA Data"),
    costSettingsStatus:     pickStatus("Country Cost Settings"),
    targetSettingsStatus:   pickStatus("Target Settings"),
    holidayCalendarStatus:  pickStatus("Public Holidays"),
    overallStatus:          r.overall,
    blockingIssues:         r.blockingIssues,
    recommendedActions:     r.blockingIssues.length === 0
      ? []
      : [
          "Resolve each blocking issue before opening the new financial year",
          "Re-run the validation queue after corrections are uploaded",
          "Have the Country Director re-approve cost settings if any item changed",
        ],
  };
}

// ────────── Helpers used by other engines ──────────

export function blockOrLimitPlanningFromReadiness(): {
  block: boolean;
  reason: string;
  limit: "full" | "limited" | "gateway-only";
} {
  const r = planningDataReadiness();
  if (r.overall === "Blocked") {
    return {
      block: true,
      reason: r.blockingIssues.join(" · "),
      limit: "gateway-only",
    };
  }
  if (r.overall === "Needs Attention") {
    return {
      block: false,
      reason: "Some data still needs review — full plans are allowed for ready areas only.",
      limit: "limited",
    };
  }
  return { block: false, reason: "All planning data ready", limit: "full" };
}
