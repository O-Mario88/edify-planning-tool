// SSA Refresh + Training Follow-Up engines.
//
// CONTRACT:
//   • SSA Refresh — every school must have a current SSA for the active FY.
//     If latest SSA date is on or before September 30 of the previous FY,
//     the school is moved into "Schools Needing SSA" and a staff todo is
//     created. FY runs October → September.
//
//   • Training Follow-Up — if a school's latest training is ≥ 30 days old
//     and no follow-up activity has happened since, an alert is created
//     with escalating urgency at 30 / 45 / 60 days. Alert closes only on
//     scheduled follow-up, completed follow-up with Salesforce ID, or a
//     supervisor dismissal with documented reason.
//
// Both engines are role-aware (see filterFor*) so CCEOs see only their
// assigned schools, Program Leads see supervised CCEOs, Country Directors
// see the country, and RVPs see country/region rollups.

import type { CurrentUser } from "./schools-mock";

// ────────── Shared "today" anchor ──────────
//
// Single function so refreshing the demo to a different month only changes
// one place. The screenshots reference May/Jun/Jul 2025 and the Sept-30
// rule rolls into Oct 1, so we anchor today at 2025-11-15 to demonstrate
// the SSA-needed list cleanly while keeping recent training dates valid.

export const ENGINE_TODAY = new Date("2025-11-15T00:00:00");

export function fyForDate(d: Date = ENGINE_TODAY): {
  start: string;
  end: string;
  label: string;
} {
  const y = d.getFullYear();
  const startYear = d.getMonth() >= 9 ? y : y - 1; // Oct = month index 9
  const start = `${startYear}-10-01`;
  const end = `${startYear + 1}-09-30`;
  return {
    start,
    end,
    label: `FY ${startYear}/${String((startYear + 1) % 100).padStart(2, "0")}`,
  };
}

export function previousFyEnd(d: Date = ENGINE_TODAY): string {
  return fyForDate(d).start.replace("-10-01", "-09-30").replace(
    String(fyForDate(d).start.slice(0, 4)),
    String(Number(fyForDate(d).start.slice(0, 4))),
  ).replace(/^(\d{4})/, (m) => String(Number(m) - 1) + "-09-30").slice(0, 10);
}

// Cleaner: previous FY ends at Sept 30 of the start year of the current FY.
// e.g. current FY starts 2025-10-01 → previous FY ended 2025-09-30.
export function previousFyEndIso(d: Date = ENGINE_TODAY): string {
  const startYear = Number(fyForDate(d).start.slice(0, 4));
  return `${startYear}-09-30`;
}

function daysBetween(a: string, b: Date): number {
  const start = new Date(a + "T00:00:00").getTime();
  const end = b.getTime();
  return Math.floor((end - start) / 86_400_000);
}

// ────────── SSA Refresh ──────────

export type SsaRefreshStatus =
  | "SSA Current"
  | "SSA Needed"
  | "SSA Scheduled"
  | "SSA Completed"
  | "SSA Verified"
  | "SSA Overdue";

export type SchoolForSsaRefresh = {
  schoolId: string;
  schoolName: string;
  district: string;
  region: string;
  assignedCceoId: string;
  assignedCceoName: string;
  latestSsaDate?: string; // ISO; undefined = never assessed
  ssaScheduledDate?: string;
};

