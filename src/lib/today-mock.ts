// Today's Tasks — role-scoped data.
//
// The /today console renders a different day depending on who is signed
// in. A Program Lead sees their team-oversight day (approvals, team
// check-in); a CCEO sees their field day; leadership / finance / M&E /
// HR / Admin each get a purpose-built day. Identity (name, initials) is
// layered on top from the live session — see today/page.tsx.

import type { EdifyRole } from "@/lib/auth-public";

export type TodayTone = "green" | "blue" | "amber" | "rose" | "violet" | "slate";
export type TodayStatus = "Completed" | "In Progress" | "Planned" | "Overdue";

export type TodayKpi = {
  label: string;
  value: number;
  icon: string;
  tone: TodayTone;
  trend: string;
  dir: "up" | "flat" | "bad";
};

export type TodayTask = {
  title: string;
  place: string;
  status: TodayStatus;
  icon: string;
  tone: TodayTone;
  sf?: boolean;
  people?: number;
};

export type TodayBlock = { label: string; icon: string; tone: string; tasks: TodayTask[] };
export type TodayGlance = { label: string; value: number; pct: number; color: string };
export type TodayUpcoming = { date: string; title: string; sub: string; icon: string; tone: TodayTone };
export type TodayApproval = { title: string; sub: string };
export type TodayQuick = { label: string; icon: string; tone: TodayTone };
export type TodayTeamMember = { initials: string; color: string };
export type TodayPriorityFocus = { title: string; sub: string; pct: number; target: string };

export type TodayData = {
  consoleLabel: string;
  roleLabel: string;
  totalTasks: number;
  kpis: TodayKpi[];
  agenda: TodayBlock[];
  glance: TodayGlance[];
  upcoming: TodayUpcoming[];
  approvals: { label: string; items: TodayApproval[] };
  quick: TodayQuick[];
  team: { label: string; activeToday: number; offline: number; members: TodayTeamMember[] };
  priorityFocus: TodayPriorityFocus;
};

