// Mock data shaped to match the Prisma schema, ready to swap for `db.*` calls later.

export type Trend = "up" | "down";
export type ChipTone = "red" | "amber" | "green" | "blue" | "grey";

export type StatCard = {
  label: string;
  value: string;
  trend: string;
  trendType: Trend;
  chart: "spark" | "ring";
  icon:
    | "calendar"
    | "users"
    | "school"
    | "cloud"
    | "refresh"
    | "target"
    | "shield"
    | "school2";
  variant: "primary" | "orange" | "red";
  pct?: number;
};

export const statCards: StatCard[] = [
  { label: "This Month's Activities",  value: "132", trend: "18% vs Apr", trendType: "up",   chart: "spark", icon: "calendar", variant: "primary" },
  { label: "Cluster Trainings",        value: "14",  trend: "27% vs Apr", trendType: "up",   chart: "spark", icon: "users",    variant: "primary" },
  { label: "In-School Activities",     value: "78",  trend: "15% vs Apr", trendType: "up",   chart: "spark", icon: "school",   variant: "primary" },
  { label: "Awaiting Salesforce ID",   value: "11",  trend: "8% vs Apr",  trendType: "down", chart: "spark", icon: "cloud",    variant: "orange" },
  { label: "Returned Corrections",     value: "6",   trend: "25% vs Apr", trendType: "down", chart: "spark", icon: "refresh",  variant: "red" },
  { label: "Monthly Target Progress",  value: "81%", trend: "9% vs Apr",  trendType: "up",   chart: "ring",  icon: "target",   variant: "primary", pct: 81 },
  { label: "Verified Visits",          value: "92%", trend: "6% vs Apr",  trendType: "up",   chart: "ring",  icon: "shield",   variant: "primary", pct: 92 },
  { label: "Schools Reached",          value: "34",  trend: "7 vs Apr",   trendType: "up",   chart: "ring",  icon: "school2",  variant: "primary", pct: 80 },
];

export type PlannerWeek = {
  label: string;
  range: string;
  cluster: number;
  inSchool: number;
  clusterFill: number; // out of 5
  inSchoolFill: number; // out of 6
};

export const plannerWeeks: PlannerWeek[] = [
  { label: "Week 1", range: "Apr 28 – May 4",  cluster: 3, inSchool: 16, clusterFill: 3, inSchoolFill: 6 },
  { label: "Week 2", range: "May 5 – May 11",  cluster: 4, inSchool: 18, clusterFill: 4, inSchoolFill: 6 },
  { label: "Week 3", range: "May 12 – May 18", cluster: 3, inSchool: 20, clusterFill: 3, inSchoolFill: 6 },
  { label: "Week 4", range: "May 19 – May 25", cluster: 2, inSchool: 14, clusterFill: 2, inSchoolFill: 5 },
  { label: "Week 5", range: "May 26 – May 31", cluster: 2, inSchool: 10, clusterFill: 2, inSchoolFill: 4 },
];

export type ActivityBreakdownRow = {
  label: string;
  count: number;
  pct: number;
  color: string;
  icon: "users" | "school" | "refresh" | "target" | "calendar";
};

export const activityBreakdown: ActivityBreakdownRow[] = [
  { label: "Cluster Trainings",          count: 14, pct: 11, color: "#527083", icon: "users" },
  { label: "School Visits by Me",        count: 42, pct: 32, color: "#344f5f", icon: "school" },
  { label: "Follow-Up Visits by Partner",count: 18, pct: 14, color: "#7aa1b2", icon: "users" },
  { label: "SSA Follow-Up",              count: 20, pct: 15, color: "#f59e0b", icon: "refresh" },
  { label: "In-School Coaching",         count: 16, pct: 12, color: "#9ec1cf", icon: "school" },
  { label: "Lessons Observation",        count: 10, pct: 8,  color: "#b0d3df", icon: "target" },
  { label: "Handover Meetings",          count: 12, pct: 9,  color: "#cfe1e8", icon: "calendar" },
];

export type PrioritySchool = {
  rank: number;
  school: string;
  cluster: string;
  riskLabel: string;
  riskTone: "red" | "amber";
  ssa: string;
  lastVisit: string;
};

export const prioritySchools: PrioritySchool[] = [
  { rank: 1, school: "Hope Primary School",     cluster: "Kigun Central Cluster", riskLabel: "Weak SSA Score",            riskTone: "red",   ssa: "42%", lastVisit: "May 02" },
  { rank: 2, school: "St. Peter Primary",       cluster: "Maryhill Cluster",      riskLabel: "No Visit",                  riskTone: "amber", ssa: "38%", lastVisit: "—" },
  { rank: 3, school: "Grace Primary School",    cluster: "Kigun West Cluster",    riskLabel: "No Training",               riskTone: "amber", ssa: "45%", lastVisit: "Apr 24" },
  { rank: 4, school: "Olive Children's School", cluster: "Kigun East Cluster",    riskLabel: "Inactive Risk",             riskTone: "amber", ssa: "48%", lastVisit: "Apr 18" },
  { rank: 5, school: "Bright Future PS",        cluster: "Maryhill Cluster",      riskLabel: "Neither Visit Nor Training",riskTone: "red",   ssa: "25%", lastVisit: "—" },
];

export type SalesforceQueueRow = {
  activity: string;
  school: string;
  completedOn: string;
  matchStatus: "Smart Match" | "Possible Match" | "No Match";
  action: { label: "Confirm" | "Review" | "Create ID"; tone: "outline" | "primary" };
};

