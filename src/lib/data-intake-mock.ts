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
  | "Evidence Records";

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
  {
    id: "tpl-school-register",
    name: "School Register Template",
    dataType: "School Register",
    description: "Master list of every school in the platform. Used by every dashboard, planning surface, and Salesforce import.",
    requiredColumns: [
      "School_ID", "Salesforce_School_ID", "School_Name", "Country",
      "Region", "District", "Cluster", "School_Type", "School_Status",
      "Assigned_CCEO_ID", "Assigned_CCEO_Name", "Assigned_CCEO_Email",
      "Assigned_Program_Lead_ID",
    ],
    optionalColumns: [
      "Primary_Contact_Name", "Primary_Contact_Phone",
      "School_Latitude", "School_Longitude", "Assigned_Partner_ID",
    ],
    dropdownColumns: {
      School_Type:   ["Primary", "Secondary", "Cluster"],
      School_Status: ["Active", "Inactive", "Closed"],
      Country:       ["Uganda", "Zambia", "Kenya"],
    },
    exampleRows: [
      { School_ID: "CS-001", Salesforce_School_ID: "001AB00001", School_Name: "Sunrise Primary School", Country: "Uganda", Region: "North", District: "Kitgum", Cluster: "Kitgum North", School_Type: "Primary", School_Status: "Active", Assigned_CCEO_ID: "STF-DM-014", Assigned_CCEO_Name: "Daniel Mwangi", Assigned_CCEO_Email: "daniel.mwangi@edify.org", Assigned_Program_Lead_ID: "PL-001" },
    ],
    validationRules: [
      "School_ID is unique across the file",
      "Salesforce_School_ID must match the 18-char Salesforce format",
      "Assigned_CCEO_ID must exist in Staff Register",
      "School_Type must be one of: Primary / Secondary / Cluster",
      "School_Latitude / School_Longitude must be valid lat/long if provided",
    ],
    createdBy: "Edify HQ",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-staff-register",
    name: "Staff Register Template",
    dataType: "Staff Register",
    description: "Active staff with role, region, supervisor, and email.",
    requiredColumns: ["Staff_ID", "Staff_Name", "Email", "Role", "Region", "Supervisor_ID"],
    optionalColumns: ["Phone", "Cluster", "Start_Date", "Salesforce_User_ID"],
    dropdownColumns: {
      Role: ["CCEO", "Country Program Lead", "Country Director", "RVP", "Program Accountant", "Impact Assessment", "HR", "Admin"],
    },
    exampleRows: [
      { Staff_ID: "STF-DM-014", Staff_Name: "Daniel Mwangi", Email: "daniel.mwangi@edify.org", Role: "Country Program Lead", Region: "North", Supervisor_ID: "STF-SO-021" },
    ],
    validationRules: [
      "Staff_ID is unique",
      "Email is unique and validly formatted",
      "Supervisor_ID must exist in Staff Register",
      "Role must be one of the allowed values",
    ],
    createdBy: "Edify HQ",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-partner-register",
    name: "Partner Register Template",
    dataType: "Partner Register",
    description: "Certified delivery partners + assignment scope.",
    requiredColumns: ["Partner_ID", "Partner_Name", "Country", "Certification_Status", "Effective_From"],
    optionalColumns: ["Effective_To", "Primary_Contact_Name", "Primary_Contact_Phone", "Assigned_District"],
    dropdownColumns: {
      Certification_Status: ["Certified", "Probationary", "Suspended", "Decertified"],
    },
    exampleRows: [
      { Partner_ID: "PRT-001", Partner_Name: "Hope Africa", Country: "Uganda", Certification_Status: "Certified", Effective_From: "2024-10-01" },
    ],
    validationRules: [
      "Partner_ID is unique",
      "Certification_Status must be one of the allowed values",
      "Effective_From must be a valid date",
    ],
    createdBy: "Edify HQ",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-cceo-assignment",
    name: "CCEO School Assignment Template",
    dataType: "CCEO Assignment",
    description: "Which CCEO owns which schools this FY.",
    requiredColumns: ["School_ID", "Assigned_CCEO_ID", "Effective_From"],
    optionalColumns: ["Effective_To", "Notes"],
    dropdownColumns: {},
    exampleRows: [
      { School_ID: "CS-001", Assigned_CCEO_ID: "STF-DM-014", Effective_From: "2025-10-01" },
    ],
    validationRules: [
      "Each School_ID has at most one Active assignment at a time",
      "Assigned_CCEO_ID must exist in Staff Register",
      "Effective_From must be on or after the FY start",
    ],
    createdBy: "Edify HQ",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-pl-assignment",
    name: "Program Lead Assignment Template",
    dataType: "Program Lead Assignment",
    description: "Which Program Lead supervises which CCEOs this FY.",
    requiredColumns: ["Program_Lead_ID", "CCEO_ID", "Effective_From"],
    optionalColumns: ["Effective_To"],
    dropdownColumns: {},
    exampleRows: [
      { Program_Lead_ID: "PL-001", CCEO_ID: "STF-DM-014", Effective_From: "2025-10-01" },
    ],
    validationRules: [
      "Each CCEO_ID has at most one Active Program Lead at a time",
      "Both IDs must exist in Staff Register",
    ],
    createdBy: "Edify HQ",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-ssa-results",
    name: "SSA Results Template",
    dataType: "SSA Results",
    description: "Per-school SSA scoring across all 8 intervention areas + overall verification flag.",
    requiredColumns: [
      "School_ID", "Assessment_Date", "Conducted_By_Staff_ID",
      "Christ_like_Behavior", "Exposure_to_Word_of_God", "Fees_Budget_Accounts",
      "Government_Requirements", "Leadership_Best_Practice", "Learning_Environment",
      "Teaching_Environment", "Enrollment",
    ],
    optionalColumns: ["Notes", "Verification_Salesforce_ID", "Verified_By_Staff_ID"],
    dropdownColumns: {},
    exampleRows: [
      { School_ID: "CS-001", Assessment_Date: "2025-11-04", Conducted_By_Staff_ID: "STF-DM-014", Christ_like_Behavior: 8, Exposure_to_Word_of_God: 7, Fees_Budget_Accounts: 5, Government_Requirements: 6, Leadership_Best_Practice: 8, Learning_Environment: 7, Teaching_Environment: 7, Enrollment: 6 },
    ],
    validationRules: [
      "Every intervention score must be a number between 0 and 10",
      "Assessment_Date must be within the active FY",
      "School_ID must exist in School Register",
      "Conducted_By_Staff_ID must be the assigned CCEO or supervisor",
    ],
    createdBy: "Impact Assessment",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-training-records",
    name: "Training Records Template",
    dataType: "Training Records",
    description: "School Improvement Training, cluster trainings, in-school coaching.",
    requiredColumns: ["Training_ID", "Training_Type", "Training_Date", "Cluster_Name", "Participant_Count", "Conducted_By_Staff_ID", "Salesforce_Activity_ID"],
    optionalColumns: ["Partner_ID", "School_IDs", "Notes"],
    dropdownColumns: {
      Training_Type: ["School Improvement Training", "Cluster Training", "In-School Coaching", "Partner-Led Training"],
    },
    exampleRows: [
      { Training_ID: "TR-001", Training_Type: "School Improvement Training", Training_Date: "2025-10-15", Cluster_Name: "Kitgum North", Participant_Count: 28, Conducted_By_Staff_ID: "STF-DM-014", Salesforce_Activity_ID: "SFA-100018" },
    ],
    validationRules: [
      "Training_Date must be within the active FY",
      "Salesforce_Activity_ID must be valid + verifiable",
      "Conducted_By_Staff_ID must exist",
    ],
    createdBy: "Edify HQ",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-visit-records",
    name: "Visit Records Template",
    dataType: "Visit Records",
    description: "School visits — staff or partner-led.",
    requiredColumns: ["Visit_ID", "School_ID", "Visit_Date", "Conducted_By_Staff_ID", "Visit_Type", "Salesforce_Activity_ID"],
    optionalColumns: ["Partner_ID", "Headteacher_Signoff", "Photo_Evidence_Url", "Notes"],
    dropdownColumns: {
      Visit_Type: ["School Visit", "Core Visit", "Follow-Up Visit", "SSA Visit", "Partner Visit"],
    },
    exampleRows: [
      { Visit_ID: "V-001", School_ID: "CS-001", Visit_Date: "2025-11-08", Conducted_By_Staff_ID: "STF-DM-014", Visit_Type: "Core Visit", Salesforce_Activity_ID: "SFA-100119" },
    ],
    validationRules: [
      "Visit_Date must be within the active FY",
      "School_ID must exist in School Register",
      "Salesforce_Activity_ID format check",
    ],
    createdBy: "Edify HQ",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-exam-results",
    name: "Exam Results Template",
    dataType: "Exam Results",
    description: "End-of-term and end-of-year exam result counts.",
    requiredColumns: ["School_ID", "Exam_Period", "Subject", "Average_Score", "Pass_Rate", "Collected_By_Staff_ID"],
    optionalColumns: ["Notes", "Salesforce_Activity_ID"],
    dropdownColumns: {
      Exam_Period: ["Term 1", "Term 2", "Term 3", "End of Year"],
    },
    exampleRows: [
      { School_ID: "CS-001", Exam_Period: "End of Year", Subject: "Mathematics", Average_Score: 64, Pass_Rate: 78, Collected_By_Staff_ID: "STF-DM-014" },
    ],
    validationRules: [
      "Average_Score 0–100",
      "Pass_Rate 0–100",
      "School_ID must exist",
    ],
    createdBy: "Edify HQ",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-enrollment",
    name: "Enrollment Update Template",
    dataType: "Enrollment Updates",
    description: "Termly enrollment update per school.",
    requiredColumns: ["School_ID", "Term", "Boys_Enrolled", "Girls_Enrolled", "Collected_By_Staff_ID"],
    optionalColumns: ["Notes"],
    dropdownColumns: {
      Term: ["Term 1", "Term 2", "Term 3"],
    },
    exampleRows: [
      { School_ID: "CS-001", Term: "Term 1", Boys_Enrolled: 240, Girls_Enrolled: 232, Collected_By_Staff_ID: "STF-DM-014" },
    ],
    validationRules: [
      "Boys_Enrolled and Girls_Enrolled must be non-negative integers",
      "School_ID must exist",
    ],
    createdBy: "Edify HQ",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-msc-stories",
    name: "MSC Stories Template",
    dataType: "MSC Stories",
    description: "Most Significant Change stories collected from the field.",
    requiredColumns: ["Story_ID", "School_ID", "Collected_By_Staff_ID", "Collected_Date", "Headline", "Story_Body"],
    optionalColumns: ["Photo_Url", "Subject_Name", "Subject_Role"],
    dropdownColumns: {},
    exampleRows: [
      { Story_ID: "MSC-001", School_ID: "CS-001", Collected_By_Staff_ID: "STF-DM-014", Collected_Date: "2025-11-04", Headline: "Headteacher transformed staff morale", Story_Body: "..." },
    ],
    validationRules: [
      "Story_ID is unique",
      "Headline and Story_Body required",
    ],
    createdBy: "Edify HQ",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-core-package",
    name: "Core School Package Template",
    dataType: "Core School Package",
    description: "Year package status for each Core School.",
    requiredColumns: ["School_ID", "Package_Year", "Visits_Required", "Trainings_Required"],
    optionalColumns: ["Notes"],
    dropdownColumns: {},
    exampleRows: [
      { School_ID: "CS-002", Package_Year: "2025/26", Visits_Required: 4, Trainings_Required: 4 },
    ],
    validationRules: [
      "School_ID must reference a Core School in the School Register",
      "Visits_Required and Trainings_Required must be positive integers",
    ],
    createdBy: "Edify HQ",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-special-projects",
    name: "Special Projects Template",
    dataType: "Special Projects",
    description: "Targets + participant counts for each special project.",
    requiredColumns: ["Project_ID", "Project_Name", "Target_Sessions", "Target_Participants", "Lead_Staff_ID"],
    optionalColumns: ["Partner_ID", "Notes"],
    dropdownColumns: {},
    exampleRows: [
      { Project_ID: "SP-EDTECH", Project_Name: "EdTech 2025", Target_Sessions: 24, Target_Participants: 320, Lead_Staff_ID: "STF-DM-014" },
    ],
    validationRules: [
      "Project_ID is unique",
      "Target_Sessions and Target_Participants must be positive integers",
    ],
    createdBy: "Edify HQ",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-cost-settings",
    name: "Country Cost Settings Template",
    dataType: "Country Cost Settings",
    description: "Unit costs for every budget category in the active FY.",
    requiredColumns: ["Country", "Cost_Item", "Unit_Cost", "Currency", "Effective_From"],
    optionalColumns: ["Effective_To", "Notes"],
    dropdownColumns: {
      Currency: ["UGX", "ZMW", "KES", "USD"],
    },
    exampleRows: [
      { Country: "Uganda", Cost_Item: "Staff school visit cost", Unit_Cost: 95000, Currency: "UGX", Effective_From: "2025-10-01" },
    ],
    validationRules: [
      "Unit_Cost must be a positive number",
      "Currency must be one of the allowed values",
      "Effective_From must be a valid date",
    ],
    createdBy: "Country Director",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-targets",
    name: "Target Settings Template",
    dataType: "Target Settings",
    description: "Annual + quarterly + monthly target rules per role / activity.",
    requiredColumns: ["Target_ID", "Scope", "Activity", "Monthly_Target", "Quarterly_Target", "Annual_Target"],
    optionalColumns: ["Notes"],
    dropdownColumns: {
      Scope: ["Country", "Region", "District", "Cluster", "Staff"],
    },
    exampleRows: [
      { Target_ID: "TGT-001", Scope: "Staff", Activity: "Valid Visits", Monthly_Target: 18, Quarterly_Target: 52, Annual_Target: 210 },
    ],
    validationRules: [
      "Targets must be positive integers",
      "Monthly_Target × 3 should approximately equal Quarterly_Target",
    ],
    createdBy: "Country Director",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-public-holidays",
    name: "Public Holidays Template",
    dataType: "Public Holidays",
    description: "Country public holidays used by the planning engine.",
    requiredColumns: ["Country", "Date", "Holiday_Name"],
    optionalColumns: ["Notes"],
    dropdownColumns: {},
    exampleRows: [
      { Country: "Uganda", Date: "2025-10-09", Holiday_Name: "Independence Day" },
    ],
    validationRules: [
      "Date must be valid ISO YYYY-MM-DD",
      "(Country, Date) must be unique",
    ],
    createdBy: "Admin",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-leave-blackout",
    name: "Leave / Blackout Dates Template",
    dataType: "Leave Blackout Dates",
    description: "Conference weeks, training blackouts, organisational closures.",
    requiredColumns: ["Country", "Start_Date", "End_Date", "Reason"],
    optionalColumns: ["Region", "Notes"],
    dropdownColumns: {
      Reason: ["Conference Week", "Holiday", "Audit Window", "Training Blackout", "Organisational Closure"],
    },
    exampleRows: [
      { Country: "Uganda", Start_Date: "2025-12-15", End_Date: "2025-12-22", Reason: "Conference Week" },
    ],
    validationRules: [
      "Start_Date <= End_Date",
      "Reason must be one of the allowed values",
    ],
    createdBy: "Admin",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-salesforce-verification",
    name: "Salesforce Verification Template",
    dataType: "Salesforce Verification",
    description: "Verified Salesforce activity IDs with evidence flags.",
    requiredColumns: ["Salesforce_Activity_ID", "Verified_By_Staff_ID", "Verified_Date", "Evidence_Complete"],
    optionalColumns: ["Notes"],
    dropdownColumns: {
      Evidence_Complete: ["Yes", "No", "Partial"],
    },
    exampleRows: [
      { Salesforce_Activity_ID: "SFA-100018", Verified_By_Staff_ID: "STF-GA-031", Verified_Date: "2025-11-09", Evidence_Complete: "Yes" },
    ],
    validationRules: [
      "Salesforce_Activity_ID must exist and not already be Verified",
      "Verified_Date must be within 14 days of activity date",
    ],
    createdBy: "Impact Assessment",
    updatedAt: "2025-09-15",
  },
  {
    id: "tpl-evidence-records",
    name: "Evidence Records Template",
    dataType: "Evidence Records",
    description: "Photo, signoff, and document evidence per activity.",
    requiredColumns: ["Evidence_ID", "Salesforce_Activity_ID", "Evidence_Type", "Submitted_By_Staff_ID", "Submitted_Date"],
    optionalColumns: ["File_Url", "Notes"],
    dropdownColumns: {
      Evidence_Type: ["School Photo", "Headteacher Signoff", "Participant List", "Receipt", "Other"],
    },
    exampleRows: [
      { Evidence_ID: "EV-001", Salesforce_Activity_ID: "SFA-100018", Evidence_Type: "School Photo", Submitted_By_Staff_ID: "STF-DM-014", Submitted_Date: "2025-11-04" },
    ],
    validationRules: [
      "Evidence_ID is unique",
      "Salesforce_Activity_ID must exist",
    ],
    createdBy: "Edify HQ",
    updatedAt: "2025-09-15",
  },
];

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
