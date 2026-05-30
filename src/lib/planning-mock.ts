// Mock data for the Planning Tool dashboard.
// Shaped to map cleanly onto the existing Prisma schema for later DB wiring.

export type PlanningKpi = {
  label: string;
  value: string;
  status: "Planned" | "Estimated";
  trend: string;
  trendType: "up" | "down";
  icon:
    | "users"
    | "users2"
    | "school"
    | "userPlus"
    | "calendarCheck"
    | "wallet"
    | "wallet2";
};

export const planningKpis: PlanningKpi[] = [
  { label: "Cluster Trainings",                value: "28",         status: "Planned",   trend: "12% vs Apr", trendType: "up",   icon: "users" },
  { label: "Cluster Meetings",                 value: "16",         status: "Planned",   trend: "6% vs Apr",  trendType: "up",   icon: "users2" },
  { label: "My School Visits",                 value: "64",         status: "Planned",   trend: "18% vs Apr", trendType: "up",   icon: "school" },
  { label: "Partner Follow-Up Visits",         value: "82",         status: "Planned",   trend: "11% vs Apr", trendType: "up",   icon: "userPlus" },
  { label: "Total Planned Activities This Month", value: "190",     status: "Planned",   trend: "14% vs Apr", trendType: "up",   icon: "calendarCheck" },
  { label: "Total Cost This Month",            value: "UGX 1,24,560", status: "Estimated", trend: "9% vs Apr",  trendType: "up",   icon: "wallet" },
  { label: "Total Cost This Week",             value: "UGX 28,450",   status: "Estimated", trend: "7% vs Apr",  trendType: "up",   icon: "wallet2" },
];

export type Priority = "High" | "Medium" | "Low";
export type PlanStatus = "Planned" | "Draft" | "Submitted for Approval";
export type DeliveryMode = "In-School" | "Cluster" | "Partner";
export type AssignedTo = "Me" | "Cluster" | "Partner" | "Planned";

export type PlannedActivityRow = {
  schoolName: string;
  district: string;
  schoolType: "Primary" | "Cluster";
  priority: Priority;
  ssaStatus: { label: "Low SSA" | "Moderate SSA" | "High SSA"; pct: string };
  intervention: string;
  recommended: string;
  delivery: DeliveryMode;
  assignedTo: AssignedTo;
  schedule: { line1: string; line2: string };
  estCost: number;
  status: PlanStatus;
};

