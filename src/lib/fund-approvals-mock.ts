// Fund Approvals page — mock data layer for the CPL Fund Approvals
// replica. Numbers match the design reference exactly. Shapes mirror
// what the real backend will return so the page can swap to db.*
// without UI changes.

// ────────── 6 KPI tiles ──────────

export type FundApprovalKpi = {
  key:      string;
  label:    string;
  value:    string;       // "UGX 214.6M"
  caption?: string;       // "12 requests", "100% of requests"
  delta?:   string;       // "+18.6% vs Apr 2025"
  deltaTone?: "up" | "down";
  icon:     "wallet" | "clock" | "checkCircle" | "rotateCcw" | "folder" | "building";
  iconTone: "edify" | "amber" | "emerald" | "blue" | "violet" | "slate";
};

export const fundApprovalKpis: FundApprovalKpi[] = [
  { key: "total",       label: "Total Requested This Month", value: "UGX 214.6M",                 delta: "+18.6%", deltaTone: "up",   caption: "vs Apr 2025",    icon: "wallet",      iconTone: "emerald" },
  { key: "awaiting",    label: "Awaiting Approval",          value: "UGX 128.4M",                 caption: "12 requests",                                       icon: "clock",       iconTone: "amber"   },
  { key: "approved",    label: "Approved Today",             value: "UGX 36.2M",                  caption: "5 requests",                                        icon: "checkCircle", iconTone: "emerald" },
  { key: "returned",    label: "Returned for Review",        value: "UGX 12.8M",                  caption: "4 requests",                                        icon: "rotateCcw",   iconTone: "amber"   },
  { key: "planned",     label: "Planned Activities Funding", value: "UGX 214.6M",                 caption: "100% of requests",                                  icon: "folder",      iconTone: "violet"  },
  { key: "avg_cost",    label: "Average Cost per School",    value: "UGX 468,950",                delta: "+7.3%",  deltaTone: "up",   caption: "vs Apr 2025",    icon: "building",    iconTone: "blue"    },
];

// ────────── Approval Queue (left column) ──────────

export type FundApprovalItem = {
  id:           string;
  cceoName:     string;
  initials:     string;
  district:     string;
  region:       string;
  description:  string;                // "Includes own cluster trainings, staff visits, partner visits"
  amount:       string;                // "UGX 42.6M"
  status:       "Awaiting Approval" | "Needs Review" | "Ready" | "Returned" | "Awaiting Review";
  isOwnPlan?:   boolean;
  isActive?:    boolean;               // currently selected
  counts: {
    visits:    number;
    partners:  number;
    clusters:  number;
    trainings: number;
  };
};

export const fundApprovalQueue: FundApprovalItem[] = [
  { id: "fp-sarah",  cceoName: "Sarah M.",  initials: "SM", district: "Northern District", region: "North", description: "Includes own cluster trainings, staff visits, partner visits", amount: "UGX 42.6M", status: "Awaiting Approval", isActive: true,  counts: { visits: 24, partners: 8, clusters: 4, trainings: 6 } },
  { id: "fp-peter",  cceoName: "Peter K.",  initials: "PK", district: "Central District",  region: "North", description: "Includes own cluster trainings, staff visits, partner visits", amount: "UGX 38.4M", status: "Awaiting Approval", isOwnPlan: true, counts: { visits: 18, partners: 6, clusters: 3, trainings: 4 } },
  { id: "fp-ruth",   cceoName: "Ruth W.",   initials: "RW", district: "Eastern District",  region: "North", description: "Includes own cluster trainings, staff visits, partner visits", amount: "UGX 26.7M", status: "Needs Review",                       counts: { visits: 15, partners: 6, clusters: 3, trainings: 4 } },
  { id: "fp-moses",  cceoName: "Moses T.",  initials: "MT", district: "Northern District", region: "North", description: "Includes own cluster trainings, staff visits, partner visits", amount: "UGX 24.1M", status: "Ready",                              counts: { visits: 12, partners: 6, clusters: 3, trainings: 3 } },
  { id: "fp-joel",   cceoName: "Joel O.",   initials: "JO", district: "Western District",  region: "North", description: "Includes own cluster trainings, staff visits, partner visits", amount: "UGX 19.8M", status: "Returned",                           counts: { visits: 10, partners: 3, clusters: 2, trainings: 3 } },
  { id: "fp-grace",  cceoName: "Grace A.",  initials: "GA", district: "Central District",  region: "North", description: "Includes own cluster trainings, staff visits, partner visits", amount: "UGX 16.9M", status: "Awaiting Review",                    counts: { visits: 9,  partners: 2, clusters: 2, trainings: 3 } },
];

// ────────── Active Plan Detail (Sarah M. — May Fund Plan) ──────────

export type FundPlanLineItem = {
  category:  string;        // "Staff School Visits"
  qty:       number | "—";
  unitCost:  number | "—";
  total:     number;
};

