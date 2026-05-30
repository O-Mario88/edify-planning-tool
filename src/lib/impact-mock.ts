// Impact Assessment dashboard mock data.
//
// The Impact Assessment role (Grace Alimo · M&E) is responsible for
// validating program data uploaded by field staff and partners. The
// dashboard surfaces dataset-level metrics across all five programs
// (Core Schools, Client Schools, Exam Scores, SSA Assessments,
// Discipleship Clubs) and lets the assessor jump directly into any
// program area, the verification queue, or the quality-checks console.

// ────────── Header / user ─────────────────────────────────────────────

export const impactHeader = {
  title: "Impact Assessment Dashboard",
  subtitle:
    "Monitor data quality, verification progress and partner performance across all programs.",
  filters: {
    month:    "May 2025",
    program:  "All Programs",
    region:   "All Regions",
  },
};

export const impactUser = {
  name:     "Grace Alimo",
  role:     "Impact Assessor",
  initials: "GA",
};

export const impactNotificationCount = 8;

// ────────── Top KPI row ───────────────────────────────────────────────

export type ImpactKpi = {
  key:        string;
  label:      string;
  value:      string;
  share?:     string; // optional secondary "(76.5%)" annotation
  trend:      { tone: "up" | "down"; label: string };
  icon:       "database" | "shieldCheck" | "clock" | "alertOctagon" | "users";
  iconTone:   "violet" | "green" | "amber" | "rose" | "blue";
  href:       string;
};

// Per-leader scoping of the same 5 KPIs. Leadership dashboards reuse the
// shape from `impactKpis` but with values scaled to that leader's scope:
// team for CPL, country for Country Director, region for RVP.
export type LeadershipScope = "cpl" | "director" | "rvp";

export const leadershipImpactKpis: Record<LeadershipScope, ImpactKpi[]> = {
  cpl: [
    { key: "total-records",       label: "Records (My Team)",    value: "2,148", trend: { tone: "up",   label: "6.2% vs Apr" },          icon: "database",     iconTone: "violet", href: "/data-verification" },
    { key: "verified-records",    label: "Verified",             value: "1,604", share: "74.7%", trend: { tone: "up",   label: "4.9% vs Apr" }, icon: "shieldCheck",  iconTone: "green",  href: "/data-verification?status=verified&scope=team" },
    { key: "pending-verification",label: "Pending Verification", value: "412",   share: "19.2%", trend: { tone: "down", label: "2.4% vs Apr" }, icon: "clock",        iconTone: "amber",  href: "/data-verification?status=pending&scope=team"  },
    { key: "failed-qc",           label: "Failed Quality Check", value: "132",   share: "6.1%",  trend: { tone: "down", label: "0.9% vs Apr" }, icon: "alertOctagon", iconTone: "rose",   href: "/quality-checks?status=failed&scope=team"     },
    { key: "partners-active",     label: "Partners Active",      value: "11",    trend: { tone: "up",   label: "1 vs Apr"   },                  icon: "users",        iconTone: "blue",   href: "/partners?scope=team" },
  ],
  director: [
    { key: "total-records",       label: "Records (Country)",    value: "6,920", trend: { tone: "up",   label: "7.8% vs Apr" },          icon: "database",     iconTone: "violet", href: "/data-verification?scope=country" },
    { key: "verified-records",    label: "Verified",             value: "5,283", share: "76.3%", trend: { tone: "up",   label: "6.1% vs Apr" }, icon: "shieldCheck",  iconTone: "green",  href: "/data-verification?status=verified&scope=country" },
    { key: "pending-verification",label: "Pending Verification", value: "1,168", share: "16.9%", trend: { tone: "down", label: "3.0% vs Apr" }, icon: "clock",        iconTone: "amber",  href: "/data-verification?status=pending&scope=country"  },
    { key: "failed-qc",           label: "Failed Quality Check", value: "469",   share: "6.8%",  trend: { tone: "down", label: "1.1% vs Apr" }, icon: "alertOctagon", iconTone: "rose",   href: "/quality-checks?status=failed&scope=country"     },
    { key: "partners-active",     label: "Partners Active",      value: "27",    trend: { tone: "up",   label: "2 vs Apr"   },                  icon: "users",        iconTone: "blue",   href: "/partners?scope=country" },
  ],
  rvp: [
    { key: "total-records",       label: "Records (Region)",     value: "12,842",trend: { tone: "up",   label: "8.4% vs Apr" },          icon: "database",     iconTone: "violet", href: "/data-verification" },
    { key: "verified-records",    label: "Verified",             value: "9,823", share: "76.5%", trend: { tone: "up",   label: "6.7% vs Apr" }, icon: "shieldCheck",  iconTone: "green",  href: "/data-verification?status=verified" },
    { key: "pending-verification",label: "Pending Verification", value: "2,143", share: "16.7%", trend: { tone: "down", label: "3.1% vs Apr" }, icon: "clock",        iconTone: "amber",  href: "/data-verification?status=pending"  },
    { key: "failed-qc",           label: "Failed Quality Check", value: "876",   share: "6.8%",  trend: { tone: "down", label: "1.2% vs Apr" }, icon: "alertOctagon", iconTone: "rose",   href: "/quality-checks?status=failed"     },
    { key: "partners-active",     label: "Partners Active",      value: "48",    trend: { tone: "up",   label: "3 vs Apr"   },                  icon: "users",        iconTone: "blue",   href: "/partners" },
  ],
};