// ────────── Program Lead — team-oversight day ──────────
export const programLeadToday: TodayData = {
  consoleLabel: "Program Lead Console",
  roleLabel: "Program Lead",
  totalTasks: 24,
  kpis: [
    { label: "COMPLETED",   value: 7,  icon: "checkCircle2",  tone: "green", trend: "29% vs last week", dir: "up"   },
    { label: "IN PROGRESS", value: 10, icon: "loader",        tone: "blue",  trend: "41% vs last week", dir: "up"   },
    { label: "PLANNED",     value: 5,  icon: "clipboardCheck",tone: "amber", trend: "No change",        dir: "flat" },
    { label: "OVERDUE",     value: 2,  icon: "flame",         tone: "rose",  trend: "1 vs last week",   dir: "bad"  },
  ],
  agenda: [
    {
      label: "Morning", icon: "sun", tone: "text-[#e0902f]",
      tasks: [
        { title: "Cluster Training — Leadership Best Practice", place: "Kitgum Central Cluster Hub  ·  Kitgum District", status: "Completed",   icon: "graduationCap", tone: "green", sf: true },
        { title: "School Visit — Pope John PS",                 place: "Pope John Primary School  ·  Kitgum District",   status: "In Progress", icon: "building2",     tone: "blue",  people: 3 },
        { title: "School Visit — St. Peter PS",                 place: "St. Peter Primary School  ·  Lamwo District",    status: "Planned",     icon: "building2",     tone: "blue",  people: 2 },
      ],
    },
    {
      label: "Afternoon", icon: "sun", tone: "text-[#e0902f]",
      tasks: [
        { title: "Follow-Up Visit — Nigina UMEA",      place: "Nigina UMEA  ·  Pader District",            status: "Planned", icon: "footprints",    tone: "amber",  people: 2 },
        { title: "SSA Verification — Kal PS",          place: "Kal Primary School  ·  Agago District",     status: "Planned", icon: "clipboardCheck", tone: "amber", people: 2 },
        { title: "Partner Meeting — Compassion Intl.", place: "Compassion Field Office  ·  Gulu District", status: "Overdue", icon: "handshake",     tone: "blue",   people: 4 },
        { title: "Daily Debrief & Task Review",        place: "Virtual (Teams)",                           status: "Planned", icon: "fileText",      tone: "violet" },
      ],
    },
    {
      label: "Evening", icon: "moon", tone: "text-[#7c5cc4]",
      tasks: [
        { title: "Cluster Meeting Debrief", place: "Virtual (WhatsApp)", status: "Planned", icon: "messageSquare", tone: "violet" },
      ],
    },
  ],
  glance: [
    { label: "Completed",   value: 7,  pct: 29, color: "#22c55e" },
    { label: "In Progress", value: 10, pct: 41, color: "#3b82f6" },
    { label: "Planned",     value: 5,  pct: 21, color: "#f59e0b" },
    { label: "Overdue",     value: 2,  pct: 8,  color: "#ef4444" },
  ],
  upcoming: [
    { date: "Wed, May 14", title: "Cluster Training — Child Protection", sub: "Gulu District",  icon: "calendarCheck", tone: "blue"  },
    { date: "Thu, May 15", title: "School Visit — Oyeta PS",             sub: "Agago District", icon: "building2",     tone: "blue"  },
    { date: "Fri, May 16", title: "Partner Review Meeting",              sub: "Program Office", icon: "users",         tone: "slate" },
  ],
  approvals: {
    label: "Pending Approvals",
    items: [
      { title: "Fund Request – Week 3",    sub: "UGX 18.6M  ·  3 items" },
      { title: "Visit Report – Week 2",    sub: "3 reports" },
      { title: "Training Report – Week 2", sub: "2 reports" },
    ],
  },
  quick: [
    { label: "Log Visit",     icon: "calendarCheck", tone: "green"  },
    { label: "Request Funds", icon: "wallet",        tone: "blue"   },
    { label: "Smart Route",   icon: "navigation",    tone: "violet" },
    { label: "Team Chat",     icon: "messageSquare", tone: "slate"  },
  ],
  team: {
    label: "Team Check-in",
    activeToday: 8,
    offline: 2,
    members: [
      { initials: "AM", color: "#3f6f8f" },
      { initials: "JN", color: "#c0703a" },
      { initials: "RK", color: "#4f7a52" },
      { initials: "SO", color: "#7c5cc4" },
    ],
  },
  priorityFocus: {
    title: "Improve learning outcomes in Kitgum",
    sub: "2 more school visits to complete target",
    pct: 75,
    target: "Target: 12 visits",
  },
};