export const activePlanDetail = {
  cceoName:     "Sarah M.",
  planLabel:    "May Fund Plan",
  district:     "Northern District",
  region:       "North",
  planPeriod:   "May 1 — May 31, 2025",
  totalRequested: "UGX 42.6M",
  status:       "Awaiting Approval" as const,
  lineItems: [
    { category: "Staff School Visits",      qty: 24,  unitCost: 140_000,   total: 3_360_000  },
    { category: "Partner School Visits",    qty: 8,   unitCost: 160_000,   total: 1_280_000  },
    { category: "Cluster Meetings",         qty: 4,   unitCost: 500_000,   total: 2_000_000  },
    { category: "Cluster Trainings",        qty: 6,   unitCost: 1_200_000, total: 7_200_000  },
    { category: "In-School Trainings",      qty: 6,   unitCost: 1_000_000, total: 6_000_000  },
    { category: "SSA Support Visits",       qty: 5,   unitCost: 150_000,   total: 750_000    },
    { category: "Participant Meals",        qty: 12,  unitCost: 20_000,    total: 240_000    },
    { category: "Transport / Field Travel", qty: "—" as const, unitCost: "—" as const, total: 21_790_000 },
  ] as FundPlanLineItem[],
  subtotal:      42_620_000,
  adjustments:  -20_000,
  totalAmount:   42_600_000,
  snapshot: {
    schoolsPlannedByStaff:    24,
    plannedSchoolVisitsByPartners: "By partners",
    clusterMeetingsPlanned:   4,
    trainingsPlanned:         12,
    totalSchoolsCovered:      "Unique planned schools",
  },
};

// ────────── Right rail — This Month / Allocation / Approval Rate / Rules ──────────

export const thisMonthSummary = {
  waitingForApproval: "UGX 128.4M",
  returned:           "UGX 12.8M",
  approvedToday:      "UGX 36.2M",
};

export const monthlyAllocation = {
  status:           "On Track" as const,
  totalAllocation:  "UGX 300.0M",
  approvedToDate:   "UGX 167.8M",
  approvedPct:      55.9,
};

export const approvalRateThisMonth = {
  rate:        72,
  segments: [
    { key: "approved", label: "Approved", pct: 72, color: "#10b981" },
    { key: "returned", label: "Returned", pct: 12, color: "#ef4444" },
    { key: "pending",  label: "Pending",  pct: 16, color: "#cbd5e1" },
  ],
};

export const approvalRules: string[] = [
  "Funds must come from approved plans.",
  "Partner visits must map to planned schools.",
  "Cluster training budget scales by participants.",
  "Returned requests need correction before re-submission.",
];

// ────────── Footer — Budget Mix + Recent Activity ──────────

export type BudgetMixSegment = {
  key:    string;
  label:  string;
  pct:    number;       // 26 → 26%
  amount: string;       // "UGX 55.2M"
  color:  string;       // hex / Tailwind
};

export const budgetMixThisMonth: BudgetMixSegment[] = [
  { key: "staff",   label: "Staff Visits",      pct: 26, amount: "UGX 55.2M", color: "#10b981" },
  { key: "partner", label: "Partner Visits",    pct: 16, amount: "UGX 34.1M", color: "#8b5cf6" },
  { key: "cluster", label: "Cluster Meetings",  pct: 12, amount: "UGX 26.3M", color: "#3b82f6" },
  { key: "train",   label: "Trainings",         pct: 23, amount: "UGX 49.3M", color: "#f59e0b" },
  { key: "ssa",     label: "SSA Support",       pct: 8,  amount: "UGX 17.6M", color: "#06b6d4" },
  { key: "other",   label: "Other",             pct: 15, amount: "UGX 32.1M", color: "#94a3b8" },
];

export type RecentApprovalActivity = {
  id:        string;
  who:       string;        // "Moses T."
  action:    "approved" | "returned" | "approved_prev";
  planLabel: string;        // "May Fund Plan", "Apr Fund Plan"
  amount:    string;        // "UGX 24.1M"
  when:      string;        // "Today, 10:24 AM"
};

export const recentApprovalActivity: RecentApprovalActivity[] = [
  { id: "ra-1", who: "Moses T.", action: "approved",      planLabel: "May Fund plan approved",            amount: "UGX 24.1M", when: "Today, 10:24 AM" },
  { id: "ra-2", who: "Joel O.",  action: "returned",      planLabel: "May Fund Plan returned for review", amount: "UGX 19.8M", when: "Today, 9:15 AM"  },
  { id: "ra-3", who: "Ruth W.",  action: "approved_prev", planLabel: "Apr Fund Plan approved",            amount: "UGX 18.6M", when: "Yesterday, 4:32 PM" },
];

// ────────── Filter bar options ──────────

export const fundApprovalFilters = {
  financialYear: "2024/2025",
  month:         "May 2025",
  region:        "North",
  district:      "All Districts",
};