export const impactKpis: ImpactKpi[] = [
  {
    key:      "total-records",
    label:    "Total Records",
    value:    "12,842",
    trend:    { tone: "up", label: "8.4% vs Apr 2025" },
    icon:     "database",
    iconTone: "violet",
    href:     "/data-verification",
  },
  {
    key:      "verified-records",
    label:    "Verified Records",
    value:    "9,823",
    share:    "76.5%",
    trend:    { tone: "up", label: "6.7% vs Apr 2025" },
    icon:     "shieldCheck",
    iconTone: "green",
    href:     "/data-verification?status=verified",
  },
  {
    key:      "pending-verification",
    label:    "Pending Verification",
    value:    "2,143",
    share:    "16.7%",
    trend:    { tone: "down", label: "3.1% vs Apr 2025" },
    icon:     "clock",
    iconTone: "amber",
    href:     "/data-verification?status=pending",
  },
  {
    key:      "failed-qc",
    label:    "Failed Quality Check",
    value:    "876",
    share:    "6.8%",
    trend:    { tone: "down", label: "1.2% vs Apr 2025" },
    icon:     "alertOctagon",
    iconTone: "rose",
    href:     "/quality-checks?status=failed",
  },
  {
    key:      "partners-active",
    label:    "Partners Active",
    value:    "48",
    trend:    { tone: "up", label: "3 vs Apr 2025" },
    icon:     "users",
    iconTone: "blue",
    href:     "/partners",
  },
];

// ────────── Program Overview tiles ────────────────────────────────────

export type ProgramTile = {
  key:      string;
  label:    string;
  count:    string;
  trend:    string; // "6 vs Apr"
  icon:     "school" | "building" | "fileSpreadsheet" | "shieldCheck" | "heart";
  iconTone: "edify" | "green" | "violet" | "amber" | "rose";
  href:     string;
};

export const programTiles: ProgramTile[] = [
  { key: "core",        label: "Core Schools",       count: "128",   trend: "6 vs Apr",    icon: "school",          iconTone: "edify",  href: "/core-schools"      },
  { key: "client",      label: "Client Schools",     count: "342",   trend: "12 vs Apr",   icon: "building",        iconTone: "green",  href: "/schools"           },
  { key: "exam",        label: "Exam Scores",        count: "5,672", trend: "9.4% vs Apr", icon: "fileSpreadsheet", iconTone: "violet", href: "/exam-scores"       },
  { key: "ssa",         label: "SSA Assessments",    count: "1,248", trend: "7.1% vs Apr", icon: "shieldCheck",     iconTone: "amber",  href: "/ssa"               },
  { key: "discipleship",label: "Discipleship Clubs", count: "986",   trend: "5.3% vs Apr", icon: "heart",           iconTone: "rose",   href: "/discipleship-clubs"},
];

