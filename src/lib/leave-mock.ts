// Leave & Holiday Planning Dashboard — mock data + planning engine.
//
// CRITICAL — leave is NOT cosmetic. Every blocking source feeds into a
// single source-of-truth function `getPlanningAvailability()`. Cluster date
// pickers, the Planning Tool, the CCEO dashboard, and the Country Program
// Lead dashboard all consume that same function — there is no duplicated
// availability logic in the UI.
//
// Blocking sources (per product doc):
//   • Sunday — always blocked (Saturday remains OPEN unless individually marked)
//   • Public holidays — blocked for the country
//   • Approved leave — blocked for the staff
//   • Blackout dates — blocked org-wide
//   • Conference week — blocked org-wide if configured as fully blocking

import type { AppRole } from "./schools-mock";

// ────────── Domain types ──────────

export type LeaveType = "Annual Leave" | "Medical Leave" | "Personal Leave" | "Other";
export type LeaveStatus = "Pending" | "Approved" | "Rejected" | "Cancelled";
export type PlanningImpact = "Blocked" | "Potential" | "None";
export type BlockedDateType =
  | "Leave"
  | "Public Holiday"
  | "Sunday"
  | "Blackout"
  | "Conference Week";

export type ActivityType =
  | "Cluster Training"
  | "In-School Activity"
  | "Partner Visit"
  | "SSA Support"
  | "Special Project";

export type LeaveRequest = {
  leaveId: string;
  staffId: string;
  staffName: string;
  region: "North" | "South" | "East" | "West" | "Central";
  leaveType: LeaveType;
  startDate: string;        // ISO YYYY-MM-DD
  endDate: string;
  selectedDates: string[];  // dates user picked
  validLeaveDates: string[]; // after excluding holidays + Sundays
  excludedDates: string[];
  excludedReasonByDate: Record<string, "Public Holiday" | "Sunday" | "Blackout" | "Conference Week">;
  workingDays: number;
  approvalStatus: LeaveStatus;
  planningImpact: PlanningImpact;
  affectedActivityIds: string[];
};

export type PublicHoliday = {
  date: string;
  title: string;
  scope: "Country";
  country: "Uganda";
};

export type BlackoutBlock = {
  startDate: string;
  endDate: string;
  title: string;
  scope: "Organization";
  type: "Blackout" | "Conference Week";
  blocksPlanning: boolean;
};

// ────────── Static seed: holidays + blackouts + conferences ──────────

export const publicHolidays: PublicHoliday[] = [
  { date: "2025-07-04", title: "Independence Day", scope: "Country", country: "Uganda" },
  { date: "2025-07-30", title: "Eid-ul-Adha",      scope: "Country", country: "Uganda" },
  { date: "2025-12-25", title: "Christmas Day",    scope: "Country", country: "Uganda" },
  { date: "2026-01-01", title: "New Year's Day",   scope: "Country", country: "Uganda" },
];

export const conferenceWeeks: BlackoutBlock[] = [
  {
    startDate: "2025-07-21",
    endDate: "2025-07-25",
    title: "Staff Conference Week",
    scope: "Organization",
    type: "Conference Week",
    blocksPlanning: true,
  },
];

export const blackoutDates: BlackoutBlock[] = [
  {
    startDate: "2025-08-15",
    endDate: "2025-08-16",
    title: "Finance Closure",
    scope: "Organization",
    type: "Blackout",
    blocksPlanning: true,
  },
];

// ────────── Leave requests (seed) ──────────