export const plannedActivities: PlannedActivityRow[] = [
  {
    schoolName: "Greenfields Primary School",
    district: "Central",
    schoolType: "Primary",
    priority: "High",
    ssaStatus: { label: "Low SSA", pct: "(42%)" },
    intervention: "Teaching Learning",
    recommended: "In-School Coaching",
    delivery: "In-School",
    assignedTo: "Me",
    schedule: { line1: "May / Week 1", line2: "(5–9 May)" },
    estCost: 2000,
    status: "Planned",
  },
  {
    schoolName: "Sunrayvale Primary School",
    district: "Central",
    schoolType: "Primary",
    priority: "High",
    ssaStatus: { label: "Low SSA", pct: "(58%)" },
    intervention: "Foundational Literacy",
    recommended: "Cluster Training",
    delivery: "Cluster",
    assignedTo: "Planned",
    schedule: { line1: "Sunrayvale Cluster", line2: "15 May 2025" },
    estCost: 1500,
    status: "Planned",
  },
  {
    schoolName: "Riverside Primary School",
    district: "Central",
    schoolType: "Primary",
    priority: "High",
    ssaStatus: { label: "Low SSA", pct: "(31%)" },
    intervention: "Numeracy",
    recommended: "In-School Coaching",
    delivery: "In-School",
    assignedTo: "Me",
    schedule: { line1: "May / Week 2", line2: "(12–16 May)" },
    estCost: 1800,
    status: "Planned",
  },
  {
    schoolName: "Westview Cluster",
    district: "Central",
    schoolType: "Cluster",
    priority: "Medium",
    ssaStatus: { label: "Moderate SSA", pct: "(67%)" },
    intervention: "Classroom Practice",
    recommended: "Cluster Training",
    delivery: "Cluster",
    assignedTo: "Partner",
    schedule: { line1: "Westview Cluster", line2: "19 May 2025" },
    estCost: 3000,
    status: "Planned",
  },
  {
    schoolName: "Hilltop Primary School",
    district: "Central",
    schoolType: "Primary",
    priority: "High",
    ssaStatus: { label: "Low SSA", pct: "(19%)" },
    intervention: "Attendance",
    recommended: "SSA Support + Home Visits",
    delivery: "In-School",
    assignedTo: "Partner",
    schedule: { line1: "May / Week 1", line2: "(5–9 May)" },
    estCost: 1600,
    status: "Planned",
  },
  {
    schoolName: "Eastside Cluster Meeting",
    district: "Central",
    schoolType: "Cluster",
    priority: "Medium",
    ssaStatus: { label: "Low SSA", pct: "(72%)" },
    intervention: "Leadership & Mgmt",
    recommended: "Cluster Meeting",
    delivery: "Cluster",
    assignedTo: "Me",
    schedule: { line1: "Eastside Cluster", line2: "22 May 2025" },
    estCost: 800,
    status: "Planned",
  },
  {
    schoolName: "Maple Grove Primary School",
    district: "Central",
    schoolType: "Primary",
    priority: "High",
    ssaStatus: { label: "Low SSA", pct: "(48%)" },
    intervention: "Teaching Learning",
    recommended: "In-School Coaching",
    delivery: "In-School",
    assignedTo: "Me",
    schedule: { line1: "May / Week 3", line2: "(19–23 May)" },
    estCost: 2000,
    status: "Draft",
  },
  // ── 25 additional rows so pagination has real pages to navigate. ──
  { schoolName: "Northgate Primary School",  district: "North",  schoolType: "Primary", priority: "Medium", ssaStatus: { label: "Moderate SSA", pct: "(64%)" }, intervention: "Classroom Practice", recommended: "Cluster Training",      delivery: "Cluster",  assignedTo: "Partner", schedule: { line1: "May / Week 2",      line2: "(12–16 May)" }, estCost: 2400, status: "Planned" },
  { schoolName: "Lakeside Primary School",   district: "North",  schoolType: "Primary", priority: "High",   ssaStatus: { label: "Low SSA",      pct: "(38%)" }, intervention: "Numeracy",           recommended: "In-School Coaching + Visit", delivery: "In-School", assignedTo: "Me",      schedule: { line1: "May / Week 3",      line2: "(19–23 May)" }, estCost: 2200, status: "Planned" },
  { schoolName: "Mountview Primary School",  district: "East",   schoolType: "Primary", priority: "High",   ssaStatus: { label: "Low SSA",      pct: "(29%)" }, intervention: "Foundational Literacy", recommended: "SSA Follow-Up",           delivery: "In-School", assignedTo: "Me",      schedule: { line1: "May / Week 4",      line2: "(26–30 May)" }, estCost: 1900, status: "Planned" },
  { schoolName: "Cedar Hill Primary",        district: "East",   schoolType: "Primary", priority: "Low",    ssaStatus: { label: "High SSA",     pct: "(81%)" }, intervention: "Parent Engagement",   recommended: "Cluster Meeting",        delivery: "Cluster",  assignedTo: "Cluster", schedule: { line1: "Cedar Hill Cluster", line2: "08 May 2025" }, estCost: 900,  status: "Submitted for Approval" },
  { schoolName: "Brook Valley Primary",      district: "West",   schoolType: "Primary", priority: "Medium", ssaStatus: { label: "Moderate SSA", pct: "(56%)" }, intervention: "Pedagogy",            recommended: "Mentoring Session",       delivery: "In-School", assignedTo: "Me",      schedule: { line1: "May / Week 1",      line2: "(5–9 May)" }, estCost: 1500, status: "Draft"   },
  { schoolName: "Stone Ridge Primary",       district: "West",   schoolType: "Primary", priority: "High",   ssaStatus: { label: "Low SSA",      pct: "(33%)" }, intervention: "Teaching Learning",   recommended: "Teacher Coaching",       delivery: "In-School", assignedTo: "Me",      schedule: { line1: "May / Week 2",      line2: "(12–16 May)" }, estCost: 2100, status: "Planned" },
  { schoolName: "Pine Forest Cluster",       district: "West",   schoolType: "Cluster", priority: "Medium", ssaStatus: { label: "Moderate SSA", pct: "(61%)" }, intervention: "Leadership & Mgmt",   recommended: "Cluster Training",      delivery: "Cluster",  assignedTo: "Partner", schedule: { line1: "Pine Forest Cluster",line2: "21 May 2025" }, estCost: 3200, status: "Planned" },
  { schoolName: "Heritage Primary School",   district: "South",  schoolType: "Primary", priority: "High",   ssaStatus: { label: "Low SSA",      pct: "(41%)" }, intervention: "Attendance",          recommended: "SSA Support + Home Visits", delivery: "In-School", assignedTo: "Partner", schedule: { line1: "May / Week 3",      line2: "(19–23 May)" }, estCost: 1700, status: "Planned" },
  { schoolName: "Sunset Valley Primary",     district: "South",  schoolType: "Primary", priority: "Medium", ssaStatus: { label: "Moderate SSA", pct: "(68%)" }, intervention: "Classroom Practice",  recommended: "In-School Coaching",     delivery: "In-School", assignedTo: "Me",      schedule: { line1: "May / Week 4",      line2: "(26–30 May)" }, estCost: 1800, status: "Submitted for Approval" },
  { schoolName: "Crystal Spring Primary",    district: "Central",schoolType: "Primary", priority: "High",   ssaStatus: { label: "Low SSA",      pct: "(35%)" }, intervention: "Foundational Literacy", recommended: "Teacher Coaching",       delivery: "In-School", assignedTo: "Me",      schedule: { line1: "Jun / Week 1",      line2: "(2–6 Jun)" }, estCost: 2000, status: "Planned" },
  { schoolName: "Willow Creek Cluster",      district: "Central",schoolType: "Cluster", priority: "Medium", ssaStatus: { label: "Moderate SSA", pct: "(59%)" }, intervention: "Leadership & Mgmt",   recommended: "Cluster Meeting",        delivery: "Cluster",  assignedTo: "Cluster", schedule: { line1: "Willow Creek Cluster", line2: "12 Jun 2025" }, estCost: 1200, status: "Draft"   },
  { schoolName: "Golden Gate Primary",       district: "North",  schoolType: "Primary", priority: "Low",    ssaStatus: { label: "High SSA",     pct: "(78%)" }, intervention: "Pedagogy",            recommended: "Mentoring Session",       delivery: "In-School", assignedTo: "Me",      schedule: { line1: "Jun / Week 1",      line2: "(2–6 Jun)" }, estCost: 1400, status: "Planned" },
  { schoolName: "Silver Lake Primary",       district: "East",   schoolType: "Primary", priority: "High",   ssaStatus: { label: "Low SSA",      pct: "(27%)" }, intervention: "Numeracy",            recommended: "In-School Coaching + Visit", delivery: "In-School", assignedTo: "Partner", schedule: { line1: "Jun / Week 2",      line2: "(9–13 Jun)" }, estCost: 2300, status: "Planned" },
  { schoolName: "Diamond Hill Primary",      district: "East",   schoolType: "Primary", priority: "Medium", ssaStatus: { label: "Moderate SSA", pct: "(62%)" }, intervention: "Teaching Learning",   recommended: "Teacher Coaching",       delivery: "In-School", assignedTo: "Me",      schedule: { line1: "Jun / Week 2",      line2: "(9–13 Jun)" }, estCost: 1900, status: "Submitted for Approval" },
  { schoolName: "Eagle Ridge Primary",       district: "West",   schoolType: "Primary", priority: "High",   ssaStatus: { label: "Low SSA",      pct: "(44%)" }, intervention: "Attendance",          recommended: "SSA Follow-Up",           delivery: "In-School", assignedTo: "Me",      schedule: { line1: "Jun / Week 3",      line2: "(16–20 Jun)" }, estCost: 1600, status: "Planned" },
  { schoolName: "Bayview Cluster Meeting",   district: "West",   schoolType: "Cluster", priority: "Medium", ssaStatus: { label: "Moderate SSA", pct: "(65%)" }, intervention: "Leadership & Mgmt",   recommended: "Cluster Meeting",        delivery: "Cluster",  assignedTo: "Cluster", schedule: { line1: "Bayview Cluster",    line2: "18 Jun 2025" }, estCost: 1000, status: "Planned" },
  { schoolName: "Highland Primary School",   district: "North",  schoolType: "Primary", priority: "High",   ssaStatus: { label: "Low SSA",      pct: "(36%)" }, intervention: "Foundational Literacy", recommended: "In-School Coaching",     delivery: "In-School", assignedTo: "Me",      schedule: { line1: "Jun / Week 3",      line2: "(16–20 Jun)" }, estCost: 2000, status: "Draft"   },
  { schoolName: "Spring Meadow Primary",     district: "South",  schoolType: "Primary", priority: "Medium", ssaStatus: { label: "Moderate SSA", pct: "(57%)" }, intervention: "Pedagogy",            recommended: "Cluster Training",      delivery: "Cluster",  assignedTo: "Partner", schedule: { line1: "Spring Meadow Cluster", line2: "25 Jun 2025" }, estCost: 2800, status: "Planned" },
  { schoolName: "Foxglove Primary",          district: "Central",schoolType: "Primary", priority: "Low",    ssaStatus: { label: "High SSA",     pct: "(83%)" }, intervention: "Parent Engagement",   recommended: "SSA Follow-Up",           delivery: "In-School", assignedTo: "Me",      schedule: { line1: "Jun / Week 4",      line2: "(23–27 Jun)" }, estCost: 1100, status: "Submitted for Approval" },
  { schoolName: "Brookfield Primary",        district: "Central",schoolType: "Primary", priority: "High",   ssaStatus: { label: "Low SSA",      pct: "(31%)" }, intervention: "Numeracy",            recommended: "In-School Coaching + Visit", delivery: "In-School", assignedTo: "Me",      schedule: { line1: "Jul / Week 1",      line2: "(30 Jun–4 Jul)" }, estCost: 2400, status: "Planned" },
  { schoolName: "Acacia Grove Primary",      district: "East",   schoolType: "Primary", priority: "Medium", ssaStatus: { label: "Moderate SSA", pct: "(60%)" }, intervention: "Classroom Practice",  recommended: "Teacher Coaching",       delivery: "In-School", assignedTo: "Partner", schedule: { line1: "Jul / Week 1",      line2: "(30 Jun–4 Jul)" }, estCost: 1800, status: "Planned" },
  { schoolName: "Ironwood Cluster",          district: "East",   schoolType: "Cluster", priority: "Medium", ssaStatus: { label: "Moderate SSA", pct: "(63%)" }, intervention: "Leadership & Mgmt",   recommended: "Cluster Meeting",        delivery: "Cluster",  assignedTo: "Cluster", schedule: { line1: "Ironwood Cluster",   line2: "07 Jul 2025" }, estCost: 950,  status: "Planned" },
  { schoolName: "Marigold Primary",          district: "West",   schoolType: "Primary", priority: "High",   ssaStatus: { label: "Low SSA",      pct: "(40%)" }, intervention: "Teaching Learning",   recommended: "Mentoring Session",       delivery: "In-School", assignedTo: "Me",      schedule: { line1: "Jul / Week 2",      line2: "(7–11 Jul)" }, estCost: 2100, status: "Submitted for Approval" },
  { schoolName: "Whispering Pines Primary",  district: "North",  schoolType: "Primary", priority: "Low",    ssaStatus: { label: "High SSA",     pct: "(76%)" }, intervention: "Parent Engagement",   recommended: "Cluster Training",      delivery: "Cluster",  assignedTo: "Partner", schedule: { line1: "Whispering Pines Cluster", line2: "14 Jul 2025" }, estCost: 1300, status: "Planned" },
  { schoolName: "Hawthorne Primary",         district: "South",  schoolType: "Primary", priority: "High",   ssaStatus: { label: "Low SSA",      pct: "(39%)" }, intervention: "Attendance",          recommended: "SSA Support + Home Visits", delivery: "In-School", assignedTo: "Me",      schedule: { line1: "Jul / Week 3",      line2: "(14–18 Jul)" }, estCost: 1700, status: "Planned" },
];