// ────────── CCEO — Core Schools field day ──────────
export const cceoToday: TodayData = {
  consoleLabel: "Core Schools Console",
  roleLabel: "Core Schools Officer",
  totalTasks: 16,
  kpis: [
    { label: "COMPLETED",   value: 5, icon: "checkCircle2",  tone: "green", trend: "2 vs last week", dir: "up"   },
    { label: "IN PROGRESS", value: 4, icon: "loader",        tone: "blue",  trend: "1 vs last week", dir: "up"   },
    { label: "PLANNED",     value: 6, icon: "clipboardCheck",tone: "amber", trend: "No change",      dir: "flat" },
    { label: "OVERDUE",     value: 1, icon: "flame",         tone: "rose",  trend: "1 vs last week", dir: "bad"  },
  ],
  agenda: [
    {
      label: "Morning", icon: "sun", tone: "text-[#e0902f]",
      tasks: [
        { title: "SSA Assessment — Bright Future Kamwokya", place: "Bright Future Kamwokya  ·  Kampala District", status: "Completed",   icon: "clipboardCheck", tone: "green", sf: true },
        { title: "Core School Visit — St. Mary's Naguru",   place: "St. Mary's Naguru  ·  Kampala District",       status: "In Progress", icon: "building2",      tone: "blue"  },
        { title: "In-School Coaching — Hilltop Bukoto",     place: "Hilltop Bukoto  ·  Kampala District",          status: "Planned",     icon: "graduationCap",  tone: "violet" },
      ],
    },
    {
      label: "Afternoon", icon: "sun", tone: "text-[#e0902f]",
      tasks: [
        { title: "Follow-Up Visit — Sunrise Kabalagala",        place: "Sunrise Kabalagala  ·  Kampala District", status: "Planned", icon: "footprints",   tone: "amber" },
        { title: "Cluster Training Prep — Christ-like Behavior", place: "Cluster Hub Naguru  ·  Kampala District", status: "Planned", icon: "graduationCap", tone: "violet" },
        { title: "Evidence Upload — Week 3 visits",             place: "Salesforce  ·  6 records",                status: "Overdue", icon: "fileText",     tone: "rose" },
      ],
    },
    {
      label: "Evening", icon: "moon", tone: "text-[#7c5cc4]",
      tasks: [
        { title: "Daily Debrief — submit to Program Lead", place: "Virtual (WhatsApp)", status: "Planned", icon: "messageSquare", tone: "violet" },
      ],
    },
  ],
  glance: [
    { label: "Completed",   value: 5, pct: 31, color: "#22c55e" },
    { label: "In Progress", value: 4, pct: 25, color: "#3b82f6" },
    { label: "Planned",     value: 6, pct: 38, color: "#f59e0b" },
    { label: "Overdue",     value: 1, pct: 6,  color: "#ef4444" },
  ],
  upcoming: [
    { date: "Wed, May 14", title: "SSA Assessment — Excel Academy Ntinda", sub: "Kampala District",  icon: "clipboardCheck", tone: "blue"  },
    { date: "Thu, May 15", title: "Core School Visit — Royal Hill Bugolobi", sub: "Kampala District", icon: "building2",     tone: "blue"  },
    { date: "Fri, May 16", title: "Cluster Training — Christ-like Behavior", sub: "Cluster Hub Ntinda", icon: "calendarCheck", tone: "slate" },
  ],
  approvals: {
    label: "Awaiting PL Approval",
    items: [
      { title: "Weekly Fund Request – Week 3", sub: "UGX 6.2M  ·  awaiting PL review" },
      { title: "Visit Report – Week 3",        sub: "3 reports submitted" },
      { title: "SSA Evidence Batch",           sub: "6 records  ·  awaiting verification" },
    ],
  },
  quick: [
    { label: "Log Visit",      icon: "calendarCheck", tone: "green"  },
    { label: "Open SSA Form",  icon: "clipboardCheck", tone: "amber"  },
    { label: "Smart Route",    icon: "navigation",    tone: "violet" },
    { label: "Upload Evidence",icon: "upload",        tone: "blue"   },
  ],
  team: {
    label: "Cluster Partners",
    activeToday: 3,
    offline: 1,
    members: [
      { initials: "HA", color: "#3f6f8f" },
      { initials: "NE", color: "#4f7a52" },
      { initials: "MC", color: "#c0703a" },
    ],
  },
  priorityFocus: {
    title: "Complete SSA cycle for core schools",
    sub: "3 more SSA assessments to hit target",
    pct: 67,
    target: "Target: 9 SSA assessments",
  },
};

