// Special Projects Dashboard — mock data layer.
//
// Special projects sit OUTSIDE the SSA 8 interventions, but per the product
// doc they still:
//   • appear in staff todos and count toward staff capacity
//   • generate fund requests
//   • follow Salesforce logging + verification rules
//   • show on School 360 (Special Project Participation)
//   • are EXCLUDED from SSA-based recommendation generation
//
// This file structures the special-projects domain so a backend swap is a
// no-op. Visibility filtering is role-aware: see getVisibleProjects() — the
// same access pattern used for the school directory.

import type { AppRole, CurrentUser } from "./schools-mock";

// ────────── Project type — extensible ──────────
//
// The product doc lists initial types but requires the module to allow
// adding more without code changes. Here the type is `string` so the
// backend can drive the option list at runtime.

export type ProjectStatus = "Planning" | "Active" | "At Risk" | "Completed" | "Delayed";
export type ImpactMeasurementType = "Schools" | "Teachers" | "Participants" | "Sessions";
export type PartnerCertificationStatus = "Certified" | "Not Certified" | "Needs Review";
export type PartnerCapacityStatus = "Available" | "Capacity Full" | "Needs Review";
export type VerificationStatus = "Not Submitted" | "Submitted" | "Verified" | "Returned" | "Rejected";

export type SpecialProject = {
  projectId: string;
  projectName: string;
  projectShortName: string;
  projectType: string;
  description?: string;
  financialYear: string;
  startDate: string;
  endDate: string;

  // Partner
  assignedPartnerId?: string;
  assignedPartnerName?: string;
  partnerCertificationStatus?: PartnerCertificationStatus;
  partnerCapacityStatus?: PartnerCapacityStatus;

  // Impact measurement
  impactMeasurementType: ImpactMeasurementType;
  targetNumber: number;

  // Counts
  schoolsEnrolled?: number;
  teachersImpacted?: number;
  participantsReached?: number;
  sessionsCompleted?: number;

  // Funding
  totalAllocation?: number;
  budgetUtilizationPct?: number;

  // State
  status: ProjectStatus;
  healthScore: number; // 0–5

  // System integration
  salesforceLoggingRequired: boolean;
  verificationStatus?: VerificationStatus;
  excludedFromSsaRecommendations: true;

  // Visibility (role-aware filter source)
  ownerCountry: "Uganda";
  visibleToRoles?: AppRole[]; // when set, restrict; when undefined, default rules apply
};

// ────────── Project Portfolio (5 initial types) ──────────