export type Urgency = "Urgent" | "High" | "Medium";

export type PriorityPlanningRow = {
  rank: number;
  school: string;
  ssaScore: string;
  severity: { label: "Very Low" | "Low" | "Moderate"; tone: "red" | "amber" | "amber2" };
  chips: ("No Training" | "No Visits")[];
  weakest: string;
  recommended: string;
  urgency: Urgency;
};

export const priorityPlanning: PriorityPlanningRow[] = [
  {
    rank: 1,
    school: "Hilltop Primary School",
    ssaScore: "SSA Score: 19%",
    severity: { label: "Very Low", tone: "red" },
    chips: ["No Training", "No Visits"],
    weakest: "Attendance",
    recommended: "SSA Support + Home Visits",
    urgency: "Urgent",
  },
  {
    rank: 2,
    school: "Greenfields Primary School",
    ssaScore: "SSA Score: 42%",
    severity: { label: "Low", tone: "amber" },
    chips: ["No Training", "No Visits"],
    weakest: "Teaching Learning",
    recommended: "In-School Coaching",
    urgency: "High",
  },
  {
    rank: 3,
    school: "Maple Grove Primary School",
    ssaScore: "SSA Score: 48%",
    severity: { label: "Low", tone: "amber" },
    chips: ["No Training", "No Visits"],
    weakest: "Teaching Learning",
    recommended: "In-School Coaching",
    urgency: "High",
  },
  {
    rank: 4,
    school: "Sunrayvale Primary School",
    ssaScore: "SSA Score: 58%",
    severity: { label: "Moderate", tone: "amber2" },
    chips: ["No Visits"],
    weakest: "Foundational Literacy",
    recommended: "Cluster Training",
    urgency: "Medium",
  },
  {
    rank: 5,
    school: "Riverside Primary School",
    ssaScore: "SSA Score: 31%",
    severity: { label: "Very Low", tone: "red" },
    chips: ["No Training", "No Visits"],
    weakest: "Numeracy",
    recommended: "In-School Coaching + Visit",
    urgency: "Urgent",
  },
];

