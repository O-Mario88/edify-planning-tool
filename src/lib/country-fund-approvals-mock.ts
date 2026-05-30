// Country Director Fund Approvals — mock data layer.
//
// CD-scope replica: numbers match the reference design exactly. Lives
// alongside the Program-Lead mock (`fund-approvals-mock.ts`) so the
// /approvals route can render either flavour based on role.

// ────────── 6 KPI tiles ──────────

export type CountryFundKpi = {
  key:        string;
  label:      string;
  value:      string;
  caption?:   string;
  delta?:     string;
  deltaTone?: "up" | "down";
  icon:       "wallet" | "clock" | "checkCircle" | "rotateCcw" | "calendar" | "building";
  iconTone:   "emerald" | "amber" | "rose" | "violet" | "slate";
};

export const countryFundKpis: CountryFundKpi[] = [
  { key: "total",     label: "Total Requested This Month", value: "UGX 1.24B",   caption: "64 requests",            delta: "+18.4%", deltaTone: "up", icon: "wallet",      iconTone: "emerald" },
  { key: "awaiting",  label: "Awaiting CD Approval",        value: "UGX 642.7M",  caption: "18 requests",                                           icon: "clock",       iconTone: "amber"   },
  { key: "approved",  label: "Approved Today",              value: "UGX 152.3M",  caption: "6 requests",                                            icon: "checkCircle", iconTone: "emerald" },
  { key: "returned",  label: "Returned for Review",         value: "UGX 78.6M",   caption: "3 requests",                                            icon: "rotateCcw",   iconTone: "rose"    },
  { key: "projects",  label: "Special Projects Funding",    value: "UGX 216.4M",  caption: "5 projects",                                            icon: "calendar",    iconTone: "violet"  },
  { key: "admin",     label: "Admin Budget Pending",        value: "UGX 56.8M",   caption: "4 requests",                                            icon: "building",    iconTone: "slate"   },
];

// ────────── Fund Approval Queue (7 leads) ──────────

export type CountryFundQueueItem = {
  id:        string;
  leadName:  string;
  initials:  string;
  region:    string;          // "North" or "Special Projects Coordinator"
  planLabel: string;          // "Team fund plan" or "Special project plan"
  amount:    string;          // "UGX 186.4M"
  status:    "Awaiting Approval" | "Returned";
  isActive?: boolean;
};

export const countryFundQueue: CountryFundQueueItem[] = [
  { id: "cfp-sarah",   leadName: "Sarah M.",   initials: "SM", region: "North",                            planLabel: "Team fund plan",     amount: "UGX 186.4M", status: "Awaiting Approval", isActive: true },
  { id: "cfp-peter",   leadName: "Peter K.",   initials: "PK", region: "West",                             planLabel: "Team fund plan",     amount: "UGX 124.7M", status: "Awaiting Approval" },
  { id: "cfp-ruth",    leadName: "Ruth W.",    initials: "RW", region: "East",                             planLabel: "Team fund plan",     amount: "UGX 98.3M",  status: "Awaiting Approval" },
  { id: "cfp-grace",   leadName: "Grace A.",   initials: "GA", region: "Central",                          planLabel: "Team fund plan",     amount: "UGX 86.2M",  status: "Awaiting Approval" },
  { id: "cfp-joel",    leadName: "Joel O.",    initials: "JO", region: "North",                            planLabel: "Team fund plan",     amount: "UGX 62.1M",  status: "Awaiting Approval" },
  { id: "cfp-moses",   leadName: "Moses T.",   initials: "MT", region: "North",                            planLabel: "Team fund plan",     amount: "UGX 47.6M",  status: "Returned" },
  { id: "cfp-lillian", leadName: "Lillian N.", initials: "LN", region: "Special Projects Coordinator",     planLabel: "Special project plan", amount: "UGX 38.7M",  status: "Awaiting Approval" },
];

// ────────── Active Plan Detail (Sarah M. — North Team Fund Plan) ──────────

export type CountryFundLineItem = {
  category: string;
  qty:      number | "—";
  unitCost: number | "—";
  total:    number;
};

export const countryActivePlan = {
  leadName:     "Sarah M.",
  planLabel:    "North Team Fund Plan",
  planPeriod:   "May 1 — May 31, 2025",
  submitted:    "May 9, 2025",
  status:       "Awaiting Approval" as const,
  totalRequested: 186_400_000,
  lineItems: [
    { category: "Staff School Visits",      qty: 32,  unitCost: 140_000,   total: 4_480_000  },
    { category: "Partner School Visits",    qty: 18,  unitCost: 160_000,   total: 2_880_000  },
    { category: "Cluster Meetings",         qty: 6,   unitCost: 500_000,   total: 3_000_000  },
    { category: "Cluster Trainings",        qty: 8,   unitCost: 1_200_000, total: 9_600_000  },
    { category: "In-School Trainings",      qty: 10,  unitCost: 1_000_000, total: 10_000_000 },
    { category: "SSA Support Visits",       qty: 7,   unitCost: 150_000,   total: 1_050_000  },
    { category: "Participant Meals",        qty: 250, unitCost: 20_000,    total: 5_000_000  },
    { category: "Transport / Field Travel", qty: "—" as const, unitCost: "—" as const, total: 21_010_000 },
  ] as CountryFundLineItem[],
  subtotal:     57_020_000,
  adjustments: -20_000,
  totalAmount:  186_400_000,
  snapshot: {
    schoolsByStaff:           48,
    schoolsByPartners:        "By partners",
    clusterMeetingsPlanned:   "Cluster meetings planned",
    trainingsPlanned:         "In-School & cluster",
    totalSchoolsCovered:      "Across 6 districts",
    includedCceoPlans:        "Across the region",
  },
};