// ────────── Data Verification Funnel ──────────────────────────────────

export type FunnelStage = {
  key:    string;
  label:  string;
  value:  number;
  share:  string;   // "100%", "76.5%"
  tone:   "blue" | "sky" | "amber" | "rose" | "green";
  href:   string;
};

export const verificationFunnel: FunnelStage[] = [
  { key: "uploaded",  label: "Uploaded",  value: 12842, share: "100%",  tone: "blue",  href: "/data-verification?stage=uploaded"  },
  { key: "in-review", label: "In Review", value: 2143,  share: "16.7%", tone: "sky",   href: "/data-verification?stage=in-review" },
  { key: "verified",  label: "Verified",  value: 9823,  share: "76.5%", tone: "amber", href: "/data-verification?stage=verified"  },
  { key: "failed-qc", label: "Failed QC", value: 876,   share: "6.8%",  tone: "rose",  href: "/quality-checks?status=failed"      },
  { key: "resolved",  label: "Resolved",  value: 8947,  share: "69.7%", tone: "green", href: "/data-verification?stage=resolved"  },
];

export const verificationRate = 76.5;

// ────────── Data Quality Trend ─────────────────────────────────────────

export type QualityTrendPoint = {
  month:    string;
  verified: number;
  inReview: number;
  failedQc: number;
  resolved: number;
};

export const qualityTrend: QualityTrendPoint[] = [
  { month: "Dec", verified: 3200, inReview: 1100, failedQc: 600, resolved: 2200 },
  { month: "Jan", verified: 4100, inReview: 1300, failedQc: 720, resolved: 3000 },
  { month: "Feb", verified: 4900, inReview: 1500, failedQc: 760, resolved: 3700 },
  { month: "Mar", verified: 5600, inReview: 1700, failedQc: 810, resolved: 4400 },
  { month: "Apr", verified: 6900, inReview: 1900, failedQc: 840, resolved: 5500 },
  { month: "May", verified: 7600, inReview: 2143, failedQc: 876, resolved: 6800 },
];

// ────────── Quality Check Status (donut) ──────────────────────────────

export type QualitySeverity = {
  key:   string;
  label: string;
  value: number;
  share: string;
  color: string;
  href:  string;
};

export const qualityCheckSeverity: QualitySeverity[] = [
  { key: "critical", label: "Critical", value: 214, share: "24.4%", color: "#ef4444", href: "/quality-checks?severity=critical" },
  { key: "major",    label: "Major",    value: 342, share: "39.0%", color: "#f59e0b", href: "/quality-checks?severity=major"    },
  { key: "minor",    label: "Minor",    value: 198, share: "22.6%", color: "#facc15", href: "/quality-checks?severity=minor"    },
  { key: "info",     label: "Info",     value: 122, share: "14.0%", color: "#3b82f6", href: "/quality-checks?severity=info"     },
];

export const qualityCheckTotal = 876;

// ────────── Top Data Quality Issues ───────────────────────────────────

export type DataQualityIssue = {
  key:   string;
  label: string;
  count: number;
  tone:  "rose" | "amber" | "violet" | "blue" | "green";
  href:  string;
};

export const topQualityIssues: DataQualityIssue[] = [
  { key: "missing-exam",  label: "Missing Exam Scores",         count: 234, tone: "rose",   href: "/quality-checks?issue=missing-exam-scores"        },
  { key: "incomplete-ssa",label: "Incomplete SSA Assessment",   count: 198, tone: "amber",  href: "/quality-checks?issue=incomplete-ssa"             },
  { key: "duplicates",    label: "Duplicate Records",           count: 156, tone: "violet", href: "/quality-checks?issue=duplicates"                 },
  { key: "invalid-format",label: "Invalid Data Format",         count: 132, tone: "blue",   href: "/quality-checks?issue=invalid-format"             },
  { key: "missing-club",  label: "Missing Discipleship Club Data", count: 98, tone: "green",  href: "/quality-checks?issue=missing-discipleship-data" },
];