export type PlanningSummaryTile = {
  key: string;
  label: string;
  value: number;
  icon:
    | "noTraining"
    | "noVisit"
    | "neither"
    | "completed"
    | "notCompleted"
    | "inactive"
    | "active";
  tone: "amber" | "red" | "purple" | "green" | "orange" | "grey" | "edify";
};

export const planningSummary: PlanningSummaryTile[] = [
  { key: "no_training",     label: "No Training",              value: 38,  icon: "noTraining",   tone: "amber" },
  { key: "no_visits",       label: "No Visits",                value: 42,  icon: "noVisit",      tone: "red" },
  { key: "neither",         label: "Neither Training Nor Visit", value: 46, icon: "neither",     tone: "purple" },
  { key: "completed",       label: "Completed SSA",            value: 78,  icon: "completed",    tone: "green" },
  { key: "not_completed",   label: "Not Completed SSA",        value: 112, icon: "notCompleted", tone: "orange" },
  { key: "inactive",        label: "Inactive Schools",         value: 31,  icon: "inactive",     tone: "grey" },
  { key: "active",          label: "Active Schools",           value: 159, icon: "active",       tone: "edify" },
];

export type QuickAction = {
  key: string;
  label: { line1: string; line2: string };
  icon: "calendarPlus" | "calendarDays" | "starCheck" | "mapPin" | "send";
  primary?: boolean;
};

