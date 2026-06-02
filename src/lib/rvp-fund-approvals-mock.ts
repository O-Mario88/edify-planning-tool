// RVP Fund Approval — mock data layer.
//
// Numbers match the design reference (FY 2026, Q2). Lives alongside
// the PL + CD fund-approvals mocks so the /approvals route can switch
// flavours by role. Every shape mirrors the real backend so the page
// will swap to `db.*` with no UI changes.

// ────────── 6 KPI tiles ──────────

export type RvpKpi = {
  key:        string;
  label:      string;
  value:      string;          // "UGX 18.4B", "12 / 14"
  subValue?:  string;          // "Across 12 countries", "85% coverage"
  delta?:     string;          // "+12%", "0.4d faster"
  deltaTone?: "up" | "down";
  caption?:   string;          // "vs last month"
  /** Optional ring on the right (Budget Utilization tile). */
  ringPct?:   number;
  ringTone?:  "emerald" | "amber" | "blue";
};

export const rvpKpis: RvpKpi[] = [
  { key: "total",      label: "Total Requested",      value: "UGX 18.4B", subValue: "Across 12 countries" },
  { key: "pending",    label: "Pending Approval",     value: "UGX 4.2B",  subValue: "23 requests" },
  { key: "approved",   label: "Approved This Month",  value: "UGX 9.1B",  delta: "+12%",   deltaTone: "up",   caption: "vs last month" },
  { key: "countries",  label: "Countries with Requests", value: "12 / 14", subValue: "85% coverage" },
  { key: "approval_t", label: "Avg. Approval Time",   value: "1.8 days",  delta: "0.4d faster", deltaTone: "down", caption: "" },
  { key: "utilization",label: "Budget Utilization",   value: "54%",       subValue: "of RVP allocation", ringPct: 54, ringTone: "blue" },
];

// ────────── Country Fund Requests (left list) ──────────

export type RvpCountryRequest = {
  id:          string;
  country:     string;
  flag:        string;          // emoji
  leadName:    string;
  amount:      string;
  status:      "Pending" | "Approved" | "Under Review" | "Draft" | "Overdue" | "No requests";
  statusCount?: number;          // shown next to status, e.g., Pending (5)
  starred?:    boolean;          // 🌟 prefix for high-priority countries
  isActive?:   boolean;          // currently selected
};

export const rvpCountryRequests: RvpCountryRequest[] = [
  { id: "ug", country: "Uganda",      flag: "🇺🇬", leadName: "Sarah M.",  amount: "UGX 3.9B",  status: "Pending",      statusCount: 5, starred: true,  isActive: true },
  { id: "ke", country: "Kenya",       flag: "🇰🇪", leadName: "David K.",  amount: "UGX 2.8B",  status: "Approved"                                       },
  { id: "tz", country: "Tanzania",    flag: "🇹🇿", leadName: "Aisha H.",  amount: "UGX 1.6B",  status: "Under Review",                  starred: true   },
  { id: "rw", country: "Rwanda",      flag: "🇷🇼", leadName: "Jean P.",   amount: "UGX 1.2B",  status: "Draft",        statusCount: 3                  },
  { id: "ss", country: "South Sudan", flag: "🇸🇸", leadName: "Peter A.",  amount: "UGX 950M",  status: "Overdue",      statusCount: 2, starred: true   },
  { id: "cd", country: "DR Congo",    flag: "🇨🇩", leadName: "Marie L.",  amount: "UGX 3.1B",  status: "Approved"                                       },
  { id: "zm", country: "Zambia",      flag: "🇿🇲", leadName: "John C.",   amount: "UGX 1.4B",  status: "Pending",      statusCount: 2                  },
  { id: "mw", country: "Malawi",      flag: "🇲🇼", leadName: "Grace T.",  amount: "UGX 850M",  status: "No requests"                                    },
  { id: "et", country: "Ethiopia",    flag: "🇪🇹", leadName: "Daniel W.", amount: "UGX 1.8B",  status: "Pending",      statusCount: 1                  },
];

// ────────── Active country detail (Uganda) ──────────

export const rvpActiveCountry = {
  countryId:  "ug",
  country:    "Uganda",
  flag:       "🇺🇬",
  leadName:   "Sarah M.",
  leadRole:   "CCEO",
  districts:  8,
  fyLabel:    "FY 2026",
  approveAllCount: 5,
};

// Detail KPI strip — 5 tiles directly under the country header.

export type RvpDetailKpi = {
  key:      string;
  label:    string;
  value:    string;
  caption?: string;
  ringPct?: number;
  ringTone?: "blue";
};