// ────────── Recent Data Uploads ───────────────────────────────────────

export type UploadStatus = "Verified" | "In Review" | "Failed QC";

export type DataUploadRow = {
  key:        string;
  program:    string;
  fileName:   string;
  uploadedBy: string;
  records:    number;
  status:     UploadStatus;
  uploadedOn: string;
  href:       string;
};

export const recentUploads: DataUploadRow[] = [
  { key: "u1", program: "Core Schools",      fileName: "CoreSchools_May2025.xlsx",   uploadedBy: "John Mwangi",  records: 128,   status: "Verified",  uploadedOn: "May 20, 2025 10:30 AM", href: "/data-intake/upload/u1" },
  { key: "u2", program: "Client Schools",    fileName: "ClientSchools_May2025.xlsx", uploadedBy: "Sarah K.",     records: 342,   status: "In Review", uploadedOn: "May 20, 2025 09:15 AM", href: "/data-intake/upload/u2" },
  { key: "u3", program: "Exam Scores",       fileName: "ExamScores_May2025.xlsx",    uploadedBy: "Michael O.",   records: 1256,  status: "Verified",  uploadedOn: "May 19, 2025 04:45 PM", href: "/data-intake/upload/u3" },
  { key: "u4", program: "SSA Assessments",   fileName: "SSA_May2025.xlsx",           uploadedBy: "Grace A.",     records: 248,   status: "Failed QC", uploadedOn: "May 19, 2025 02:20 PM", href: "/data-intake/upload/u4" },
  { key: "u5", program: "Discipleship Clubs",fileName: "DC_May2025.xlsx",            uploadedBy: "David L.",     records: 186,   status: "In Review", uploadedOn: "May 19, 2025 11:05 AM", href: "/data-intake/upload/u5" },
];

// ────────── Partner Performance (Verification Rate) ───────────────────

export type PartnerScore = {
  key:   string;
  name:  string;
  pct:   number; // 0–100
  tone:  "green" | "amber" | "rose";
  href:  string;
};

export const partnerScores: PartnerScore[] = [
  { key: "p1", name: "Living Word School",     pct: 92, tone: "green", href: "/partners/p1" },
  { key: "p2", name: "Hope Academy",           pct: 87, tone: "green", href: "/partners/p2" },
  { key: "p3", name: "Grace Community School", pct: 76, tone: "green", href: "/partners/p3" },
  { key: "p4", name: "Victory Academy",        pct: 65, tone: "amber", href: "/partners/p4" },
  { key: "p5", name: "Light of Hope School",   pct: 58, tone: "rose",  href: "/partners/p5" },
];

export const partnerOverallAverage = 76.5;

// ────────── Quick Actions ─────────────────────────────────────────────

export type ImpactQuickAction = {
  key:    string;
  label:  string;
  icon:   "upload" | "shield" | "check" | "fileText" | "alertTriangle" | "activity";
  tone:   "edify" | "green" | "violet" | "amber" | "rose" | "blue";
  href:   string;
  badge?: number;
};

export const impactQuickActions: ImpactQuickAction[] = [
  { key: "upload",      label: "Upload Data",        icon: "upload",         tone: "edify",  href: "/data-intake/upload"          },
  { key: "qc",          label: "Run Quality Check",  icon: "shield",         tone: "violet", href: "/quality-checks"              },
  { key: "verify",      label: "Verify Records",     icon: "check",          tone: "green",  href: "/data-verification?status=pending" },
  { key: "report",      label: "Generate Report",    icon: "fileText",       tone: "blue",   href: "/reports"                     },
  { key: "issues",      label: "View Issues",        icon: "alertTriangle",  tone: "rose",   href: "/alerts",     badge: 12       },
  { key: "activity",    label: "Activity Log",       icon: "activity",       tone: "amber",  href: "/activity-log"                },
];