export const specialProjects: SpecialProject[] = [
  {
    projectId: "SP-EDTECH",
    projectName: "Education Technology",
    projectShortName: "EdTech",
    projectType: "EdTech",
    financialYear: "FY 2024/25",
    startDate: "2025-01-15",
    endDate: "2025-12-31",
    assignedPartnerId: "PRT-WV",
    assignedPartnerName: "World Vision",
    partnerCertificationStatus: "Certified",
    partnerCapacityStatus: "Available",
    impactMeasurementType: "Schools",
    targetNumber: 200,
    schoolsEnrolled: 156,
    teachersImpacted: 1250,
    totalAllocation: 480_000_000,
    budgetUtilizationPct: 38, // < 40% triggers Budget Risk
    status: "Active",
    healthScore: 4.5,
    salesforceLoggingRequired: true,
    verificationStatus: "Submitted",
    excludedFromSsaRecommendations: true,
    ownerCountry: "Uganda",
  },
  {
    projectId: "SP-CCSEL",
    projectName: "Christ-Centered SEL",
    projectShortName: "Christ-Centered SEL",
    projectType: "SEL",
    financialYear: "FY 2024/25",
    startDate: "2025-02-01",
    endDate: "2025-11-22",
    assignedPartnerId: "PRT-CI",
    assignedPartnerName: "Compassion Int.",
    partnerCertificationStatus: "Certified",
    partnerCapacityStatus: "Available",
    impactMeasurementType: "Schools",
    targetNumber: 130,
    schoolsEnrolled: 98,
    teachersImpacted: 812,
    totalAllocation: 380_000_000,
    budgetUtilizationPct: 65,
    status: "Active",
    healthScore: 4.2,
    salesforceLoggingRequired: true,
    verificationStatus: "Verified",
    excludedFromSsaRecommendations: true,
    ownerCountry: "Uganda",
  },
  {
    projectId: "SP-DIP",
    projectName: "International Diploma in Christ-Centered Education",
    projectShortName: "Int'l Diploma in CCE",
    projectType: "Teacher Dev",
    financialYear: "FY 2024/25",
    startDate: "2025-03-01",
    endDate: "2026-02-28",
    assignedPartnerId: "PRT-ACSI",
    assignedPartnerName: "ACSI",
    partnerCertificationStatus: "Certified",
    partnerCapacityStatus: "Available",
    impactMeasurementType: "Teachers",
    targetNumber: 800,
    schoolsEnrolled: 64,
    teachersImpacted: 612,
    totalAllocation: 520_000_000,
    budgetUtilizationPct: 71,
    status: "Active",
    healthScore: 4.6,
    salesforceLoggingRequired: true,
    verificationStatus: "Submitted",
    excludedFromSsaRecommendations: true,
    ownerCountry: "Uganda",
  },
  {
    projectId: "SP-ECC",
    projectName: "Early Childhood Curriculum",
    projectShortName: "ECC",
    projectType: "ECE",
    financialYear: "FY 2024/25",
    startDate: "2025-01-20",
    endDate: "2025-12-20",
    assignedPartnerId: "PRT-TB",
    assignedPartnerName: "Teach Beyond",
    partnerCertificationStatus: "Needs Review",
    partnerCapacityStatus: "Needs Review",
    impactMeasurementType: "Teachers",
    targetNumber: 1000,
    schoolsEnrolled: 68,
    teachersImpacted: 732,
    totalAllocation: 460_000_000,
    budgetUtilizationPct: 56,
    status: "At Risk",
    healthScore: 3.6,
    salesforceLoggingRequired: true,
    verificationStatus: "Returned",
    excludedFromSsaRecommendations: true,
    ownerCountry: "Uganda",
  },
  {
    projectId: "SP-UCU",
    projectName: "UCU Teacher Upgrading Programs",
    projectShortName: "UCU Upgrading",
    projectType: "Teacher Dev",
    financialYear: "FY 2024/25",
    startDate: "2025-02-10",
    endDate: "2025-12-10",
    assignedPartnerId: "PRT-UCU",
    assignedPartnerName: "UCU",
    partnerCertificationStatus: "Certified",
    partnerCapacityStatus: "Available",
    impactMeasurementType: "Teachers",
    targetNumber: 600,
    schoolsEnrolled: 40,
    teachersImpacted: 436,
    totalAllocation: 320_000_000,
    budgetUtilizationPct: 62,
    status: "Active",
    healthScore: 4.1,
    salesforceLoggingRequired: true,
    verificationStatus: "Submitted",
    excludedFromSsaRecommendations: true,
    ownerCountry: "Uganda",
  },
];

// ────────── Role-aware visibility ──────────
//
// Country-level roles see all projects in their country. CCEOs see only
// projects whose schools they're assigned to (mocked here as showing the
// portfolio for the country since assignment is school-driven). Partners
// see only their assigned projects.
export function getVisibleProjects(user: CurrentUser): SpecialProject[] {
  if (user.role === "Admin") return specialProjects;
  if (user.role === "CountryDirector") return specialProjects.filter((p) => p.ownerCountry === user.country);
  if (user.role === "CountryProgramLead") return specialProjects;
  if (user.role === "ImpactAssessment" || user.role === "ProgramAccountant") {
    return specialProjects.filter((p) => p.ownerCountry === user.country);
  }
  // CCEO — in real backend: WHERE project_id IN (SELECT project_id FROM
  // project_schools WHERE school_id IN (SELECT id FROM schools WHERE
  // assigned_cceo_id = currentUser.staffId)). For mock we return the same
  // country-scoped list.
  return specialProjects.filter((p) => p.ownerCountry === user.country);
}

// ────────── KPI row (8 cards) ──────────

export type SpecialProjectKpi = {
  key: string;
  label: string;
  value: string;
  trend: { delta: string; tone: "up" | "down" };
  icon:
    | "briefcase"
    | "play"
    | "school"
    | "handshake"
    | "users"
    | "wallet"
    | "calendar"
    | "shield";
  iconTone: "edify" | "green" | "blue" | "amber" | "violet" | "rose" | "emerald" | "orange";
  spark: { seed: number; trend: "up" | "down" };
};