// ────────── Country Director — country oversight day ──────────
export const directorToday: TodayData = {
  consoleLabel: "Country Director Console",
  roleLabel: "Country Director",
  totalTasks: 16,
  kpis: [
    { label: "COMPLETED",   value: 5, icon: "checkCircle2",  tone: "green", trend: "2 vs last week", dir: "up"   },
    { label: "IN PROGRESS", value: 6, icon: "loader",        tone: "blue",  trend: "On pace",        dir: "flat" },
    { label: "PLANNED",     value: 4, icon: "clipboardCheck",tone: "amber", trend: "Steady",         dir: "flat" },
    { label: "OVERDUE",     value: 1, icon: "flame",         tone: "rose",  trend: "1 escalated",    dir: "bad"  },
  ],
  agenda: [
    { label: "Morning", icon: "sun", tone: "text-[#e0902f]", tasks: [
      { title: "Leadership Review — country KPIs", place: "Director's Office  ·  Country rollup", status: "Completed",   icon: "fileText", tone: "green" },
      { title: "1:1 — Program Lead (North)",       place: "Virtual (Teams)",                      status: "In Progress", icon: "users",    tone: "blue", people: 2 },
    ]},
    { label: "Afternoon", icon: "sun", tone: "text-[#e0902f]", tasks: [
      { title: "Approve Monthly Plans — 4 teams",    place: "Director's Office  ·  Approvals queue", status: "Planned", icon: "clipboardCheck", tone: "amber" },
      { title: "Regional Performance Review — West", place: "Virtual (Teams)  ·  West region",       status: "Overdue", icon: "fileText",       tone: "rose" },
    ]},
    { label: "Evening", icon: "moon", tone: "text-[#7c5cc4]", tasks: [
      { title: "Prep — quarterly board update", place: "Director's Office", status: "Planned", icon: "fileText", tone: "violet" },
    ]},
  ],
  glance: [
    { label: "Completed",   value: 5, pct: 31, color: "#22c55e" },
    { label: "In Progress", value: 6, pct: 38, color: "#3b82f6" },
    { label: "Planned",     value: 4, pct: 25, color: "#f59e0b" },
    { label: "Overdue",     value: 1, pct: 6,  color: "#ef4444" },
  ],
  upcoming: [
    { date: "Wed, May 14", title: "Budget Approval Session", sub: "Finance + Program Leads", icon: "clipboardCheck", tone: "amber" },
    { date: "Fri, May 16", title: "Country Leadership Sync", sub: "All Program Leads",       icon: "users",          tone: "slate" },
  ],
  approvals: {
    label: "Pending Approvals",
    items: [
      { title: "Monthly Plan — North team", sub: "UGX 186.4M  ·  awaiting sign-off" },
      { title: "Monthly Plan — West team",  sub: "UGX 124.7M  ·  awaiting sign-off" },
      { title: "Special Project — EdTech",  sub: "Returned for amendment" },
    ],
  },
  quick: [
    { label: "Approvals",  icon: "clipboardCheck", tone: "amber"  },
    { label: "Analytics",  icon: "fileText",       tone: "blue"   },
    { label: "Reports",    icon: "fileText",       tone: "violet" },
    { label: "Leads Sync", icon: "users",          tone: "slate"  },
  ],
  team: {
    label: "Leadership Team",
    activeToday: 6,
    offline: 1,
    members: [
      { initials: "DM", color: "#3f6f8f" },
      { initials: "GA", color: "#c0703a" },
      { initials: "PO", color: "#4f7a52" },
      { initials: "SN", color: "#7c5cc4" },
    ],
  },
  priorityFocus: {
    title: "Recover West region target",
    sub: "West is at 65% vs the 72% national average",
    pct: 65,
    target: "Target: 72% achievement",
  },
};

// ────────── Regional VP — cross-country day ──────────
export const rvpToday: TodayData = {
  consoleLabel: "Regional VP Console",
  roleLabel: "Regional VP",
  totalTasks: 17,
  kpis: [
    { label: "COMPLETED",   value: 4, icon: "checkCircle2",  tone: "green", trend: "1 vs last week", dir: "up"   },
    { label: "IN PROGRESS", value: 5, icon: "loader",        tone: "blue",  trend: "On pace",        dir: "flat" },
    { label: "PLANNED",     value: 6, icon: "clipboardCheck",tone: "amber", trend: "3 added",        dir: "up"   },
    { label: "OVERDUE",     value: 2, icon: "flame",         tone: "rose",  trend: "2 vs last week", dir: "bad"  },
  ],
  agenda: [
    { label: "Morning", icon: "sun", tone: "text-[#e0902f]", tasks: [
      { title: "Country Review Call — Uganda", place: "Virtual (Teams)", status: "Completed",   icon: "users", tone: "green", people: 5 },
      { title: "Country Review Call — Kenya",  place: "Virtual (Teams)", status: "In Progress", icon: "users", tone: "blue",  people: 4 },
    ]},
    { label: "Afternoon", icon: "sun", tone: "text-[#e0902f]", tasks: [
      { title: "Cross-country Fund Approval queue", place: "Regional Office  ·  2 requests", status: "Planned", icon: "clipboardCheck", tone: "amber" },
      { title: "Quarterly Target Sync — Directors", place: "Virtual (Teams)",                status: "Overdue", icon: "users",          tone: "rose", people: 6 },
    ]},
    { label: "Evening", icon: "moon", tone: "text-[#7c5cc4]", tasks: [
      { title: "Review regional forecast deck", place: "Regional Office", status: "Planned", icon: "fileText", tone: "violet" },
    ]},
  ],
  glance: [
    { label: "Completed",   value: 4, pct: 24, color: "#22c55e" },
    { label: "In Progress", value: 5, pct: 29, color: "#3b82f6" },
    { label: "Planned",     value: 6, pct: 35, color: "#f59e0b" },
    { label: "Overdue",     value: 2, pct: 12, color: "#ef4444" },
  ],
  upcoming: [
    { date: "Wed, May 14", title: "Annual Operating Cycle Gateway", sub: "Region-wide",   icon: "calendarCheck", tone: "blue"  },
    { date: "Fri, May 16", title: "Budget & Funds Review",          sub: "All countries", icon: "wallet",        tone: "amber" },
  ],
  approvals: {
    label: "Pending Approvals",
    items: [
      { title: "Q2 School Visits — Uganda", sub: "UGX 420M  ·  pending" },
      { title: "Teacher Training — Kenya",  sub: "UGX 350M  ·  under review" },
    ],
  },
  quick: [
    { label: "Fund Approval", icon: "clipboardCheck", tone: "amber"  },
    { label: "Country View",  icon: "fileText",       tone: "blue"   },
    { label: "Forecasts",     icon: "fileText",       tone: "violet" },
    { label: "Directors",     icon: "users",          tone: "slate"  },
  ],
  team: {
    label: "Country Directors",
    activeToday: 4,
    offline: 1,
    members: [
      { initials: "SO", color: "#3f6f8f" },
      { initials: "JK", color: "#c0703a" },
      { initials: "AM", color: "#4f7a52" },
    ],
  },
  priorityFocus: {
    title: "Close the regional fund approval queue",
    sub: "2 cross-country requests awaiting decision",
    pct: 60,
    target: "Target: cleared by Friday",
  },
};