// ────────── CCEO Contributions (Included in Plan) ──────────

export type CceoContribution = {
  id:       string;
  name:     string;
  initials: string;
  amount:   string;          // "UGX 42.6M"
  role:     "Lead CCEO" | "CCEO";
};

export const cceoContributions: CceoContribution[] = [
  { id: "ct-sarah", name: "Sarah M.", initials: "SM", amount: "UGX 42.6M", role: "Lead CCEO" },
  { id: "ct-peter", name: "Peter K.", initials: "PK", amount: "UGX 38.4M", role: "CCEO" },
  { id: "ct-ruth",  name: "Ruth W.",  initials: "RW", amount: "UGX 26.7M", role: "CCEO" },
  { id: "ct-grace", name: "Grace A.", initials: "GA", amount: "UGX 25.3M", role: "CCEO" },
];

export const cceoContributionTotal = {
  amount:   "UGX 133.0M",
  pctOfPlan: 71.4,
};

// ────────── Right rail summaries ──────────

export const countryThisMonth = {
  waitingForApproval: "UGX 642.7M",
  returned:           "UGX 78.6M",
  approvedToday:      "UGX 152.3M",
};

export const countryPlanBudget = {
  totalAllocation:  "UGX 2.80B",
  approvedToDate:   "UGX 1.76B",
  approvedPct:      62.9,
};

export const countryApprovalRate = {
  rate: 72,
  segments: [
    { key: "approved", label: "Approved", pct: 72, color: "#10b981" },
    { key: "returned", label: "Returned", pct: 12, color: "#ef4444" },
    { key: "pending",  label: "Pending",  pct: 16, color: "#cbd5e1" },
  ],
};

// ────────── Footer — Budget Mix + Recent Activity ──────────

export type CountryBudgetMixSegment = {
  key:    string;
  label:  string;
  pct:    number;
  amount: string;
  color:  string;
};

export const countryBudgetMix: CountryBudgetMixSegment[] = [
  { key: "staff",    label: "Staff Visits",     pct: 33, amount: "UGX 221.4M", color: "#10b981" },
  { key: "partner",  label: "Partner Visits",   pct: 17, amount: "UGX 114.2M", color: "#8b5cf6" },
  { key: "cluster",  label: "Cluster Meetings", pct: 14, amount: "UGX 92.6M",  color: "#3b82f6" },
  { key: "train",    label: "Trainings",        pct: 11, amount: "UGX 72.1M",  color: "#f59e0b" },
  { key: "transport",label: "Transport",        pct: 9,  amount: "UGX 60.7M",  color: "#06b6d4" },
  { key: "meals",    label: "Meals",            pct: 9,  amount: "UGX 60.2M",  color: "#ec4899" },
  { key: "other",    label: "Other",            pct: 7,  amount: "UGX 47.5M",  color: "#94a3b8" },
];

export type CountryRecentActivity = {
  id:        string;
  who:       string;
  planLabel: string;
  amount:    string;
  when:      string;
  action:    "approved" | "submitted" | "returned" | "approved_prev";
};

export const countryRecentActivity: CountryRecentActivity[] = [
  { id: "cra-1", who: "Peter K.",  planLabel: "West plan approved",   amount: "UGX 124.7M", when: "Today, 10:12 AM",  action: "approved"      },
  { id: "cra-2", who: "Sarah M.",  planLabel: "North plan submitted", amount: "UGX 186.4M", when: "Today, 9:45 AM",  action: "submitted"     },
  { id: "cra-3", who: "Ruth W.",   planLabel: "East plan returned",   amount: "UGX 98.3M",  when: "Today, 9:15 AM",  action: "returned"      },
  { id: "cra-4", who: "Joel O.",   planLabel: "North plan approved",  amount: "UGX 62.1M",  when: "Yesterday, 4:32 PM", action: "approved_prev" },
];

// ────────── Filter bar ──────────

export const countryFundFilters = {
  financialYear: "FY 2024/25",
  month:         "May 2025",
  country:       "Uganda",
};

// ────────── Admin Fund Request drawer ──────────

export type AdminBudgetCategory = {
  key:   string;
  label: string;
  icon:  "home" | "printer" | "monitor" | "truck" | "bed" | "utensils" | "users" | "message";
};

export const adminBudgetCategories: AdminBudgetCategory[] = [
  { key: "rent",          label: "Rent",                icon: "home"     },
  { key: "printing",      label: "Printing",            icon: "printer"  },
  { key: "it",            label: "IT",                  icon: "monitor"  },
  { key: "transport",     label: "Transport",           icon: "truck"    },
  { key: "accommodation", label: "Accommodation",       icon: "bed"      },
  { key: "feeding",       label: "Feeding",             icon: "utensils" },
  { key: "stakeholder",   label: "Stakeholder Meeting", icon: "users"    },
  { key: "communication", label: "Communication",       icon: "message"  },
];