export function computeSpecialProjectKpis(projects: SpecialProject[]): SpecialProjectKpi[] {
  const total = projects.length;
  const active = projects.filter((p) => p.status === "Active").length;
  const schoolsInProjects = 426; // rolled-up: schools tagged to ≥1 project
  const partnersAssigned = new Set(projects.map((p) => p.assignedPartnerId).filter(Boolean)).size;
  const teachersImpacted = projects.reduce((a, p) => a + (p.teachersImpacted ?? 0), 0);
  const totalAlloc = projects.reduce((a, p) => a + (p.totalAllocation ?? 0), 0);
  const closingThisMonth = projects.filter((p) => p.endDate.startsWith("2025-05")).length || 2;
  const avgHealth = projects.length
    ? Math.round((projects.reduce((a, p) => a + p.healthScore, 0) / projects.length) * 10) / 10
    : 0;

  return [
    { key: "total",     label: "Total Special Projects", value: String(total),                       trend: { delta: "9%",  tone: "up" },   icon: "briefcase", iconTone: "edify",   spark: { seed: 31, trend: "up" } },
    { key: "active",    label: "Active Projects",         value: String(active),                      trend: { delta: "12%", tone: "up" },   icon: "play",      iconTone: "green",   spark: { seed: 32, trend: "up" } },
    { key: "schools",   label: "Schools in Projects",     value: schoolsInProjects.toLocaleString(),  trend: { delta: "18%", tone: "up" },   icon: "school",    iconTone: "blue",    spark: { seed: 33, trend: "up" } },
    { key: "partners",  label: "Partners Assigned",       value: String(Math.max(partnersAssigned, 16)), trend: { delta: "6%",  tone: "up" }, icon: "handshake", iconTone: "amber",   spark: { seed: 34, trend: "up" } },
    { key: "teachers",  label: "Teachers Impacted",       value: teachersImpacted.toLocaleString(),   trend: { delta: "22%", tone: "up" },   icon: "users",     iconTone: "violet",  spark: { seed: 35, trend: "up" } },
    { key: "alloc",     label: "Total Allocation",        value: `UGX ${(totalAlloc / 1_000_000_000).toFixed(2)}B`, trend: { delta: "15%", tone: "up" }, icon: "wallet", iconTone: "emerald", spark: { seed: 36, trend: "up" } },
    { key: "closing",   label: "Closing This Month",      value: String(closingThisMonth),            trend: { delta: "20%", tone: "down" }, icon: "calendar",  iconTone: "orange",  spark: { seed: 37, trend: "down" } },
    { key: "health",    label: "Impact / Health Score",   value: `${avgHealth} / 5`,                  trend: { delta: "8%",  tone: "up" },   icon: "shield",    iconTone: "edify",   spark: { seed: 38, trend: "up" } },
  ];
}

// ────────── Action bar ──────────

export type SpecialProjectAction = {
  key: string;
  label: string;
  icon: "plus" | "import" | "handshake" | "userPlus" | "lineChart" | "download";
  primary?: boolean;
  href?: string;
  // Permission gate. Full setup actions like "New Project" are typically
  // Admin-only; the rest open to country-level roles.
  requiresRole?: AppRole[];
};

export const specialProjectActions: SpecialProjectAction[] = [
  { key: "new",           label: "New Project",          icon: "plus",      primary: true, href: "#new",            requiresRole: ["Admin", "CountryDirector"] },
  { key: "import",        label: "Import Schools",       icon: "import",    href: "#import",         requiresRole: ["Admin", "CountryDirector", "CountryProgramLead"] },
  { key: "assign_part",   label: "Assign Partner",       icon: "handshake", href: "#assign-partner", requiresRole: ["Admin", "CountryDirector"] },
  { key: "add_schools",   label: "Add Schools to Project", icon: "userPlus", href: "#add-schools",   requiresRole: ["Admin", "CountryDirector", "CountryProgramLead"] },
  { key: "track",         label: "Track Impact",         icon: "lineChart", href: "#track" },
  { key: "export",        label: "Export Summary",       icon: "download",  href: "#export" },
];

// ────────── Priority projects / needs attention ──────────

export type PriorityProjectIssueBadge =
  | "Low Teacher Impact"
  | "Low Enrollment"
  | "Delayed"
  | "Overdue Milestone"
  | "Budget Risk";

export type PriorityProjectIssue = {
  id: string;
  projectShortName: string;
  issue: string;
  badge: PriorityProjectIssueBadge;
  lastUpdated: string;
  rank: number;
};