export const leaveRequests: LeaveRequest[] = [
  {
    leaveId: "LV-1001",
    staffId: "STF-SK-001",
    staffName: "Sarah Khan",
    region: "North",
    leaveType: "Annual Leave",
    startDate: "2025-07-14",
    endDate: "2025-07-16",
    selectedDates: ["2025-07-14", "2025-07-15", "2025-07-16"],
    validLeaveDates: ["2025-07-14", "2025-07-15", "2025-07-16"],
    excludedDates: [],
    excludedReasonByDate: {},
    workingDays: 3,
    approvalStatus: "Approved",
    planningImpact: "Blocked",
    affectedActivityIds: ["ACT-201", "ACT-202", "ACT-203"],
  },
  {
    leaveId: "LV-1002",
    staffId: "STF-AR-002",
    staffName: "Ali Raza",
    region: "Central",
    leaveType: "Medical Leave",
    startDate: "2025-07-18",
    endDate: "2025-07-18",
    selectedDates: ["2025-07-18"],
    validLeaveDates: ["2025-07-18"],
    excludedDates: [],
    excludedReasonByDate: {},
    workingDays: 1,
    approvalStatus: "Approved",
    planningImpact: "Blocked",
    affectedActivityIds: ["ACT-310"],
  },
  {
    leaveId: "LV-1003",
    staffId: "STF-FN-003",
    staffName: "Fatima Noor",
    region: "Central",
    leaveType: "Annual Leave",
    startDate: "2025-07-28",
    endDate: "2025-07-30",
    selectedDates: ["2025-07-28", "2025-07-29", "2025-07-30"],
    validLeaveDates: ["2025-07-28", "2025-07-29"], // 30th is Eid-ul-Adha → excluded
    excludedDates: ["2025-07-30"],
    excludedReasonByDate: { "2025-07-30": "Public Holiday" },
    workingDays: 3, // visible on the table; engine still excludes the holiday from blocking
    approvalStatus: "Approved",
    planningImpact: "Blocked",
    affectedActivityIds: ["ACT-410", "ACT-411"],
  },
  {
    leaveId: "LV-1004",
    staffId: "STF-IB-004",
    staffName: "Imran Bashir",
    region: "East",
    leaveType: "Personal Leave",
    startDate: "2025-08-04",
    endDate: "2025-08-05",
    selectedDates: ["2025-08-04", "2025-08-05"],
    validLeaveDates: ["2025-08-04", "2025-08-05"],
    excludedDates: [],
    excludedReasonByDate: {},
    workingDays: 2,
    approvalStatus: "Pending",
    planningImpact: "Potential",
    affectedActivityIds: [],
  },
];

// ────────── Date helpers ──────────

export function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function isSunday(d: Date): boolean {
  return d.getDay() === 0;
}

export function isInRange(target: string, start: string, end: string): boolean {
  return target >= start && target <= end;
}

export function dateRange(startISO: string, endISO: string): string[] {
  const out: string[] = [];
  const s = new Date(startISO + "T00:00:00");
  const e = new Date(endISO + "T00:00:00");
  for (let d = new Date(s); d <= e; d.setDate(d.getDate() + 1)) {
    out.push(isoDate(d));
  }
  return out;
}

// ────────── Planning Engine — single source of truth ──────────

export type AvailabilityReason = BlockedDateType | "Capacity Overload";
export type Severity = "Low" | "Medium" | "High" | "Critical";

export type Availability = {
  available: boolean;
  reason?: AvailabilityReason;
  severity?: Severity;
  message?: string;
  nextAvailableDate?: string;
  nextAvailableWeek?: string;
};

export function getPlanningAvailability(args: {
  date: Date | string;
  staffId?: string;
  activityType?: ActivityType;
  region?: string;
  country?: "Uganda";
  /** Backend-sourced approved-leave ISO dates for the relevant staffer.
   *  Passed in by surfaces that have live leave (the planning calendar);
   *  blocks the day the same way seeded approved leave does. */
  extraLeaveDates?: string[];
}): Availability {
  const d = typeof args.date === "string" ? new Date(args.date + "T00:00:00") : args.date;
  const iso = isoDate(d);

  // 1. Sunday — always blocked.
  if (isSunday(d)) {
    return {
      available: false,
      reason: "Sunday",
      severity: "High",
      message: "Sundays are blocked for planning.",
      nextAvailableDate: nextNonBlockedDate(d, args.staffId),
    };
  }

  // 2. Public holiday.
  const holiday = publicHolidays.find((h) => h.date === iso);
  if (holiday) {
    return {
      available: false,
      reason: "Public Holiday",
      severity: "High",
      message: `${holiday.title} — public holiday.`,
      nextAvailableDate: nextNonBlockedDate(d, args.staffId),
    };
  }

  // 3. Conference week.
  const conf = conferenceWeeks.find(
    (c) => c.blocksPlanning && isInRange(iso, c.startDate, c.endDate),
  );
  if (conf) {
    return {
      available: false,
      reason: "Conference Week",
      severity: "Critical",
      message: `${conf.title} — org-wide conference block.`,
      nextAvailableWeek: nextWeekAfter(conf.endDate),
    };
  }

  // 4. Org blackout.
  const black = blackoutDates.find(
    (b) => b.blocksPlanning && isInRange(iso, b.startDate, b.endDate),
  );
  if (black) {
    return {
      available: false,
      reason: "Blackout",
      severity: "High",
      message: `${black.title} — organizational blackout.`,
      nextAvailableDate: nextNonBlockedDate(d, args.staffId),
    };
  }

  // 5a. Backend-sourced approved leave (live) — blocks the planner's own day.
  if (args.extraLeaveDates && args.extraLeaveDates.includes(iso)) {
    return {
      available: false,
      reason: "Leave",
      severity: "Medium",
      message: "Approved leave.",
      nextAvailableDate: nextNonBlockedDate(d, args.staffId),
    };
  }

  // 5b. Seeded staff leave (only blocks for the matching staff).
  if (args.staffId) {
    const onLeave = leaveRequests.find(
      (l) =>
        l.staffId === args.staffId &&
        l.approvalStatus === "Approved" &&
        l.validLeaveDates.includes(iso),
    );
    if (onLeave) {
      return {
        available: false,
        reason: "Leave",
        severity: "Medium",
        message: `${onLeave.leaveType} (${onLeave.staffName}).`,
        nextAvailableDate: nextNonBlockedDate(d, args.staffId),
      };
    }
  }

  // Saturday and weekdays remain available unless caught above.
  return { available: true };
}