// ────────── Program Accountant — finance ops day ──────────
export const accountantToday: TodayData = {
  consoleLabel: "Finance Console",
  roleLabel: "Program Accountant",
  totalTasks: 24,
  kpis: [
    { label: "COMPLETED",   value: 9, icon: "checkCircle2",  tone: "green", trend: "4 vs last week", dir: "up"   },
    { label: "IN PROGRESS", value: 7, icon: "loader",        tone: "blue",  trend: "On pace",        dir: "flat" },
    { label: "PLANNED",     value: 5, icon: "clipboardCheck",tone: "amber", trend: "Steady",         dir: "flat" },
    { label: "OVERDUE",     value: 3, icon: "flame",         tone: "rose",  trend: "3 vs last week", dir: "bad"  },
  ],
  agenda: [
    { label: "Morning", icon: "sun", tone: "text-[#e0902f]", tasks: [
      { title: "Weekly Disbursement Batch — Week 3", place: "Finance Office  ·  6 teams", status: "Completed",   icon: "wallet",   tone: "green" },
      { title: "Confirm Treasury Receipts",          place: "Finance Office",             status: "In Progress", icon: "fileText", tone: "blue" },
    ]},
    { label: "Afternoon", icon: "sun", tone: "text-[#e0902f]", tasks: [
      { title: "Review Fund Requests — 6 teams",            place: "Finance Office  ·  Approvals", status: "Planned", icon: "clipboardCheck", tone: "amber" },
      { title: "Expense Reconciliation — overdue accounts", place: "Finance Office  ·  3 accounts", status: "Overdue", icon: "wallet",        tone: "rose" },
    ]},
    { label: "Evening", icon: "moon", tone: "text-[#7c5cc4]", tasks: [
      { title: "Generate Funds & Disbursement report", place: "Finance Office", status: "Planned", icon: "fileText", tone: "violet" },
    ]},
  ],
  glance: [
    { label: "Completed",   value: 9, pct: 38, color: "#22c55e" },
    { label: "In Progress", value: 7, pct: 29, color: "#3b82f6" },
    { label: "Planned",     value: 5, pct: 21, color: "#f59e0b" },
    { label: "Overdue",     value: 3, pct: 12, color: "#ef4444" },
  ],
  upcoming: [
    { date: "Wed, May 14", title: "Salesforce Intake Queue review", sub: "Data intake", icon: "upload", tone: "blue"  },
    { date: "Thu, May 15", title: "Cost Settings review",           sub: "Finance",     icon: "wallet", tone: "slate" },
  ],
  approvals: {
    label: "Pending Approvals",
    items: [
      { title: "Fund Request — Week 3",   sub: "UGX 42.6M  ·  awaiting disbursement" },
      { title: "Reimbursement — North",   sub: "UGX 7.2M  ·  supervisor reviewed" },
      { title: "Balance Return — Week 2", sub: "UGX 5.4M  ·  to confirm" },
    ],
  },
  quick: [
    { label: "Disburse",  icon: "wallet",        tone: "green"  },
    { label: "Fund Reqs", icon: "clipboardCheck",tone: "amber"  },
    { label: "Reconcile", icon: "fileText",      tone: "blue"   },
    { label: "Reports",   icon: "fileText",      tone: "violet" },
  ],
  team: {
    label: "Finance Team",
    activeToday: 4,
    offline: 1,
    members: [
      { initials: "MT", color: "#3f6f8f" },
      { initials: "IM", color: "#c0703a" },
      { initials: "PC", color: "#4f7a52" },
    ],
  },
  priorityFocus: {
    title: "Clear overdue expense accountability",
    sub: "3 accounts past the 2-week return window",
    pct: 82,
    target: "Target: 0 overdue accounts",
  },
};