// 12 demo rows mixing CCEOs, regions, and SSA freshness so each role's
// "Schools Needing SSA" view has something to show.
export const ssaRefreshSchools: SchoolForSsaRefresh[] = [
  { schoolId: "SR-001", schoolName: "Sunrise Primary School", district: "Central",  region: "North Region",   assignedCceoId: "STF-DM-014", assignedCceoName: "Daniel Mwangi",  latestSsaDate: "2025-03-12" },
  { schoolId: "SR-002", schoolName: "Greenfield Secondary",   district: "Central",  region: "North Region",   assignedCceoId: "STF-DM-014", assignedCceoName: "Daniel Mwangi",  latestSsaDate: "2024-11-08" },
  { schoolId: "SR-003", schoolName: "Riverside Primary",      district: "Cluster",  region: "North Region",   assignedCceoId: "STF-DM-014", assignedCceoName: "Daniel Mwangi",  latestSsaDate: "2025-09-30" },
  { schoolId: "SR-004", schoolName: "Hilltop Basic",          district: "Cluster",  region: "North Region",   assignedCceoId: "STF-DM-014", assignedCceoName: "Daniel Mwangi",  latestSsaDate: "2025-10-15" },
  { schoolId: "SR-005", schoolName: "Eastview Junior",        district: "East",     region: "North Region",   assignedCceoId: "STF-DM-014", assignedCceoName: "Daniel Mwangi",  ssaScheduledDate: "2025-12-08" },
  { schoolId: "SR-006", schoolName: "Maple Grove Primary",    district: "Central",  region: "North Region",   assignedCceoId: "STF-DM-014", assignedCceoName: "Daniel Mwangi",  latestSsaDate: "2025-11-02" },
  { schoolId: "SR-007", schoolName: "Kitgum Hill PS",         district: "East",     region: "North Region",   assignedCceoId: "STF-GN-007", assignedCceoName: "Grace Nansubuga", latestSsaDate: "2025-08-22" },
  { schoolId: "SR-008", schoolName: "Pader West PS",          district: "West",     region: "North Region",   assignedCceoId: "STF-GN-007", assignedCceoName: "Grace Nansubuga", latestSsaDate: "2024-09-14" },
  { schoolId: "SR-009", schoolName: "Lamwo Bright PS",        district: "Cluster",  region: "Central Region", assignedCceoId: "STF-PO-008", assignedCceoName: "Peter Ochieng",  latestSsaDate: "2025-07-19" },
  { schoolId: "SR-010", schoolName: "Agago Junior",           district: "Cluster",  region: "Central Region", assignedCceoId: "STF-PO-008", assignedCceoName: "Peter Ochieng",  latestSsaDate: "2025-10-30" },
  { schoolId: "SR-011", schoolName: "Gulu Cluster PS",        district: "Cluster",  region: "Eastern Region", assignedCceoId: "STF-SN-009", assignedCceoName: "Sarah Namutebi", latestSsaDate: "2024-06-04" },
  { schoolId: "SR-012", schoolName: "Omoro Bright PS",        district: "West",     region: "Eastern Region", assignedCceoId: "STF-SN-009", assignedCceoName: "Sarah Namutebi", latestSsaDate: "2025-04-11" },
];

// Single source of truth for the refresh decision. Anything ≤ Sept 30 of the
// previous FY needs a fresh SSA for the new FY. If the school has scheduled
// the SSA, surface that as "SSA Scheduled" instead of plain "SSA Needed".
export function evaluateSsaRefresh(
  s: SchoolForSsaRefresh,
  today: Date = ENGINE_TODAY,
): SsaRefreshStatus {
  const cutoff = previousFyEndIso(today); // YYYY-09-30 of previous FY
  if (s.ssaScheduledDate) {
    if (s.latestSsaDate && s.latestSsaDate > cutoff) return "SSA Current";
    return "SSA Scheduled";
  }
  if (!s.latestSsaDate) return "SSA Needed";
  if (s.latestSsaDate <= cutoff) {
    // Older than 60 days past Sept 30 → escalate.
    const overdueDays = daysBetween(cutoff, today);
    return overdueDays > 60 ? "SSA Overdue" : "SSA Needed";
  }
  return "SSA Current";
}

export function detectSchoolsNeedingAnnualSsa(
  schools: SchoolForSsaRefresh[] = ssaRefreshSchools,
  today: Date = ENGINE_TODAY,
): (SchoolForSsaRefresh & { ssaRefreshStatus: SsaRefreshStatus })[] {
  return schools
    .map((s) => ({ ...s, ssaRefreshStatus: evaluateSsaRefresh(s, today) }))
    .filter((s) =>
      s.ssaRefreshStatus === "SSA Needed" ||
      s.ssaRefreshStatus === "SSA Scheduled" ||
      s.ssaRefreshStatus === "SSA Overdue"
    );
}