export const priorityProjectIssues: PriorityProjectIssue[] = [
  { id: "pri-1", rank: 1, projectShortName: "Early Childhood Curriculum (ECC)", issue: "Low teacher impact against target",   badge: "Low Teacher Impact", lastUpdated: "May 15, 2025" },
  { id: "pri-2", rank: 2, projectShortName: "UCU Teacher Upgrading Programs",   issue: "Below target enrollment",              badge: "Low Enrollment",     lastUpdated: "May 14, 2025" },
  { id: "pri-3", rank: 3, projectShortName: "Christ-Centered SEL",              issue: "Enrollment behind plan",                badge: "Delayed",            lastUpdated: "May 12, 2025" },
  { id: "pri-4", rank: 4, projectShortName: "International Diploma in CCE",     issue: "Partner reports overdue",                badge: "Overdue Milestone",  lastUpdated: "May 10, 2025" },
  { id: "pri-5", rank: 5, projectShortName: "Education Technology",             issue: "Budget utilization below 40%",           badge: "Budget Risk",        lastUpdated: "May 09, 2025" },
];

// ────────── Project Impact Overview ──────────

export const teachersImpactedByProject = [
  { project: "EdTech",                value: 1250, color: "#527083" },
  { project: "Christ-Centered SEL",   value: 812,  color: "#344f5f" },
  { project: "Int'l Diploma (CCE)",   value: 612,  color: "#7ba3b8" },
  { project: "ECC",                   value: 732,  color: "#9ec1cf" },
  { project: "UCU Upgrading",         value: 436,  color: "#cfe1e8" },
];

export const projectStatusMix = [
  { label: "Active",    count: 9, pct: 75, color: "var(--color-success)" },
  { label: "Planning",  count: 2, pct: 17, color: "var(--color-edify-primary)" },
  { label: "At Risk",   count: 1, pct: 8,  color: "var(--color-edify-orange)" },
  { label: "Completed", count: 0, pct: 0,  color: "#9ec1cf" },
];

export const impactSummaryCards = [
  { key: "schools",  label: "Schools Reached",  value: "426",     delta: "18%", icon: "school" as const },
  { key: "teachers", label: "Teachers Reached", value: "3,842",   delta: "22%", icon: "users"  as const },
  { key: "health",   label: "Avg. Health Score", value: "4.6 / 5", delta: "8%",  icon: "shield" as const },
];

// ────────── Schools in Projects ──────────

export const schoolsInProjectsKpis = [
  { key: "assigned",   label: "Total Schools Assigned",        value: "426", delta: "18%", deltaTone: "up" as const },
  { key: "active",     label: "Schools Active in Projects",    value: "378", delta: "16%", deltaTone: "up" as const },
  { key: "unassigned", label: "Schools Not Yet Assigned",      value: "122", delta: "5%",  deltaTone: "up" as const },
  { key: "imported",   label: "Newly Imported This Month",     value: "34",  delta: "42%", deltaTone: "up" as const },
];

export type PrioritySchoolToAdd = {
  id: string;
  schoolName: string;
  district: string;
  priority: "High Priority" | "Medium Priority";
};

export const prioritySchoolsToAdd: PrioritySchoolToAdd[] = [
  { id: "ps-1", schoolName: "Kigun Central Primary School", district: "Kigun District",   priority: "High Priority"   },
  { id: "ps-2", schoolName: "Mayini Primary School",         district: "Mayini District",  priority: "High Priority"   },
  { id: "ps-3", schoolName: "Sunrayvale Primary School",     district: "Mayini District",  priority: "Medium Priority" },
  { id: "ps-4", schoolName: "Riverside Primary School",      district: "Kigun District",   priority: "Medium Priority" },
];

// ────────── Partner Assignment & Delivery ──────────

export const partnerKpis = [
  { key: "with_partner", label: "Projects with Partner", value: "10", delta: "10%",  deltaTone: "up" as const },
  { key: "active",       label: "Partners Active",       value: "16", delta: "7%",   deltaTone: "up" as const },
  { key: "unassigned",   label: "Unassigned Projects",   value: "2",  delta: "100%", deltaTone: "up" as const },
];

export type PartnerDeliveryRow = {
  partnerId: string;
  partner: string;
  projects: number;
  deliveryProgressPct: number;
};

export const partnerDelivery: PartnerDeliveryRow[] = [
  { partnerId: "PRT-WV",   partner: "World Vision",            projects: 2, deliveryProgressPct: 92 },
  { partnerId: "PRT-CI",   partner: "Compassion International", projects: 2, deliveryProgressPct: 85 },
  { partnerId: "PRT-TB",   partner: "Teach Beyond",            projects: 1, deliveryProgressPct: 78 },
  { partnerId: "PRT-ACSI", partner: "ACSI",                    projects: 1, deliveryProgressPct: 88 },
  { partnerId: "PRT-UCU",  partner: "UCU",                     projects: 1, deliveryProgressPct: 70 },
];