// ────────── Impact Assessment — M&E / data-quality day ──────────
export const impactToday: TodayData = {
  consoleLabel: "M&E / Impact Console",
  roleLabel: "Impact Assessment",
  totalTasks: 23,
  kpis: [
    { label: "COMPLETED",   value: 8, icon: "checkCircle2",  tone: "green", trend: "3 vs last week", dir: "up"   },
    { label: "IN PROGRESS", value: 6, icon: "loader",        tone: "blue",  trend: "On pace",        dir: "flat" },
    { label: "PLANNED",     value: 7, icon: "clipboardCheck",tone: "amber", trend: "4 added",        dir: "up"   },
    { label: "OVERDUE",     value: 2, icon: "flame",         tone: "rose",  trend: "2 vs last week", dir: "bad"  },
  ],
  agenda: [
    { label: "Morning", icon: "sun", tone: "text-[#e0902f]", tasks: [
      { title: "Data Verification Funnel review", place: "M&E Office", status: "Completed",   icon: "clipboardCheck", tone: "green" },
      { title: "Quality Check batch — Week 19",   place: "M&E Office", status: "In Progress", icon: "fileText",       tone: "blue" },
    ]},
    { label: "Afternoon", icon: "sun", tone: "text-[#e0902f]", tasks: [
      { title: "Validate Recent Data Uploads", place: "M&E Office  ·  Salesforce", status: "Planned", icon: "upload",   tone: "amber" },
      { title: "Partner Performance review",   place: "Virtual (Teams)",           status: "Overdue", icon: "fileText", tone: "rose" },
    ]},
    { label: "Evening", icon: "moon", tone: "text-[#7c5cc4]", tasks: [
      { title: "Compile Verified Impact summary", place: "M&E Office", status: "Planned", icon: "fileText", tone: "violet" },
    ]},
  ],
  glance: [
    { label: "Completed",   value: 8, pct: 35, color: "#22c55e" },
    { label: "In Progress", value: 6, pct: 26, color: "#3b82f6" },
    { label: "Planned",     value: 7, pct: 30, color: "#f59e0b" },
    { label: "Overdue",     value: 2, pct: 9,  color: "#ef4444" },
  ],
  upcoming: [
    { date: "Wed, May 14", title: "Salesforce Queue triage", sub: "Data intake", icon: "upload",   tone: "blue"  },
    { date: "Thu, May 15", title: "Top Issues review",       sub: "Quality",     icon: "fileText", tone: "slate" },
  ],
  approvals: {
    label: "Verification Queue",
    items: [
      { title: "SSA Evidence Batch — Week 19", sub: "21 schools  ·  awaiting verification" },
      { title: "Returned Records — North",     sub: "6 records  ·  re-check" },
    ],
  },
  quick: [
    { label: "Verify Data", icon: "clipboardCheck", tone: "green"  },
    { label: "Data Intake", icon: "upload",         tone: "blue"   },
    { label: "Quality",     icon: "fileText",       tone: "amber"  },
    { label: "Reports",     icon: "fileText",       tone: "violet" },
  ],
  team: {
    label: "M&E Partners",
    activeToday: 4,
    offline: 1,
    members: [
      { initials: "GA", color: "#3f6f8f" },
      { initials: "HA", color: "#c0703a" },
      { initials: "NE", color: "#4f7a52" },
    ],
  },
  priorityFocus: {
    title: "Raise data verification pass rate",
    sub: "21 schools awaiting final verification",
    pct: 81,
    target: "Target: 95% verified",
  },
};