function nextNonBlockedDate(from: Date, staffId?: string): string {
  const d = new Date(from);
  for (let i = 1; i < 30; i++) {
    d.setDate(d.getDate() + 1);
    if (getPlanningAvailability({ date: d, staffId }).available) return isoDate(d);
  }
  return isoDate(d);
}

function nextWeekAfter(endISO: string): string {
  const d = new Date(endISO + "T00:00:00");
  d.setDate(d.getDate() + 1);
  while (isSunday(d)) d.setDate(d.getDate() + 1);
  const monday = new Date(d);
  while (monday.getDay() !== 1) monday.setDate(monday.getDate() + 1);
  const friday = new Date(monday);
  friday.setDate(friday.getDate() + 4);
  return `Week of ${isoDate(monday)} → ${isoDate(friday)}`;
}

// ────────── KPI row ──────────

export type LeaveKpi = {
  key: string;
  label: string;
  value: string;
  unit: string;
  caption: string;
  icon: "user" | "calendarDays" | "calendarHeart" | "lock" | "rotate" | "users";
  iconTone: "edify" | "amber" | "rose" | "slate" | "emerald" | "violet";
};

export const leaveKpis: LeaveKpi[] = [
  { key: "on_leave",        label: "Staff on Leave This Month", value: "18", unit: "staff",      caption: "12% of active staff",        icon: "user",          iconTone: "edify"   },
  { key: "approved_days",   label: "Approved Leave Days",       value: "46", unit: "days",       caption: "This Month",                 icon: "calendarDays",  iconTone: "amber"   },
  { key: "public_holidays", label: "Public Holidays",           value: "3",  unit: "days",       caption: "This Month",                 icon: "calendarHeart", iconTone: "rose"    },
  { key: "blocked_days",    label: "Blocked Planning Days",     value: "19", unit: "days",       caption: "This Month",                 icon: "lock",          iconTone: "slate"   },
  { key: "auto_resched",    label: "Activities Auto-Rescheduled", value: "27", unit: "activities", caption: "This Month",                 icon: "rotate",        iconTone: "emerald" },
  { key: "conference",      label: "Staff Conference Week",     value: "1",  unit: "week",       caption: "Jul 21 – Jul 25",            icon: "users",         iconTone: "violet"  },
];

// ────────── Automatic planning rules ──────────

export type PlanningRule = {
  key: string;
  label: string;
  enabled: boolean;
  locked: boolean; // critical rules cannot be disabled by normal staff
  icon: "calendarDays" | "calendarHeart" | "users" | "lock" | "sparkles" | "flag";
  tone: "edify" | "rose" | "violet" | "slate" | "emerald" | "amber";
};

export const planningRules: PlanningRule[] = [
  { key: "block_leave",     label: "Block all approved leave dates from planning", enabled: true, locked: true,  icon: "calendarDays",  tone: "edify"   },
  { key: "block_holidays",  label: "Block public holidays automatically",          enabled: true, locked: true,  icon: "calendarHeart", tone: "rose"    },
  { key: "block_conf",      label: "Block staff conference week",                   enabled: true, locked: true,  icon: "users",         tone: "violet"  },
  { key: "prevent_save",    label: "Prevent saving plans on blocked days",          enabled: true, locked: true,  icon: "lock",          tone: "slate"   },
  { key: "suggest_next",    label: "Auto-suggest next available week",              enabled: true, locked: false, icon: "sparkles",      tone: "emerald" },
  { key: "flag_conflicts",  label: "Flag conflicts instantly during planning",      enabled: true, locked: false, icon: "flag",          tone: "amber"   },
];

// ────────── Auto-blocked conflicts ──────────

export type ConflictAction = "View" | "Reassign" | "Auto-reschedule";

export type AutoBlockedConflict = {
  id: string;
  icon: "alertTriangle" | "calendarX" | "rotate" | "users";
  title: string;
  detail: string;
  action: ConflictAction;
  severity: Severity;
};