export const salesforceQueue: SalesforceQueueRow[] = [
  { activity: "In-School Coaching", school: "Hope Primary School",   completedOn: "May 09", matchStatus: "Smart Match",    action: { label: "Confirm",   tone: "outline" } },
  { activity: "School Visit",       school: "St. Peter Primary",     completedOn: "May 08", matchStatus: "Smart Match",    action: { label: "Confirm",   tone: "outline" } },
  { activity: "SSA Follow-Up",      school: "Grace Primary School",  completedOn: "May 07", matchStatus: "Possible Match", action: { label: "Review",    tone: "outline" } },
  { activity: "Cluster Training",   school: "Kigun Central Cluster", completedOn: "May 06", matchStatus: "No Match",       action: { label: "Create ID", tone: "primary" } },
  { activity: "Handover Meeting",   school: "Bright Future PS",      completedOn: "May 05", matchStatus: "Smart Match",    action: { label: "Confirm",   tone: "outline" } },
];

export type TargetRing = {
  label: string;
  pct: number;
  value: string;
  sub: string;
  star?: boolean;
};

export const targetRings: TargetRing[] = [
  { label: "Monthly Pace",         pct: 81, value: "81%",     sub: "On Track" },
  { label: "Activities Completed", pct: 81, value: "132/163", sub: "On Track" },
  { label: "Schools Supported",    pct: 81, value: "34/42",   sub: "On Track" },
  { label: "Learners Reached",     pct: 84, value: "8,420",   sub: "On Track" },
  { label: "Quality Score",        pct: 92, value: "92%",     sub: "Excellent", star: true },
];

export type ClusterScheduleRow = {
  cluster: string;
  date: string;
  district: string;
  state: { label: "Ready" | "In Progress" | "Planned"; tone: "green" | "amber" | "blue" };
};

export const clusterSchedule: ClusterScheduleRow[] = [
  { cluster: "Kigun Central Cluster", date: "May 06", district: "Kigun", state: { label: "Ready",       tone: "green" } },
  { cluster: "Maryhill Cluster",      date: "May 10", district: "Kigun", state: { label: "Ready",       tone: "green" } },
  { cluster: "Kigun West Cluster",    date: "May 14", district: "Kigun", state: { label: "In Progress", tone: "amber" } },
  { cluster: "Kigun East Cluster",    date: "May 20", district: "Kigun", state: { label: "In Progress", tone: "amber" } },
  { cluster: "North Ridge Cluster",   date: "May 27", district: "Kigun", state: { label: "Planned",     tone: "blue"  } },
];

export type RouteRow = {
  bundle: string;
  weeks: string;
  schools: string;
  impact: { label: "High Impact" | "Medium Impact"; tone: "red" | "amber" };
  open: string;
};

export const routeOpportunities: RouteRow[] = [
  { bundle: "Route Bundle A", weeks: "Wk 1-2", schools: "12 Schools", impact: { label: "High Impact",   tone: "red"   }, open: "8 Open" },
  { bundle: "Route Bundle B", weeks: "Wk 3-3", schools: "10 Schools", impact: { label: "Medium Impact", tone: "amber" }, open: "6 Open" },
  { bundle: "Route Bundle C", weeks: "Wk 3-4", schools: "9 Schools",  impact: { label: "High Impact",   tone: "red"   }, open: "5 Open" },
  { bundle: "Route Bundle D", weeks: "Wk 4-5", schools: "7 Schools",  impact: { label: "Medium Impact", tone: "amber" }, open: "3 Open" },
];

export type PlannerStat = { label: string; value: string; sub?: string; pct: number };

export const plannerStats: PlannerStat[] = [
  { label: "Total Days Planned",  value: "22", sub: "/23", pct: 96 },
  { label: "Cluster Trainings",   value: "14", pct: 78 },
  { label: "In-School Activities",value: "78", pct: 88 },
  { label: "Buffer Days",         value: "1",  pct: 18 },
];

export type QuickContext = {
  schoolName: string;
  cluster: string;
  contactName: string;
  contactRole: string;
  phone: string;
  weakest: string;
  recommended: { primary: string; secondary: string };
  lastVisit: string;
  nextVisit: string;
};

export const quickContext: QuickContext = {
  schoolName: "Hope Primary School",
  cluster: "Kigun Central Cluster",
  contactName: "Jane Achieng",
  contactRole: "HT",
  phone: "+254 712 345 678",
  weakest: "SSA Follow-Up",
  recommended: { primary: "Improve SSA engagement", secondary: "& feedback loops" },
  lastVisit: "May 02, 2025",
  nextVisit: "May 16, 2025",
};

export type CurrentUser = {
  name: string;
  initials: string;
  role: string;
  district: string;
  online: boolean;
};

export const currentUser: CurrentUser = {
  name: "Sarah Okello",
  initials: "SO",
  role: "CCEO",
  district: "Kigun District",
  online: true,
};

export const motivation = {
  greeting: "Great momentum, Sarah!",
  body: ["You are leading with excellence and creating real change.", "Keep inspiring schools and communities across Kigun District."],
  monthStreak: 8,
  qualityScore: 92,
  consistencyWeeks: 4,
};

export const heroCopy = {
  headline: "Lead boldly. Serve deeply. Change lives.",
  body: ["Every school you reach becomes a community that thrives.", "Your leadership today builds a brighter tomorrow."],
};