export const quickActions: QuickAction[] = [
  { key: "generate", label: { line1: "Generate",     line2: "Monthly Plan" },     icon: "calendarPlus" },
  { key: "leave",    label: { line1: "Schedule",     line2: "Leave" },            icon: "calendarDays" },
  { key: "review",   label: { line1: "Review",       line2: "Recommendations" }, icon: "starCheck" },
  { key: "open",     label: { line1: "Open Route",   line2: "Planner" },         icon: "mapPin" },
  { key: "submit",   label: { line1: "Submit Plan for", line2: "Approval" },     icon: "send", primary: true },
];

export type WeeklyOverviewSlice = {
  label: "Planned" | "Draft" | "To Plan";
  value: number;
  pct: number;
  color: string;
};

export const weeklyOverview: WeeklyOverviewSlice[] = [
  { label: "Planned", value: 18, pct: 64, color: "#527083" },
  { label: "Draft",   value: 6,  pct: 21, color: "#f59e0b" },
  { label: "To Plan", value: 4,  pct: 14, color: "#9ec1cf" },
];

export type PlanningUser = {
  name: string;
  initials: string;
  role: string;
  online: boolean;
};

export const planningUser: PlanningUser = {
  name: "Daniel Mwangi",
  initials: "DM",
  role: "Planning Officer",
  online: true,
};

export const planningHeader = {
  title: "Planning Tool",
  subtitle: "Schedule visits, follow-ups, and cluster trainings — every recommendation inherits from an SSA gap in the school's own cluster.",
  filters: {
    financialYear: "FY 2024/25",
    month: "May 2025",
    region: "North",
    staff: "Me",
  },
  searchPlaceholder: "Search schools, clusters…",
};

export const planningFooter = {
  note: "All recommendations are SSA-informed. Plan strategically to improve school performance and maximize reach.",
  asOf: "Data as of 15 May 2025, 08:30 AM",
};

export const planningPagination = {
  showing: "Showing 1 to 7 of 190 activities",
  current: 1,
  pages: [1, 2, 3, 4, 5, "…", 27] as const,
};