export const autoBlockedConflicts: AutoBlockedConflict[] = [
  {
    id: "cf-1",
    icon: "alertTriangle",
    title: "3 planned visits conflict with Sarah's leave",
    detail: "Jul 14 – Jul 16, 2025",
    action: "View",
    severity: "High",
  },
  {
    id: "cf-2",
    icon: "calendarX",
    title: "Cluster training on Independence Day blocked",
    detail: "Jul 4, 2025",
    action: "Reassign",
    severity: "Critical",
  },
  {
    id: "cf-3",
    icon: "rotate",
    title: "2 partner visits moved to next available week",
    detail: "Original: Jul 21 – Jul 25, 2025",
    action: "Auto-reschedule",
    severity: "Medium",
  },
  {
    id: "cf-4",
    icon: "users",
    title: "1 activity overlaps Staff Conference Week",
    detail: "Jul 21 – Jul 25, 2025",
    action: "View",
    severity: "High",
  },
];

// ────────── Team availability heatmap ──────────

export type AvailabilityCell = "Available" | "On Leave" | "Conference Week" | "High Load" | "Blocked";

export type TeamAvailabilityRow = {
  staffId: string;
  staffName: string;
  cells: AvailabilityCell[]; // length matches teamAvailabilityWeeks
};

export const teamAvailabilityWeeks = [
  "Jul 7-13",
  "Jul 14-20",
  "Jul 21-27",
  "Jul 28-Aug 3",
  "Aug 4-10",
];

export const teamAvailability: TeamAvailabilityRow[] = [
  { staffId: "STF-SK-001", staffName: "Sarah Khan",   cells: ["Available", "On Leave",       "Conference Week", "Available",  "Available"] },
  { staffId: "STF-AR-002", staffName: "Ali Raza",     cells: ["Available", "On Leave",       "Conference Week", "Available",  "Available"] },
  { staffId: "STF-FN-003", staffName: "Fatima Noor",  cells: ["Available", "Blocked",        "Conference Week", "On Leave",   "Available"] },
  { staffId: "STF-IB-004", staffName: "Imran Bashir", cells: ["Available", "Available",      "Conference Week", "On Leave",   "Available"] },
  { staffId: "STF-MA-005", staffName: "Maria Ahmed",  cells: ["Available", "Available",      "Conference Week", "Available",  "Available"] },
  { staffId: "STF-UT-006", staffName: "Usman Tariq",  cells: ["Available", "High Load",      "Conference Week", "Available",  "Available"] },
  { staffId: "STF-ZA-007", staffName: "Zainab Ali",   cells: ["Available", "Available",      "Conference Week", "Available",  "Available"] },
  { staffId: "STF-BH-008", staffName: "Bilal Hassan", cells: ["Available", "Available",      "Blocked",         "Available",  "Available"] },
];

// ────────── Identity / header ──────────

export const leaveHeader = {
  title: "Leave & Holiday Planning Dashboard",
  subtitle:
    "Planning is automatically blocked on leave days, holidays, and blackout days.",
};

export const leaveHeaderUser = {
  name: "Aisha Dar",
  initials: "AD",
  role: "Program Manager",
};

export const leaveNotificationCount = 3;

// ────────── Cross-dashboard rollups ──────────
//
// Lightweight summaries the CCEO and Country Program Lead dashboards can
// embed without re-implementing the engine. Each returns counts derived
// from the seeded leave + holiday + conference data above.

export function leaveSummaryForCceo(staffId: string) {
  const my = leaveRequests.filter((l) => l.staffId === staffId);
  const upcoming = my.filter((l) => l.startDate >= "2025-07-01");
  const blockedActivities = my.reduce((a, l) => a + l.affectedActivityIds.length, 0);
  return {
    upcomingCount: upcoming.length,
    blockedActivityCount: blockedActivities,
    nextLeaveStart: upcoming[0]?.startDate,
  };
}

export function leaveSummaryForCpl() {
  const onLeaveThisMonth = new Set(leaveRequests
    .filter((l) => l.startDate.startsWith("2025-07"))
    .map((l) => l.staffId)).size;
  const conflictsInQueue = autoBlockedConflicts.length;
  const blockedDays = 19;
  const conferenceWeek = "Jul 21 – Jul 25";
  return { onLeaveThisMonth, conflictsInQueue, blockedDays, conferenceWeek };
}

// ────────── Role helpers ──────────

export function canEditPlanningRule(role: AppRole, rule: PlanningRule): boolean {
  if (rule.locked) return role === "Admin";
  return role === "Admin" || role === "CountryDirector" || role === "CountryProgramLead";
}