export function filterSsaRefreshForUser(
  schools: SchoolForSsaRefresh[],
  user: CurrentUser,
): SchoolForSsaRefresh[] {
  if (user.role === "Admin") return schools;
  if (user.role === "CountryDirector") return schools; // demo: all in country
  if (user.role === "CountryProgramLead") return schools; // demo: supervises all
  if (user.role === "ImpactAssessment" || user.role === "ProgramAccountant") return schools;
  return schools.filter((s) => s.assignedCceoId === user.staffId);
}

export type SsaRefreshSummary = {
  needed: number;
  scheduled: number;
  overdue: number;
  current: number;
  total: number;
};

export function ssaRefreshSummaryFor(
  user: CurrentUser,
  today: Date = ENGINE_TODAY,
): SsaRefreshSummary {
  const visible = filterSsaRefreshForUser(ssaRefreshSchools, user);
  const tagged = visible.map((s) => ({ ...s, ssaRefreshStatus: evaluateSsaRefresh(s, today) }));
  return {
    needed:    tagged.filter((s) => s.ssaRefreshStatus === "SSA Needed").length,
    scheduled: tagged.filter((s) => s.ssaRefreshStatus === "SSA Scheduled").length,
    overdue:   tagged.filter((s) => s.ssaRefreshStatus === "SSA Overdue").length,
    current:   tagged.filter((s) => s.ssaRefreshStatus === "SSA Current").length,
    total:     tagged.length,
  };
}

// ────────── Training Follow-Up ──────────

export type FollowUpStatus =
  | "Follow-Up Due"
  | "Follow-Up Overdue"
  | "Critical Follow-Up Gap"
  | "Resolved";

export type FollowUpAlert = {
  alertId: string;
  schoolId: string;
  schoolName: string;
  district: string;
  region: string;
  assignedCceoId: string;
  assignedCceoName: string;
  latestTrainingDate: string;
  daysSinceTraining: number;
  noFollowUpAfterTraining: boolean;
  followUpStatus: FollowUpStatus;
  urgency: "Medium" | "High" | "Critical";
  recommendedAction: string;
  visibleToRoles: ("CCEO" | "CountryProgramLead" | "CountryDirector" | "Admin")[];
};

export type RawTrainingRecord = {
  schoolId: string;
  schoolName: string;
  district: string;
  region: string;
  assignedCceoId: string;
  assignedCceoName: string;
  latestTrainingDate: string;
  hasFollowUpAfter: boolean;
  resolved?: boolean;
};

export const trainingRecordsRaw: RawTrainingRecord[] = [
  { schoolId: "TF-001", schoolName: "Bright Future P/S",   district: "Lamwo",   region: "North Region",   assignedCceoId: "STF-DM-014", assignedCceoName: "Daniel Mwangi",  latestTrainingDate: "2025-10-08", hasFollowUpAfter: false },
  { schoolId: "TF-002", schoolName: "Hope Academy P/S",    district: "Agago",   region: "North Region",   assignedCceoId: "STF-DM-014", assignedCceoName: "Daniel Mwangi",  latestTrainingDate: "2025-09-22", hasFollowUpAfter: false },
  { schoolId: "TF-003", schoolName: "Unity Primary",        district: "Omoro",   region: "Central Region", assignedCceoId: "STF-GN-007", assignedCceoName: "Grace Nansubuga", latestTrainingDate: "2025-09-05", hasFollowUpAfter: false },
  { schoolId: "TF-004", schoolName: "St. Peter's P/S",      district: "Agago",   region: "North Region",   assignedCceoId: "STF-PO-008", assignedCceoName: "Peter Ochieng",  latestTrainingDate: "2025-08-26", hasFollowUpAfter: false },
  { schoolId: "TF-005", schoolName: "Light of Grace P/S",   district: "Lamwo",   region: "North Region",   assignedCceoId: "STF-PO-008", assignedCceoName: "Peter Ochieng",  latestTrainingDate: "2025-08-12", hasFollowUpAfter: false },
  { schoolId: "TF-006", schoolName: "Northstar Primary",    district: "Cluster", region: "Eastern Region", assignedCceoId: "STF-SN-009", assignedCceoName: "Sarah Namutebi", latestTrainingDate: "2025-10-25", hasFollowUpAfter: true },
  { schoolId: "TF-007", schoolName: "Riverside Children's", district: "East",    region: "North Region",   assignedCceoId: "STF-DM-014", assignedCceoName: "Daniel Mwangi",  latestTrainingDate: "2025-09-30", hasFollowUpAfter: false },
];

