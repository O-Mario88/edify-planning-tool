// Reports — view types + empty seeds (no fake data, purge migration).
//
// The CCEO auto-report catalogue (spec §21) lives here as a TYPE; the
// actual reports are assembled by the backend from real workflow
// records once that service lands. Until then `cceoAutoReports`,
// `recentReports`, and `scheduledReports` are empty arrays and the UI
// renders an empty state.

export type ReportFormat = "PDF" | "XLSX" | "CSV";

export type GeneratedReport = {
  id:          string;
  title:       string;
  period:      string;
  format:      ReportFormat;
  sizeKb:      number;
  generatedBy: string;
  generatedAt: string;
  href:        string;
};

export type ScheduledReport = {
  id:         string;
  title:      string;
  cadence:    "Daily" | "Weekly" | "Monthly" | "Quarterly";
  nextRun:    string;
  recipients: string;
  status:     "Active" | "Paused";
};

export type CceoAutoReport = {
  id:            string;
  title:         string;
  cadence:       "Weekly" | "Monthly" | "Quarterly" | "Continuous";
  description:   string;
  generatedFrom: string[];
  freshness:     string;
  keyNumbers:    { label: string; value: string }[];
  sections:      { heading: string; lines: string[] }[];
  liveHref:      string;
  printHref?:    string;
};

export const recentReports:    GeneratedReport[] = [];
export const scheduledReports: ScheduledReport[] = [];
export const cceoAutoReports:  CceoAutoReport[]  = [];