// ────────── Teacher Impact Tracker ──────────
//
// Strict rule (per product doc): only projects whose impactMeasurementType
// is "Teachers" appear here. School-based projects are NOT folded in.

export type TeacherImpactRow = {
  projectId: string;
  projectShortName: string;
  teachersTarget: number;
  teachersReached: number;
  completionPct: number;
  trend: "up" | "down";
};

export function buildTeacherImpactTracker(projects: SpecialProject[]): TeacherImpactRow[] {
  return projects
    .filter((p) => p.impactMeasurementType === "Teachers")
    .map((p) => {
      const target = p.targetNumber;
      const reached = p.teachersImpacted ?? 0;
      const pct = target > 0 ? Math.round((reached / target) * 100) : 0;
      return {
        projectId: p.projectId,
        projectShortName: p.projectShortName,
        teachersTarget: target,
        teachersReached: reached,
        completionPct: pct,
        trend: pct >= 75 ? "up" : "down",
      };
    });
}

export function teacherImpactTotals(rows: TeacherImpactRow[]) {
  const totalTarget = rows.reduce((a, r) => a + r.teachersTarget, 0);
  const totalReached = rows.reduce((a, r) => a + r.teachersReached, 0);
  const overallPct = totalTarget > 0 ? Math.round((totalReached / totalTarget) * 100) : 0;
  return { totalTarget, totalReached, overallPct };
}

// ────────── Upcoming Milestones ──────────

export type Milestone = {
  id: string;
  date: string;        // ISO YYYY-MM-DD
  title: string;
  projectName: string;
  projectId: string;
  time: string;        // "10:00 AM" or "All Day"
  location: string;    // physical, "Virtual", or "All Regions"
};

export const projectMilestones: Milestone[] = [
  { id: "ms-1", date: "2025-05-20", title: "EdTech Mid-Year Review",   projectId: "SP-EDTECH", projectName: "Education Technology",        time: "10:00 AM", location: "Kigun Office"   },
  { id: "ms-2", date: "2025-05-22", title: "SEL Enrollment Deadline",   projectId: "SP-CCSEL",  projectName: "Christ-Centered SEL",         time: "All Day",  location: "All Regions"     },
  { id: "ms-3", date: "2025-05-26", title: "Partner Check-in",          projectId: "SP-DIP",    projectName: "ACSI",                        time: "02:00 PM", location: "Virtual"         },
  { id: "ms-4", date: "2025-05-30", title: "ECC Trainer Workshop",      projectId: "SP-ECC",    projectName: "Early Childhood Curriculum",  time: "09:00 AM", location: "Mayini District" },
  { id: "ms-5", date: "2025-06-02", title: "UCU Progress Review",       projectId: "SP-UCU",    projectName: "UCU Teacher Upgrading",       time: "11:00 AM", location: "Virtual"         },
  { id: "ms-6", date: "2025-06-05", title: "Impact Reporting Due",      projectId: "ALL",       projectName: "All Projects",                time: "All Day",  location: "Kigun Office"    },
];

// ────────── Identity / header ──────────

export const specialProjectsHeader = {
  title: "Special Projects Dashboard",
  subtitle:
    "Manage high-impact programs, partner delivery, school participation, and teacher outcomes.",
  searchPlaceholder: "Search projects, partners, schools…",
  filters: {
    month: "May 2025",
    region: "All Regions",
    projectType: "All Project Types",
    partner: "All Partners",
  },
};

export const specialProjectsHeaderUser = {
  name: "Sarah Okello",
  initials: "SO",
  role: "CCEO" as const,
};

export const specialProjectsSidebarUser = {
  name: "Daniel Mwangi",
  initials: "DM",
  role: "Planning Officer",
  district: "Kigun District",
  online: true,
};

export const specialProjectsNotificationCount = 12;

// ────────── Hero banner ──────────

export const specialProjectsHero = {
  title: "Build transformational programs. Scale impact beyond the core model.",
  subtitle:
    "Special projects expand opportunity, strengthen schools, and equip teachers for lasting change.",
  impactCard: {
    label: "Special Projects Impact",
    value: "92%",
    caption: "Strong Overall",
  },
};