export function urgencyForDays(days: number): {
  status: FollowUpStatus;
  urgency: "Medium" | "High" | "Critical";
} {
  if (days >= 60) return { status: "Critical Follow-Up Gap", urgency: "Critical" };
  if (days >= 45) return { status: "Follow-Up Overdue", urgency: "High" };
  return { status: "Follow-Up Due", urgency: "Medium" };
}

export function detectTrainingFollowUpGaps(
  records: RawTrainingRecord[] = trainingRecordsRaw,
  today: Date = ENGINE_TODAY,
): FollowUpAlert[] {
  return records
    .filter((r) => !r.resolved && !r.hasFollowUpAfter)
    .map((r) => {
      const days = daysBetween(r.latestTrainingDate, today);
      if (days < 30) return null;
      const { status, urgency } = urgencyForDays(days);
      return {
        alertId: `FU-${r.schoolId}`,
        schoolId: r.schoolId,
        schoolName: r.schoolName,
        district: r.district,
        region: r.region,
        assignedCceoId: r.assignedCceoId,
        assignedCceoName: r.assignedCceoName,
        latestTrainingDate: r.latestTrainingDate,
        daysSinceTraining: days,
        noFollowUpAfterTraining: true,
        followUpStatus: status,
        urgency,
        recommendedAction:
          urgency === "Critical"
            ? "Schedule follow-up this week + escalate to Program Lead"
            : urgency === "High"
              ? "Schedule follow-up within 7 days"
              : "Add follow-up visit to weekly plan",
        visibleToRoles: ["CCEO", "CountryProgramLead", "CountryDirector", "Admin"],
      } as FollowUpAlert;
    })
    .filter((a): a is FollowUpAlert => a !== null)
    .sort((a, b) => b.daysSinceTraining - a.daysSinceTraining);
}

export function followUpAlertsFor(user: CurrentUser): FollowUpAlert[] {
  const all = detectTrainingFollowUpGaps();
  if (user.role === "Admin" || user.role === "CountryDirector" || user.role === "CountryProgramLead") {
    return all;
  }
  return all.filter((a) => a.assignedCceoId === user.staffId);
}

export function followUpSummaryFor(user: CurrentUser): {
  total: number;
  due: number;
  overdue: number;
  critical: number;
} {
  const alerts = followUpAlertsFor(user);
  return {
    total: alerts.length,
    due: alerts.filter((a) => a.followUpStatus === "Follow-Up Due").length,
    overdue: alerts.filter((a) => a.followUpStatus === "Follow-Up Overdue").length,
    critical: alerts.filter((a) => a.followUpStatus === "Critical Follow-Up Gap").length,
  };
}

// Closing rule: cannot close without one of the three valid resolutions.
export function canCloseFollowUp(reason: {
  scheduledFollowUp?: boolean;
  completedWithSalesforceId?: string;
  supervisorDismissalWithReason?: string;
}): boolean {
  if (reason.scheduledFollowUp) return true;
  if (reason.completedWithSalesforceId && reason.completedWithSalesforceId.trim().length > 0) return true;
  if (reason.supervisorDismissalWithReason && reason.supervisorDismissalWithReason.trim().length > 5) return true;
  return false;
}