export const rvpDetailKpis: RvpDetailKpi[] = [
  { key: "total",     label: "Total Requested",  value: "UGX 3.9B", caption: "5 requests" },
  { key: "approved",  label: "Approved",         value: "UGX 2.1B", caption: "3 items" },
  { key: "pending",   label: "Pending",          value: "UGX 1.3B", caption: "2 items" },
  { key: "allocated", label: "Budget Allocated", value: "UGX 8.2B", caption: "FY 2026" },
  { key: "util",      label: "Utilization",      value: "48%",      caption: "UGX 3.9B used", ringPct: 48, ringTone: "blue" },
];

// FY 2026 Plan Summary — 5 activity cards.

export type RvpPlanActivity = {
  key:        string;
  label:      string;
  planned:    string;          // "2,480"
  requested:  string;          // "UGX 820M"
  icon:       "school" | "users" | "userGroup" | "graduationCap" | "heart";
  iconTone:   "blue" | "amber" | "violet" | "rose" | "emerald";
};

export const rvpPlanActivities: RvpPlanActivity[] = [
  { key: "staff",      label: "Staff School Visits",   planned: "2,480", requested: "UGX 820M", icon: "school",        iconTone: "blue"    },
  { key: "partner",    label: "Partner School Visits", planned: "1,920", requested: "UGX 640M", icon: "users",         iconTone: "amber"   },
  { key: "cluster",    label: "Cluster Meetings",      planned: "96",    requested: "UGX 480M", icon: "userGroup",     iconTone: "violet"  },
  { key: "trainings",  label: "Trainings",             planned: "24",    requested: "UGX 1.1B", icon: "graduationCap", iconTone: "rose"    },
  { key: "engagement", label: "Community Engagements", planned: "18",    requested: "UGX 360M", icon: "heart",         iconTone: "emerald" },
];

// Spending by Category — donut + legend.

export type RvpSpendCategory = {
  key:    string;
  label:  string;
  amount: string;
  pct:    number;
  color:  string;
};

export const rvpSpendingByCategory: RvpSpendCategory[] = [
  { key: "travel",    label: "Travel",               amount: "UGX 1.4B",  pct: 36, color: "#3b82f6" },
  { key: "accom",     label: "Accommodation",        amount: "UGX 1.0B",  pct: 26, color: "#22c55e" },
  { key: "feeding",   label: "Feeding",              amount: "UGX 780M",  pct: 20, color: "#a855f7" },
  { key: "materials", label: "Training Materials",   amount: "UGX 390M",  pct: 10, color: "#f59e0b" },
  { key: "stakeh",    label: "Stakeholder Meetings", amount: "UGX 220M",  pct: 6,  color: "#ec4899" },
  { key: "other",     label: "Other",                amount: "UGX 100M",  pct: 2,  color: "#94a3b8" },
];

export const rvpSpendingTotal = "UGX 3.9B";

// Recent Fund Requests (bottom left of detail).

export type RvpRecentRequest = {
  id:       string;
  title:    string;            // "Q2 School Visits"
  scope:    string;            // "North"
  category: "Staff Visits" | "Cluster" | "Training";
  amount:   string;
  status:   "Pending" | "Approved" | "Under Review";
  date:     string;            // "May 26"
};

export const rvpRecentRequests: RvpRecentRequest[] = [
  { id: "rfr-1", title: "Q2 School Visits", scope: "North",  category: "Staff Visits", amount: "UGX 420M", status: "Pending",      date: "May 26" },
  { id: "rfr-2", title: "Cluster Meetings", scope: "East",   category: "Cluster",      amount: "UGX 180M", status: "Approved",     date: "May 24" },
  { id: "rfr-3", title: "Teacher Training", scope: "SSA Program",      category: "Training",     amount: "UGX 350M", status: "Under Review", date: "May 23" },
];

// Approvals & Comments (bottom right of detail).

export type RvpApprovalComment = {
  id:        string;
  who:       string;
  role:      "Country Lead" | "RVP";
  initials:  string;
  message:   string;
  when:      string;
  badge?:    "Ready to approve";
};

export const rvpApprovalComments: RvpApprovalComment[] = [
  { id: "ac-1", who: "Sarah M.", role: "Country Lead", initials: "SM", message: "Submitted Q2 requests. All aligned to FY targets.",   when: "2h ago" },
  { id: "ac-2", who: "You",      role: "RVP",          initials: "RV", message: "Looks good. Please confirm accommodation split.",      when: "1h ago", badge: "Ready to approve" },
];

// ────────── Filter bar ──────────

export const rvpFundFilters = {
  fy:       "FY 2026",
  quarter:  "Q3 (Apr–Jun)",
  status:   "All Status",
};
