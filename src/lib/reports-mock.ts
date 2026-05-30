// Generated reports + scheduled reports — used by /reports.

export type ReportFormat = "PDF" | "XLSX" | "CSV";

export type GeneratedReport = {
  id:         string;
  title:      string;
  period:     string;
  format:     ReportFormat;
  sizeKb:     number;
  generatedBy:string;
  generatedAt:string;
  href:       string; // mock download link
};

export const recentReports: GeneratedReport[] = [
  { id: "r1", title: "Country Performance — Uganda",  period: "Apr 2025",            format: "PDF",  sizeKb: 1280, generatedBy: "Sarah Okello",   generatedAt: "May 02, 2025 · 17:10", href: "#" },
  { id: "r2", title: "Verified Impact Leaderboard",   period: "Q1 FY 24/25",          format: "PDF",  sizeKb:  840, generatedBy: "Esther Wanjiru", generatedAt: "Apr 30, 2025 · 14:22", href: "#" },
  { id: "r3", title: "Funds & Disbursement",          period: "Apr 2025",            format: "XLSX", sizeKb: 2410, generatedBy: "Moses Tindi",    generatedAt: "Apr 28, 2025 · 09:55", href: "#" },
  { id: "r4", title: "SSA Performance — All Regions", period: "Q1 FY 24/25",          format: "PDF",  sizeKb: 1640, generatedBy: "Grace Alimo",    generatedAt: "Apr 22, 2025 · 11:00", href: "#" },
  { id: "r5", title: "Team Targets · Pace Status",    period: "Apr 2025",            format: "CSV",  sizeKb:  120, generatedBy: "Daniel Mwangi",  generatedAt: "Apr 20, 2025 · 16:40", href: "#" },
  { id: "r6", title: "Leave & Holiday Impact",        period: "Apr 2025",            format: "XLSX", sizeKb:  680, generatedBy: "Anne Wairimu",   generatedAt: "Apr 18, 2025 · 10:15", href: "#" },
];

export type ScheduledReport = {
  id:        string;
  title:     string;
  cadence:   "Daily" | "Weekly" | "Monthly" | "Quarterly";
  nextRun:   string;
  recipients:string; // human-friendly list
  status:    "Active" | "Paused";
};

export const scheduledReports: ScheduledReport[] = [
  { id: "s1", title: "Country Performance",      cadence: "Monthly",   nextRun: "Jun 01, 2025 · 06:00", recipients: "Country Directors · RVP",                  status: "Active" },
  { id: "s2", title: "Verified Impact",          cadence: "Quarterly", nextRun: "Jul 01, 2025 · 06:00", recipients: "All Program Leads + Country Directors",    status: "Active" },
  { id: "s3", title: "Funds & Disbursement",     cadence: "Weekly",    nextRun: "May 19, 2025 · 06:00", recipients: "Program Accountants · Country Directors",  status: "Active" },
  { id: "s4", title: "Team Targets",             cadence: "Weekly",    nextRun: "May 19, 2025 · 06:00", recipients: "Country Program Leads",                    status: "Active" },
  { id: "s5", title: "SSA Performance",          cadence: "Monthly",   nextRun: "Jun 01, 2025 · 06:00", recipients: "Impact Assessors · Country Directors",     status: "Paused" },
];