// ────────── Human Resource — people & performance day ──────────
export const hrToday: TodayData = {
  consoleLabel: "People & Performance",
  roleLabel: "Human Resource",
  totalTasks: 16,
  kpis: [
    { label: "COMPLETED",   value: 5, icon: "checkCircle2",  tone: "green", trend: "2 vs last week", dir: "up"   },
    { label: "IN PROGRESS", value: 4, icon: "loader",        tone: "blue",  trend: "On pace",        dir: "flat" },
    { label: "PLANNED",     value: 6, icon: "clipboardCheck",tone: "amber", trend: "Steady",         dir: "flat" },
    { label: "OVERDUE",     value: 1, icon: "flame",         tone: "rose",  trend: "1 escalated",    dir: "bad"  },
  ],
  agenda: [
    { label: "Morning", icon: "sun", tone: "text-[#e0902f]", tasks: [
      { title: "Performance Review session — North leads", place: "HR Office", status: "Completed",   icon: "users",    tone: "green", people: 5 },
      { title: "Staff Support case review",                place: "HR Office", status: "In Progress", icon: "fileText", tone: "blue" },
    ]},
    { label: "Afternoon", icon: "sun", tone: "text-[#e0902f]", tasks: [
      { title: "Leave Approvals — pending requests", place: "HR Office  ·  3 staff", status: "Planned", icon: "clipboardCheck", tone: "amber" },
      { title: "Open HR Decisions from CD / RVP",    place: "HR Office",             status: "Overdue", icon: "fileText",       tone: "rose" },
    ]},
    { label: "Evening", icon: "moon", tone: "text-[#7c5cc4]", tasks: [
      { title: "Update recognition board", place: "HR Office", status: "Planned", icon: "fileText", tone: "violet" },
    ]},
  ],
  glance: [
    { label: "Completed",   value: 5, pct: 31, color: "#22c55e" },
    { label: "In Progress", value: 4, pct: 25, color: "#3b82f6" },
    { label: "Planned",     value: 6, pct: 38, color: "#f59e0b" },
    { label: "Overdue",     value: 1, pct: 6,  color: "#ef4444" },
  ],
  upcoming: [
    { date: "Wed, May 14", title: "Aggregated Field Intelligence review", sub: "Country patterns", icon: "fileText", tone: "blue"  },
    { date: "Fri, May 16", title: "Quarterly Performance cycle kickoff",   sub: "All teams",        icon: "users",    tone: "slate" },
  ],
  approvals: {
    label: "Pending Approvals",
    items: [
      { title: "Leave Request — 3 staff", sub: "Medical + annual" },
      { title: "Staff Support case",      sub: "Routed from Program Lead" },
    ],
  },
  quick: [
    { label: "Reviews",     icon: "users",         tone: "green"  },
    { label: "Leave",       icon: "clipboardCheck",tone: "amber"  },
    { label: "Field Intel", icon: "fileText",      tone: "blue"   },
    { label: "Recognition", icon: "fileText",      tone: "violet" },
  ],
  team: {
    label: "People Team",
    activeToday: 5,
    offline: 1,
    members: [
      { initials: "AW", color: "#3f6f8f" },
      { initials: "DM", color: "#c0703a" },
      { initials: "GA", color: "#4f7a52" },
    ],
  },
  priorityFocus: {
    title: "Close open performance reviews",
    sub: "12 reviews active across 5 program leads",
    pct: 70,
    target: "Target: all closed this cycle",
  },
};

// ────────── Admin — system administration day ──────────
export const adminToday: TodayData = {
  consoleLabel: "Admin Console",
  roleLabel: "System Administrator",
  totalTasks: 14,
  kpis: [
    { label: "COMPLETED",   value: 6, icon: "checkCircle2",  tone: "green", trend: "Steady",   dir: "flat" },
    { label: "IN PROGRESS", value: 3, icon: "loader",        tone: "blue",  trend: "On pace",  dir: "flat" },
    { label: "PLANNED",     value: 4, icon: "clipboardCheck",tone: "amber", trend: "Steady",   dir: "flat" },
    { label: "OVERDUE",     value: 1, icon: "flame",         tone: "rose",  trend: "1 ticket", dir: "bad"  },
  ],
  agenda: [
    { label: "Morning", icon: "sun", tone: "text-[#e0902f]", tasks: [
      { title: "User Access review — new joiners", place: "Admin Console", status: "Completed",   icon: "users",    tone: "green" },
      { title: "Audit Log review — Week 19",       place: "Admin Console", status: "In Progress", icon: "fileText", tone: "blue" },
    ]},
    { label: "Afternoon", icon: "sun", tone: "text-[#e0902f]", tasks: [
      { title: "Feature Flag check — release gates", place: "Admin Console",               status: "Planned", icon: "clipboardCheck", tone: "amber" },
      { title: "Resolve access request tickets",     place: "Admin Console  ·  2 tickets", status: "Overdue", icon: "fileText",       tone: "rose" },
    ]},
    { label: "Evening", icon: "moon", tone: "text-[#7c5cc4]", tasks: [
      { title: "System health & backup check", place: "Admin Console", status: "Planned", icon: "fileText", tone: "violet" },
    ]},
  ],
  glance: [
    { label: "Completed",   value: 6, pct: 43, color: "#22c55e" },
    { label: "In Progress", value: 3, pct: 21, color: "#3b82f6" },
    { label: "Planned",     value: 4, pct: 29, color: "#f59e0b" },
    { label: "Overdue",     value: 1, pct: 7,  color: "#ef4444" },
  ],
  upcoming: [
    { date: "Wed, May 14", title: "Role & permissions audit", sub: "All users", icon: "fileText", tone: "blue"  },
    { date: "Thu, May 15", title: "Quarterly config review",  sub: "Platform",  icon: "fileText", tone: "slate" },
  ],
  approvals: {
    label: "Pending Approvals",
    items: [
      { title: "Access Request — 2 users", sub: "Role elevation" },
    ],
  },
  quick: [
    { label: "Users",      icon: "users",         tone: "green"  },
    { label: "Audit Logs", icon: "fileText",      tone: "blue"   },
    { label: "Flags",      icon: "clipboardCheck",tone: "amber"  },
    { label: "Reports",    icon: "fileText",      tone: "violet" },
  ],
  team: {
    label: "Platform Team",
    activeToday: 3,
    offline: 1,
    members: [
      { initials: "EA", color: "#3f6f8f" },
      { initials: "SO", color: "#c0703a" },
      { initials: "MT", color: "#4f7a52" },
    ],
  },
  priorityFocus: {
    title: "Complete the quarterly access audit",
    sub: "Role / permission review across all users",
    pct: 88,
    target: "Target: signed off this week",
  },
};

const TODAY_BY_ROLE: Record<EdifyRole, TodayData> = {
  CCEO:                cceoToday,
  CountryProgramLead:  programLeadToday,
  CountryDirector:     directorToday,
  RVP:                 rvpToday,
  ProgramAccountant:   accountantToday,
  ImpactAssessment:    impactToday,
  HumanResource:       hrToday,
  Admin:               adminToday,
  // Partner sub-types reuse the program-lead "today" view as a sane
  // default — the proper partner-today data lives on the Partner
  // Command Center, not on /today.
  PartnerAdmin:        programLeadToday,
  PartnerFieldOfficer: cceoToday,
  PartnerViewer:       programLeadToday,
};

// Every role gets a purpose-built day; unknown roles fall back to the
// Program Lead view (the broadest field-management surface).
export function todayDataForRole(role: EdifyRole): TodayData {
  return TODAY_BY_ROLE[role] ?? programLeadToday;
}
