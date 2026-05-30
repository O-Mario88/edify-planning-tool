// Weekly Fund Pipeline — Mock Data
//
// Realistic snapshot for May 2026, Uganda country office. The data
// covers the whole pipeline so the Accountant, Lead, and Staff views
// all show meaningful queues:
//
//   • 6 CCEOs split across 3 districts
//   • 4 weekly requests per CCEO  (24 total)
//   • Weeks 1–2 are CLOSED; week 3 is the active operating week.
//   • Some week-3 requests are pending approval, some disbursed,
//     some pending accountability.
//   • Week 4 is AUTO_GENERATED — Lead hasn't reviewed yet.
//
// Two FundsReceivedRecords (RVP wire + HQ top-up) feed disbursements.

import type {
  CountryMonthlyBudget,
  DisbursementRecord,
  FundsReceivedRecord,
  Money,
  RequesterRole,
  StaffFundBalance,
  WeeklyFundAuditEvent,
  WeeklyFundNotification,
  WeeklyFundRequest,
  WeeklyFundRequestActivity,
  WeeklyFundRequestStatus,
} from "./weekly-fund-types";

const UGX = (amount: number): Money => ({ amount, currency: "UGX" });

// ────────── Funds received at country level ───────────────────────────

export const fundsReceived: FundsReceivedRecord[] = [
  {
    id: "FR-2026-05-001",
    countryId: "UG",
    receivedOnIso: "2026-05-04",
    fromSource: "RVP_OFFICE",
    reference: "WIRE/RVP/20260504/0091",
    totalReceived: UGX(420_000_000),
    totalAllocated: UGX(284_500_000),
    availableBalance: UGX(135_500_000),
    monthLabel: "May 2026",
    notes: "RVP monthly tranche — Uganda",
    confirmedByAccountantId: "STF-MT-031",
    confirmedAt: "2026-05-04T09:14:00Z",
  },
  {
    id: "FR-2026-05-002",
    countryId: "UG",
    receivedOnIso: "2026-05-12",
    fromSource: "HQ_TREASURY",
    reference: "WIRE/HQ/20260512/4421",
    totalReceived: UGX(90_000_000),
    totalAllocated: UGX(0),
    availableBalance: UGX(90_000_000),
    monthLabel: "May 2026",
    notes: "Top-up for Cluster training surge",
    confirmedByAccountantId: "STF-MT-031",
    confirmedAt: "2026-05-12T10:02:00Z",
  },
];

export const totalReceivedThisMonth = UGX(510_000_000);
export const totalDisbursedThisMonth = UGX(284_500_000);
export const totalAccountedThisMonth = UGX(196_300_000);
export const totalOutstanding = UGX(88_200_000);
export const totalAvailableBalance = UGX(225_500_000);

// ────────── Staff roster (Uganda — Daniel Mwangi's team) ──────────────

type Roster = {
  staffId: string;
  staffName: string;
  initials: string;
  district: string;
  programLeadId: string;
  programLeadName: string;
};

export const roster: Roster[] = [
  { staffId: "STF-PC-001", staffName: "Paul Chinyama",  initials: "PC", district: "Kampala",  programLeadId: "STF-DM-014", programLeadName: "Daniel Mwangi" },
  { staffId: "STF-IM-004", staffName: "Irene Mutebi",   initials: "IM", district: "Kampala",  programLeadId: "STF-DM-014", programLeadName: "Daniel Mwangi" },
  { staffId: "STF-JN-007", staffName: "Joseph Nsubuga", initials: "JN", district: "Wakiso",   programLeadId: "STF-DM-014", programLeadName: "Daniel Mwangi" },
  { staffId: "STF-RK-011", staffName: "Ruth Kabuye",    initials: "RK", district: "Wakiso",   programLeadId: "STF-DM-014", programLeadName: "Daniel Mwangi" },
  { staffId: "STF-SO-018", staffName: "Simon Otim",     initials: "SO", district: "Mukono",   programLeadId: "STF-DM-014", programLeadName: "Daniel Mwangi" },
  { staffId: "STF-AN-022", staffName: "Aisha Namatovu", initials: "AN", district: "Mukono",   programLeadId: "STF-DM-014", programLeadName: "Daniel Mwangi" },
];

// ────────── Activity templates ────────────────────────────────────────

let actCounter = 0;
function activity(
  kind: WeeklyFundRequestActivity["kind"],
  title: string,
  school: string,
  district: string,
  day: string,
  transport: number,
  allowance: number,
  meals: number,
  materials: number,
  misc = 0,
): WeeklyFundRequestActivity {
  actCounter += 1;
  const total = transport + allowance + meals + materials + misc;
  return {
    id: `ACT-${actCounter}`,
    originPlanLineId: `PL-${actCounter}`,
    kind,
    title,
    schoolName: school,
    district,
    plannedDay: day,
    costBreakdown: {
      transport: UGX(transport),
      allowance: UGX(allowance),
      meals: UGX(meals),
      materials: UGX(materials),
      misc: UGX(misc),
    },
    totalCost: UGX(total),
    status: "Confirmed",
  };
}

// ────────── Helper to build a request ─────────────────────────────────

function buildRequest(
  r: Roster,
  weekOfMonth: 1 | 2 | 3 | 4,
  weekStart: string,
  weekEnd: string,
  status: WeeklyFundRequestStatus,
  activities: WeeklyFundRequestActivity[],
  extras?: Partial<WeeklyFundRequest>,
): WeeklyFundRequest {
  const plannedTotal = activities.reduce(
    (a, x) => a + x.totalCost.amount,
    0,
  );
  return {
    id: `WFR-2026-05-W${weekOfMonth}-${r.staffId}`,
    staffId: r.staffId,
    staffName: r.staffName,
    staffRole: "CCEO",
    requesterRole: "CCEO",
    approverRole: "ProgramLead",
    district: r.district,
    programLeadId: r.programLeadId,
    programLeadName: r.programLeadName,
    countryId: "UG",
    monthlyPlanId: `MP-2026-05-${r.staffId}`,
    weeklyPlanId: `WP-2026-05-W${weekOfMonth}-${r.staffId}`,
    period: {
      fyLabel: "FY 2026",
      quarter: "Q3",
      monthLabel: "May 2026",
      monthIso: "2026-05",
      weekOfMonth,
      weekStartIso: weekStart,
      weekEndIso: weekEnd,
    },
    status,
    plannedAmount: UGX(plannedTotal),
    requestedAmount: UGX(plannedTotal),
    activities,
    adjustments: [],
    flags: [],
    notes: "",
    source: "AUTO_FROM_PLAN",
    ...extras,
  };
}

// ────────── 24 weekly requests, 6 staff × 4 weeks ─────────────────────

const W1 = { start: "2026-05-04", end: "2026-05-08" };
const W2 = { start: "2026-05-11", end: "2026-05-15" };
const W3 = { start: "2026-05-18", end: "2026-05-22" };
const W4 = { start: "2026-05-25", end: "2026-05-29" };

const PAUL = roster[0];
const IRENE = roster[1];
const JOSEPH = roster[2];
const RUTH = roster[3];
const SIMON = roster[4];
const AISHA = roster[5];

export const weeklyFundRequests: WeeklyFundRequest[] = [
  // ───── Paul Chinyama — Kampala ─────
  buildRequest(PAUL, 1, W1.start, W1.end, "CLOSED", [
    activity("SchoolVisit", "St. Mary's Naguru — Q3 visit", "St. Mary's Naguru", "Kampala", "Mon 04", 25_000, 60_000, 30_000, 18_000),
    activity("SchoolVisit", "Bright Future Kamwokya", "Bright Future Kamwokya", "Kampala", "Tue 05", 22_000, 60_000, 30_000, 12_000),
    activity("FollowUp",    "Refresh — Hilltop Bukoto", "Hilltop Bukoto", "Kampala", "Wed 06", 18_000, 30_000, 18_000, 8_000),
    activity("Cluster",     "Q3 cluster meeting Kampala North", "Cluster Hub Naguru", "Kampala", "Fri 08", 20_000, 50_000, 75_000, 60_000),
  ], {
    disbursedAmount: UGX(536_000),
    accountedAmount: UGX(528_500),
    returnedAmount: UGX(7_500),
  }),
  buildRequest(PAUL, 2, W2.start, W2.end, "CLOSED", [
    activity("SchoolVisit", "Sunrise Kabalagala", "Sunrise Kabalagala", "Kampala", "Mon 11", 25_000, 60_000, 30_000, 18_000),
    activity("TeacherTraining", "P5 Math methodology — Kampala East", "Cluster Hub Kabalagala", "Kampala", "Wed 13", 30_000, 90_000, 90_000, 140_000),
    activity("SchoolVisit", "Greenfield Muyenga", "Greenfield Muyenga", "Kampala", "Thu 14", 22_000, 60_000, 30_000, 18_000),
  ], {
    disbursedAmount: UGX(613_000),
    accountedAmount: UGX(606_000),
    returnedAmount: UGX(7_000),
  }),
  buildRequest(PAUL, 3, W3.start, W3.end, "IN_USE", [
    activity("SchoolVisit", "St. Mary's Naguru — follow-up audit", "St. Mary's Naguru", "Kampala", "Mon 18", 25_000, 60_000, 30_000, 18_000),
    activity("Cluster",     "Q3 cluster Kampala Central", "Cluster Hub Kololo", "Kampala", "Wed 20", 24_000, 60_000, 75_000, 65_000),
    activity("FollowUp",    "Refresh — Bright Future Kamwokya", "Bright Future Kamwokya", "Kampala", "Thu 21", 18_000, 30_000, 18_000, 6_000),
    activity("SchoolVisit", "Hilltop Bukoto — quality check", "Hilltop Bukoto", "Kampala", "Fri 22", 22_000, 60_000, 30_000, 18_000),
  ], {
    disbursedAmount: UGX(559_000),
    disbursedAt: "2026-05-18T08:42:00Z",
    disbursedByAccountantId: "STF-MT-031",
    approvedAt: "2026-05-17T15:11:00Z",
    approvedByLeadId: "STF-DM-014",
    receivedAt: "2026-05-18T11:02:00Z",
  }),
  buildRequest(PAUL, 4, W4.start, W4.end, "AUTO_GENERATED", [
    activity("SchoolVisit", "Sunrise Kabalagala — Q3 close-out", "Sunrise Kabalagala", "Kampala", "Mon 25", 25_000, 60_000, 30_000, 18_000),
    activity("StakeholderMeeting", "Parent council — Kampala East", "Cluster Hub Kabalagala", "Kampala", "Thu 28", 20_000, 50_000, 95_000, 35_000),
    activity("SchoolVisit", "Greenfield Muyenga — Q3 close-out", "Greenfield Muyenga", "Kampala", "Fri 29", 22_000, 60_000, 30_000, 18_000),
  ]),

  // ───── Irene Mutebi — Kampala ─────
  buildRequest(IRENE, 1, W1.start, W1.end, "CLOSED", [
    activity("SchoolVisit", "Excel Academy Ntinda", "Excel Academy Ntinda", "Kampala", "Mon 04", 24_000, 60_000, 30_000, 18_000),
    activity("Cluster",     "Q3 cluster Kampala East", "Cluster Hub Ntinda", "Kampala", "Wed 06", 22_000, 60_000, 75_000, 60_000),
    activity("SchoolVisit", "Royal Hill Bugolobi", "Royal Hill Bugolobi", "Kampala", "Thu 07", 22_000, 60_000, 30_000, 18_000),
  ], {
    disbursedAmount: UGX(479_000),
    accountedAmount: UGX(471_500),
    returnedAmount: UGX(7_500),
  }),
  buildRequest(IRENE, 2, W2.start, W2.end, "CLOSED", [
    activity("TeacherTraining", "ECDE methodology refresher", "Cluster Hub Ntinda", "Kampala", "Tue 12", 30_000, 90_000, 90_000, 140_000),
    activity("SchoolVisit", "Excel Academy Ntinda", "Excel Academy Ntinda", "Kampala", "Wed 13", 22_000, 60_000, 30_000, 18_000),
    activity("FollowUp",    "Refresh — Royal Hill Bugolobi", "Royal Hill Bugolobi", "Kampala", "Fri 15", 18_000, 30_000, 18_000, 6_000),
  ], {
    disbursedAmount: UGX(552_000),
    accountedAmount: UGX(540_000),
    returnedAmount: UGX(12_000),
  }),
  buildRequest(IRENE, 3, W3.start, W3.end, "ACCOUNTABILITY_SUBMITTED", [
    activity("SchoolVisit", "Excel Academy Ntinda — quality check", "Excel Academy Ntinda", "Kampala", "Mon 18", 24_000, 60_000, 30_000, 18_000),
    activity("SchoolVisit", "Royal Hill Bugolobi — quality check", "Royal Hill Bugolobi", "Kampala", "Tue 19", 22_000, 60_000, 30_000, 18_000),
    activity("Cluster",     "Q3 cluster Kampala East — close-out", "Cluster Hub Ntinda", "Kampala", "Thu 21", 22_000, 60_000, 75_000, 60_000),
  ], {
    disbursedAmount: UGX(479_000),
    accountedAmount: UGX(472_000),
    returnedAmount: UGX(7_000),
    disbursedAt: "2026-05-18T08:50:00Z",
    accountabilitySubmittedAt: "2026-05-22T16:10:00Z",
    approvedAt: "2026-05-17T14:55:00Z",
    approvedByLeadId: "STF-DM-014",
    disbursedByAccountantId: "STF-MT-031",
  }),
  buildRequest(IRENE, 4, W4.start, W4.end, "AUTO_GENERATED", [
    activity("SchoolVisit", "Excel Academy Ntinda — Q3 close-out", "Excel Academy Ntinda", "Kampala", "Mon 25", 24_000, 60_000, 30_000, 18_000),
    activity("StakeholderMeeting", "Parent council — Kampala North", "Cluster Hub Ntinda", "Kampala", "Wed 27", 20_000, 50_000, 95_000, 35_000),
  ]),

  // ───── Joseph Nsubuga — Wakiso ─────
  buildRequest(JOSEPH, 1, W1.start, W1.end, "CLOSED", [
    activity("SchoolVisit", "Kasangati Junior", "Kasangati Junior", "Wakiso", "Mon 04", 30_000, 60_000, 30_000, 18_000),
    activity("Cluster",     "Q3 cluster Wakiso North", "Cluster Hub Kasangati", "Wakiso", "Wed 06", 28_000, 60_000, 75_000, 60_000),
    activity("SchoolVisit", "Nansana Hope", "Nansana Hope", "Wakiso", "Thu 07", 25_000, 60_000, 30_000, 18_000),
    activity("SchoolVisit", "Wakiso Central", "Wakiso Central", "Wakiso", "Fri 08", 25_000, 60_000, 30_000, 18_000),
  ], {
    disbursedAmount: UGX(607_000),
    accountedAmount: UGX(601_000),
    returnedAmount: UGX(6_000),
  }),
  buildRequest(JOSEPH, 2, W2.start, W2.end, "CLOSED", [
    activity("TeacherTraining", "Literacy methodology — Wakiso", "Cluster Hub Kasangati", "Wakiso", "Wed 13", 35_000, 90_000, 90_000, 140_000),
    activity("FollowUp",    "Refresh — Nansana Hope", "Nansana Hope", "Wakiso", "Thu 14", 22_000, 30_000, 18_000, 6_000),
  ], {
    disbursedAmount: UGX(431_000),
    accountedAmount: UGX(420_000),
    returnedAmount: UGX(11_000),
  }),
  buildRequest(JOSEPH, 3, W3.start, W3.end, "DISBURSED", [
    activity("SchoolVisit", "Kasangati Junior — quality check", "Kasangati Junior", "Wakiso", "Mon 18", 30_000, 60_000, 30_000, 18_000),
    activity("SchoolVisit", "Wakiso Central — quality check", "Wakiso Central", "Wakiso", "Tue 19", 25_000, 60_000, 30_000, 18_000),
    activity("Cluster",     "Q3 cluster Wakiso North — close-out", "Cluster Hub Kasangati", "Wakiso", "Thu 21", 28_000, 60_000, 75_000, 60_000),
    activity("SchoolVisit", "Nansana Hope — quality check", "Nansana Hope", "Wakiso", "Fri 22", 25_000, 60_000, 30_000, 18_000),
  ], {
    disbursedAmount: UGX(607_000),
    disbursedAt: "2026-05-18T09:14:00Z",
    disbursedByAccountantId: "STF-MT-031",
    approvedAt: "2026-05-17T16:02:00Z",
    approvedByLeadId: "STF-DM-014",
  }),
  buildRequest(JOSEPH, 4, W4.start, W4.end, "AUTO_GENERATED", [
    activity("SchoolVisit", "Kasangati Junior — Q3 close-out", "Kasangati Junior", "Wakiso", "Mon 25", 30_000, 60_000, 30_000, 18_000),
    activity("StakeholderMeeting", "Head-teacher council — Wakiso", "Cluster Hub Kasangati", "Wakiso", "Wed 27", 28_000, 50_000, 95_000, 35_000),
    activity("SchoolVisit", "Nansana Hope — close-out", "Nansana Hope", "Wakiso", "Fri 29", 25_000, 60_000, 30_000, 18_000),
  ]),

  // ───── Ruth Kabuye — Wakiso ─────
  buildRequest(RUTH, 1, W1.start, W1.end, "CLOSED", [
    activity("SchoolVisit", "Entebbe Hill", "Entebbe Hill", "Wakiso", "Mon 04", 28_000, 60_000, 30_000, 18_000),
    activity("SchoolVisit", "Bweyogerere New Hope", "Bweyogerere New Hope", "Wakiso", "Tue 05", 25_000, 60_000, 30_000, 18_000),
    activity("Cluster",     "Q3 cluster Wakiso South", "Cluster Hub Entebbe", "Wakiso", "Thu 07", 28_000, 60_000, 75_000, 60_000),
  ], {
    disbursedAmount: UGX(492_000),
    accountedAmount: UGX(485_000),
    returnedAmount: UGX(7_000),
  }),
  buildRequest(RUTH, 2, W2.start, W2.end, "CLOSED", [
    activity("SchoolVisit", "Entebbe Hill — quality check", "Entebbe Hill", "Wakiso", "Mon 11", 28_000, 60_000, 30_000, 18_000),
    activity("TeacherTraining", "Numeracy methodology", "Cluster Hub Entebbe", "Wakiso", "Wed 13", 35_000, 90_000, 90_000, 140_000),
    activity("FollowUp",    "Refresh — Bweyogerere New Hope", "Bweyogerere New Hope", "Wakiso", "Fri 15", 22_000, 30_000, 18_000, 6_000),
  ], {
    disbursedAmount: UGX(567_000),
    accountedAmount: UGX(555_000),
    returnedAmount: UGX(12_000),
  }),
  buildRequest(RUTH, 3, W3.start, W3.end, "SUBMITTED", [
    activity("SchoolVisit", "Entebbe Hill — quality check", "Entebbe Hill", "Wakiso", "Mon 18", 28_000, 60_000, 30_000, 18_000),
    activity("SchoolVisit", "Bweyogerere New Hope — quality check", "Bweyogerere New Hope", "Wakiso", "Tue 19", 25_000, 60_000, 30_000, 18_000),
    activity("Cluster",     "Q3 cluster Wakiso South — close-out", "Cluster Hub Entebbe", "Wakiso", "Thu 21", 28_000, 60_000, 75_000, 60_000),
  ], {
    submittedAt: "2026-05-16T18:21:00Z",
  }),
  buildRequest(RUTH, 4, W4.start, W4.end, "AUTO_GENERATED", [
    activity("SchoolVisit", "Entebbe Hill — Q3 close-out", "Entebbe Hill", "Wakiso", "Mon 25", 28_000, 60_000, 30_000, 18_000),
    activity("SchoolVisit", "Bweyogerere New Hope — Q3 close-out", "Bweyogerere New Hope", "Wakiso", "Tue 26", 25_000, 60_000, 30_000, 18_000),
  ]),

  // ───── Simon Otim — Mukono ─────
  buildRequest(SIMON, 1, W1.start, W1.end, "CLOSED", [
    activity("SchoolVisit", "Mukono Mercy", "Mukono Mercy", "Mukono", "Mon 04", 30_000, 60_000, 30_000, 18_000),
    activity("SchoolVisit", "Seeta Hill", "Seeta Hill", "Mukono", "Tue 05", 28_000, 60_000, 30_000, 18_000),
    activity("FollowUp",    "Refresh — Lugazi Faith", "Lugazi Faith", "Mukono", "Thu 07", 25_000, 30_000, 18_000, 6_000),
    activity("Cluster",     "Q3 cluster Mukono Central", "Cluster Hub Mukono", "Mukono", "Fri 08", 28_000, 60_000, 75_000, 60_000),
  ], {
    disbursedAmount: UGX(586_000),
    accountedAmount: UGX(582_000),
    returnedAmount: UGX(4_000),
  }),
  buildRequest(SIMON, 2, W2.start, W2.end, "ACCOUNTABILITY_RETURNED", [
    activity("SchoolVisit", "Mukono Mercy — Q3 visit", "Mukono Mercy", "Mukono", "Mon 11", 30_000, 60_000, 30_000, 18_000),
    activity("TeacherTraining", "School leadership refresher", "Cluster Hub Mukono", "Mukono", "Wed 13", 35_000, 90_000, 90_000, 140_000),
    activity("SchoolVisit", "Seeta Hill — Q3 visit", "Seeta Hill", "Mukono", "Fri 15", 28_000, 60_000, 30_000, 18_000),
  ], {
    disbursedAmount: UGX(629_000),
    accountedAmount: UGX(602_000),
    returnedAmount: UGX(27_000),
    disbursedAt: "2026-05-11T08:46:00Z",
    accountabilitySubmittedAt: "2026-05-15T17:30:00Z",
    flags: ["MISSING_RECEIPTS"],
  }),
  buildRequest(SIMON, 3, W3.start, W3.end, "APPROVED", [
    activity("SchoolVisit", "Mukono Mercy — quality check", "Mukono Mercy", "Mukono", "Mon 18", 30_000, 60_000, 30_000, 18_000),
    activity("SchoolVisit", "Seeta Hill — quality check", "Seeta Hill", "Mukono", "Tue 19", 28_000, 60_000, 30_000, 18_000),
    activity("Cluster",     "Q3 cluster Mukono Central — close-out", "Cluster Hub Mukono", "Mukono", "Thu 21", 28_000, 60_000, 75_000, 60_000),
    activity("SchoolVisit", "Lugazi Faith — quality check", "Lugazi Faith", "Mukono", "Fri 22", 25_000, 60_000, 30_000, 18_000),
  ], {
    submittedAt: "2026-05-16T19:02:00Z",
    approvedAt: "2026-05-17T15:42:00Z",
    approvedByLeadId: "STF-DM-014",
    flags: ["PRIOR_WEEK_NOT_CLOSED"],
  }),
  buildRequest(SIMON, 4, W4.start, W4.end, "AUTO_GENERATED", [
    activity("SchoolVisit", "Mukono Mercy — Q3 close-out", "Mukono Mercy", "Mukono", "Mon 25", 30_000, 60_000, 30_000, 18_000),
    activity("StakeholderMeeting", "Parent council — Mukono", "Cluster Hub Mukono", "Mukono", "Thu 28", 28_000, 50_000, 95_000, 35_000),
  ]),

  // ───── Aisha Namatovu — Mukono ─────
  buildRequest(AISHA, 1, W1.start, W1.end, "CLOSED", [
    activity("SchoolVisit", "Jinja Road Academy", "Jinja Road Academy", "Mukono", "Mon 04", 30_000, 60_000, 30_000, 18_000),
    activity("Cluster",     "Q3 cluster Mukono East", "Cluster Hub Lugazi", "Mukono", "Wed 06", 28_000, 60_000, 75_000, 60_000),
    activity("FollowUp",    "Refresh — Highland Mukono", "Highland Mukono", "Mukono", "Fri 08", 22_000, 30_000, 18_000, 6_000),
  ], {
    disbursedAmount: UGX(465_000),
    accountedAmount: UGX(459_000),
    returnedAmount: UGX(6_000),
  }),
  buildRequest(AISHA, 2, W2.start, W2.end, "CLOSED", [
    activity("SchoolVisit", "Jinja Road Academy — quality check", "Jinja Road Academy", "Mukono", "Tue 12", 30_000, 60_000, 30_000, 18_000),
    activity("TeacherTraining", "Methodology — Mukono East", "Cluster Hub Lugazi", "Mukono", "Thu 14", 35_000, 90_000, 90_000, 140_000),
  ], {
    disbursedAmount: UGX(493_000),
    accountedAmount: UGX(484_000),
    returnedAmount: UGX(9_000),
  }),
  buildRequest(AISHA, 3, W3.start, W3.end, "RETURNED_TO_STAFF", [
    activity("SchoolVisit", "Jinja Road Academy — quality check", "Jinja Road Academy", "Mukono", "Mon 18", 30_000, 60_000, 30_000, 18_000),
    activity("StakeholderMeeting", "District council briefing", "Mukono DEO Office", "Mukono", "Wed 20", 28_000, 50_000, 95_000, 65_000),
    activity("SchoolVisit", "Highland Mukono — quality check", "Highland Mukono", "Mukono", "Fri 22", 22_000, 60_000, 30_000, 18_000),
  ], {
    submittedAt: "2026-05-16T15:20:00Z",
    notes: "Lead returned: district council line items missing approval letter — please attach.",
  }),
  buildRequest(AISHA, 4, W4.start, W4.end, "AUTO_GENERATED", [
    activity("SchoolVisit", "Jinja Road Academy — Q3 close-out", "Jinja Road Academy", "Mukono", "Mon 25", 30_000, 60_000, 30_000, 18_000),
    activity("SchoolVisit", "Highland Mukono — Q3 close-out", "Highland Mukono", "Mukono", "Tue 26", 22_000, 60_000, 30_000, 18_000),
  ]),
];

// ────────── Disbursement records (the money trail) ────────────────────

export const disbursementRecords: DisbursementRecord[] = [
  // Week 1 closes (all 6 staff)
  { id: "DSB-2026-05-W1-101", weeklyFundRequestId: "WFR-2026-05-W1-STF-PC-001", fundsReceivedId: "FR-2026-05-001", staffId: "STF-PC-001", staffName: "Paul Chinyama",  amount: UGX(536_000), method: "MobileMoney", reference: "MPSA-ABCD-104", disbursedAt: "2026-05-04T08:45:00Z", disbursedByAccountantId: "STF-MT-031", disbursedByAccountantName: "Moses Tindi", receiptConfirmedByStaffAt: "2026-05-04T10:11:00Z", reversed: false },
  { id: "DSB-2026-05-W1-102", weeklyFundRequestId: "WFR-2026-05-W1-STF-IM-004", fundsReceivedId: "FR-2026-05-001", staffId: "STF-IM-004", staffName: "Irene Mutebi",   amount: UGX(479_000), method: "MobileMoney", reference: "MPSA-ABDE-105", disbursedAt: "2026-05-04T08:50:00Z", disbursedByAccountantId: "STF-MT-031", disbursedByAccountantName: "Moses Tindi", receiptConfirmedByStaffAt: "2026-05-04T10:21:00Z", reversed: false },
  { id: "DSB-2026-05-W1-103", weeklyFundRequestId: "WFR-2026-05-W1-STF-JN-007", fundsReceivedId: "FR-2026-05-001", staffId: "STF-JN-007", staffName: "Joseph Nsubuga", amount: UGX(607_000), method: "BankTransfer", reference: "BNK-202605-0091", disbursedAt: "2026-05-04T09:01:00Z", disbursedByAccountantId: "STF-MT-031", disbursedByAccountantName: "Moses Tindi", receiptConfirmedByStaffAt: "2026-05-04T11:05:00Z", reversed: false },
  { id: "DSB-2026-05-W1-104", weeklyFundRequestId: "WFR-2026-05-W1-STF-RK-011", fundsReceivedId: "FR-2026-05-001", staffId: "STF-RK-011", staffName: "Ruth Kabuye",    amount: UGX(492_000), method: "MobileMoney", reference: "MPSA-RKBY-201", disbursedAt: "2026-05-04T09:10:00Z", disbursedByAccountantId: "STF-MT-031", disbursedByAccountantName: "Moses Tindi", receiptConfirmedByStaffAt: "2026-05-04T11:21:00Z", reversed: false },
  { id: "DSB-2026-05-W1-105", weeklyFundRequestId: "WFR-2026-05-W1-STF-SO-018", fundsReceivedId: "FR-2026-05-001", staffId: "STF-SO-018", staffName: "Simon Otim",     amount: UGX(586_000), method: "MobileMoney", reference: "MPSA-OTIM-211", disbursedAt: "2026-05-04T09:18:00Z", disbursedByAccountantId: "STF-MT-031", disbursedByAccountantName: "Moses Tindi", receiptConfirmedByStaffAt: "2026-05-04T11:40:00Z", reversed: false },
  { id: "DSB-2026-05-W1-106", weeklyFundRequestId: "WFR-2026-05-W1-STF-AN-022", fundsReceivedId: "FR-2026-05-001", staffId: "STF-AN-022", staffName: "Aisha Namatovu", amount: UGX(465_000), method: "MobileMoney", reference: "MPSA-NAMA-221", disbursedAt: "2026-05-04T09:25:00Z", disbursedByAccountantId: "STF-MT-031", disbursedByAccountantName: "Moses Tindi", receiptConfirmedByStaffAt: "2026-05-04T11:55:00Z", reversed: false },
  // Week 2
  { id: "DSB-2026-05-W2-201", weeklyFundRequestId: "WFR-2026-05-W2-STF-PC-001", fundsReceivedId: "FR-2026-05-001", staffId: "STF-PC-001", staffName: "Paul Chinyama",  amount: UGX(613_000), method: "MobileMoney", reference: "MPSA-CHNY-301", disbursedAt: "2026-05-11T08:31:00Z", disbursedByAccountantId: "STF-MT-031", disbursedByAccountantName: "Moses Tindi", receiptConfirmedByStaffAt: "2026-05-11T10:02:00Z", reversed: false },
  { id: "DSB-2026-05-W2-202", weeklyFundRequestId: "WFR-2026-05-W2-STF-IM-004", fundsReceivedId: "FR-2026-05-001", staffId: "STF-IM-004", staffName: "Irene Mutebi",   amount: UGX(552_000), method: "MobileMoney", reference: "MPSA-MUTE-302", disbursedAt: "2026-05-11T08:36:00Z", disbursedByAccountantId: "STF-MT-031", disbursedByAccountantName: "Moses Tindi", receiptConfirmedByStaffAt: "2026-05-11T10:14:00Z", reversed: false },
  { id: "DSB-2026-05-W2-203", weeklyFundRequestId: "WFR-2026-05-W2-STF-JN-007", fundsReceivedId: "FR-2026-05-001", staffId: "STF-JN-007", staffName: "Joseph Nsubuga", amount: UGX(431_000), method: "BankTransfer", reference: "BNK-202605-0142", disbursedAt: "2026-05-11T08:46:00Z", disbursedByAccountantId: "STF-MT-031", disbursedByAccountantName: "Moses Tindi", receiptConfirmedByStaffAt: "2026-05-11T10:25:00Z", reversed: false },
  { id: "DSB-2026-05-W2-204", weeklyFundRequestId: "WFR-2026-05-W2-STF-RK-011", fundsReceivedId: "FR-2026-05-001", staffId: "STF-RK-011", staffName: "Ruth Kabuye",    amount: UGX(567_000), method: "MobileMoney", reference: "MPSA-KBYE-303", disbursedAt: "2026-05-11T08:52:00Z", disbursedByAccountantId: "STF-MT-031", disbursedByAccountantName: "Moses Tindi", receiptConfirmedByStaffAt: "2026-05-11T10:42:00Z", reversed: false },
  { id: "DSB-2026-05-W2-205", weeklyFundRequestId: "WFR-2026-05-W2-STF-SO-018", fundsReceivedId: "FR-2026-05-001", staffId: "STF-SO-018", staffName: "Simon Otim",     amount: UGX(629_000), method: "MobileMoney", reference: "MPSA-OTIM-304", disbursedAt: "2026-05-11T08:58:00Z", disbursedByAccountantId: "STF-MT-031", disbursedByAccountantName: "Moses Tindi", receiptConfirmedByStaffAt: "2026-05-11T11:05:00Z", reversed: false },
  { id: "DSB-2026-05-W2-206", weeklyFundRequestId: "WFR-2026-05-W2-STF-AN-022", fundsReceivedId: "FR-2026-05-001", staffId: "STF-AN-022", staffName: "Aisha Namatovu", amount: UGX(493_000), method: "MobileMoney", reference: "MPSA-NAMA-305", disbursedAt: "2026-05-11T09:02:00Z", disbursedByAccountantId: "STF-MT-031", disbursedByAccountantName: "Moses Tindi", receiptConfirmedByStaffAt: "2026-05-11T11:18:00Z", reversed: false },
  // Week 3 (in flight)
  { id: "DSB-2026-05-W3-301", weeklyFundRequestId: "WFR-2026-05-W3-STF-PC-001", fundsReceivedId: "FR-2026-05-001", staffId: "STF-PC-001", staffName: "Paul Chinyama",  amount: UGX(559_000), method: "MobileMoney", reference: "MPSA-CHNY-401", disbursedAt: "2026-05-18T08:42:00Z", disbursedByAccountantId: "STF-MT-031", disbursedByAccountantName: "Moses Tindi", receiptConfirmedByStaffAt: "2026-05-18T11:02:00Z", reversed: false },
  { id: "DSB-2026-05-W3-302", weeklyFundRequestId: "WFR-2026-05-W3-STF-IM-004", fundsReceivedId: "FR-2026-05-001", staffId: "STF-IM-004", staffName: "Irene Mutebi",   amount: UGX(479_000), method: "MobileMoney", reference: "MPSA-MUTE-402", disbursedAt: "2026-05-18T08:50:00Z", disbursedByAccountantId: "STF-MT-031", disbursedByAccountantName: "Moses Tindi", receiptConfirmedByStaffAt: "2026-05-18T11:14:00Z", reversed: false },
  { id: "DSB-2026-05-W3-303", weeklyFundRequestId: "WFR-2026-05-W3-STF-JN-007", fundsReceivedId: "FR-2026-05-001", staffId: "STF-JN-007", staffName: "Joseph Nsubuga", amount: UGX(607_000), method: "BankTransfer", reference: "BNK-202605-0203", disbursedAt: "2026-05-18T09:14:00Z", disbursedByAccountantId: "STF-MT-031", disbursedByAccountantName: "Moses Tindi", reversed: false },
];

// ────────── Staff balance roll-ups ────────────────────────────────────

export const staffBalances: StaffFundBalance[] = [
  { staffId: "STF-PC-001", staffName: "Paul Chinyama",  district: "Kampala", openDisbursed: UGX(559_000), openAccounted: UGX(0),       outstanding: UGX(559_000), weeksOutstanding: 1, oldestWeekIso: "2026-05-18", flagged: false },
  { staffId: "STF-IM-004", staffName: "Irene Mutebi",   district: "Kampala", openDisbursed: UGX(479_000), openAccounted: UGX(472_000), outstanding: UGX(7_000),   weeksOutstanding: 1, oldestWeekIso: "2026-05-18", flagged: false },
  { staffId: "STF-JN-007", staffName: "Joseph Nsubuga", district: "Wakiso",  openDisbursed: UGX(607_000), openAccounted: UGX(0),       outstanding: UGX(607_000), weeksOutstanding: 1, oldestWeekIso: "2026-05-18", flagged: false },
  { staffId: "STF-RK-011", staffName: "Ruth Kabuye",    district: "Wakiso",  openDisbursed: UGX(0),       openAccounted: UGX(0),       outstanding: UGX(0),       weeksOutstanding: 0, flagged: false },
  { staffId: "STF-SO-018", staffName: "Simon Otim",     district: "Mukono",  openDisbursed: UGX(629_000), openAccounted: UGX(602_000), outstanding: UGX(27_000),  weeksOutstanding: 2, oldestWeekIso: "2026-05-11", flagged: true },
  { staffId: "STF-AN-022", staffName: "Aisha Namatovu", district: "Mukono",  openDisbursed: UGX(0),       openAccounted: UGX(0),       outstanding: UGX(0),       weeksOutstanding: 0, flagged: false },
];

// ────────── Audit + notifications (recent slice) ──────────────────────

export const recentAuditEvents: WeeklyFundAuditEvent[] = [
  { id: "AUD-1001", weeklyFundRequestId: "WFR-2026-05-W3-STF-PC-001", action: "DISBURSED",                fromStatus: "READY_TO_DISBURSE", toStatus: "DISBURSED",    actorId: "STF-MT-031", actorName: "Moses Tindi",  actorRole: "Accountant",  at: "2026-05-18T08:42:00Z", note: "MobileMoney MPSA-CHNY-401", delta: UGX(559_000) },
  { id: "AUD-1002", weeklyFundRequestId: "WFR-2026-05-W3-STF-IM-004", action: "ACCOUNTABILITY_SUBMITTED", fromStatus: "IN_USE",            toStatus: "ACCOUNTABILITY_SUBMITTED", actorId: "STF-IM-004", actorName: "Irene Mutebi", actorRole: "Staff",       at: "2026-05-22T16:10:00Z", note: "4 receipts attached" },
  { id: "AUD-1003", weeklyFundRequestId: "WFR-2026-05-W3-STF-RK-011", action: "SUBMITTED",               fromStatus: "AUTO_GENERATED",    toStatus: "SUBMITTED",    actorId: "STF-RK-011", actorName: "Ruth Kabuye",  actorRole: "Staff",       at: "2026-05-16T18:21:00Z", note: "Week 3 confirmed" },
  { id: "AUD-1004", weeklyFundRequestId: "WFR-2026-05-W3-STF-AN-022", action: "RETURNED",                fromStatus: "SUBMITTED",         toStatus: "RETURNED_TO_STAFF", actorId: "STF-DM-014", actorName: "Daniel Mwangi", actorRole: "ProgramLead", at: "2026-05-17T11:42:00Z", note: "District council letter missing" },
  { id: "AUD-1005", weeklyFundRequestId: "WFR-2026-05-W3-STF-SO-018", action: "APPROVED",                fromStatus: "SUBMITTED",         toStatus: "APPROVED",     actorId: "STF-DM-014", actorName: "Daniel Mwangi", actorRole: "ProgramLead", at: "2026-05-17T15:42:00Z", note: "Approved with prior-week flag" },
  { id: "AUD-1006", weeklyFundRequestId: "WFR-2026-05-W3-STF-JN-007", action: "DISBURSED",                fromStatus: "READY_TO_DISBURSE", toStatus: "DISBURSED",    actorId: "STF-MT-031", actorName: "Moses Tindi",  actorRole: "Accountant",  at: "2026-05-18T09:14:00Z", note: "Bank transfer BNK-202605-0203", delta: UGX(607_000) },
  { id: "AUD-1007", weeklyFundRequestId: "WFR-2026-05-W2-STF-SO-018", action: "BLOCKER_RAISED",          fromStatus: "ACCOUNTABILITY_SUBMITTED", toStatus: "ACCOUNTABILITY_RETURNED", actorId: "STF-DM-014", actorName: "Daniel Mwangi", actorRole: "ProgramLead", at: "2026-05-16T10:18:00Z", note: "2 receipts missing photos" },
];

export const recentNotifications: WeeklyFundNotification[] = [
  { id: "NTF-2001", weeklyFundRequestId: "WFR-2026-05-W3-STF-PC-001", audienceRole: "Staff",       audienceUserId: "STF-PC-001", channel: "Inbox", template: "REQUEST_DISBURSED",       sentAt: "2026-05-18T08:42:00Z" },
  { id: "NTF-2002", weeklyFundRequestId: "WFR-2026-05-W3-STF-IM-004", audienceRole: "ProgramLead", audienceUserId: "STF-DM-014", channel: "Inbox", template: "ACCOUNTABILITY_DUE",       sentAt: "2026-05-22T16:10:00Z" },
  { id: "NTF-2003", weeklyFundRequestId: "WFR-2026-05-W3-STF-RK-011", audienceRole: "ProgramLead", audienceUserId: "STF-DM-014", channel: "Inbox", template: "REQUEST_AUTO_GENERATED",   sentAt: "2026-05-16T18:21:00Z" },
  { id: "NTF-2004", weeklyFundRequestId: "WFR-2026-05-W3-STF-AN-022", audienceRole: "Staff",       audienceUserId: "STF-AN-022", channel: "Inbox", template: "REQUEST_RETURNED",         sentAt: "2026-05-17T11:42:00Z" },
];

// ────────── Convenience selectors used by the dashboards ──────────────

export function findWeeklyRequest(id: string): WeeklyFundRequest | undefined {
  return weeklyFundRequests.find((r) => r.id === id);
}

export function findRequestsForStaff(staffId: string): WeeklyFundRequest[] {
  return weeklyFundRequests
    .filter((r) => r.staffId === staffId)
    .sort((a, b) => a.period.weekOfMonth - b.period.weekOfMonth);
}

export function pendingLeadQueue(programLeadId: string): WeeklyFundRequest[] {
  return weeklyFundRequests.filter(
    (r) => r.programLeadId === programLeadId && r.status === "SUBMITTED",
  );
}

export function pendingAccountabilityQueue(programLeadId: string): WeeklyFundRequest[] {
  return weeklyFundRequests.filter(
    (r) => r.programLeadId === programLeadId && r.status === "ACCOUNTABILITY_SUBMITTED",
  );
}

export function pendingDisbursementQueue(): WeeklyFundRequest[] {
  return weeklyFundRequests.filter(
    (r) =>
      r.status === "APPROVED" ||
      r.status === "READY_TO_DISBURSE" ||
      r.status === "HOLD_NO_FUNDS_AVAILABLE" ||
      r.status === "BLOCKED_PRIOR_OUTSTANDING",
  );
}

export function activeDisbursements(): DisbursementRecord[] {
  return disbursementRecords.slice().sort((a, b) => b.disbursedAt.localeCompare(a.disbursedAt));
}

// ────────── Active operating week (UI hint) ───────────────────────────

export const currentWeek = {
  fyLabel: "FY 2026",
  quarter: "Q3" as const,
  monthLabel: "May 2026",
  monthIso: "2026-05",
  weekOfMonth: 3 as const,
  weekStartIso: W3.start,
  weekEndIso: W3.end,
  daysRemaining: 4,
};

// ────────── Higher-tier requesters → Country Director queue ───────────
//
// These are the requests the spec says should NOT go to the Program
// Lead: PL supervision funds, IA verification funds, Accountant ops
// funds, Special Projects funds, Admin/operations funds. They all
// route to the Country Director.

type CdRequester = {
  staffId: string;
  staffName: string;
  initials: string;
  district: string;
  role: RequesterRole;
};

const CD_REQUESTERS: CdRequester[] = [
  { staffId: "STF-DM-014", staffName: "Daniel Mwangi",  initials: "DM", district: "Uganda · Kampala HQ",  role: "ProgramLead" },
  { staffId: "STF-AD-021", staffName: "Aisha Dar",      initials: "AD", district: "Uganda · Wakiso PL",   role: "ProgramLead" },
  { staffId: "STF-GA-042", staffName: "Grace Alimo",    initials: "GA", district: "Uganda · IA Unit",     role: "ImpactAssessment" },
  { staffId: "STF-MT-031", staffName: "Moses Tindi",    initials: "MT", district: "Uganda · Finance",    role: "ProgramAccountant" },
  { staffId: "STF-LL-088", staffName: "Lillian Akello", initials: "LA", district: "Uganda · SPCo",       role: "SpecialProjectsCoordinator" },
  { staffId: "STF-AB-099", staffName: "Andrew Banda",   initials: "AB", district: "Uganda · Admin Ops",  role: "Admin" },
];

function buildCdRequest(
  r: CdRequester,
  id: string,
  weekOfMonth: 1 | 2 | 3 | 4,
  status: WeeklyFundRequestStatus,
  title: string,
  amount: number,
  activitiesCount: number,
  extras?: Partial<WeeklyFundRequest>,
): WeeklyFundRequest {
  const weekRanges = { 1: W1, 2: W2, 3: W3, 4: W4 } as const;
  const range = weekRanges[weekOfMonth];
  const synthesizedActivity: WeeklyFundRequestActivity = {
    id: `${id}-A`,
    originPlanLineId: `${id}-PL-A`,
    kind: r.role === "ImpactAssessment" ? "FollowUp" : "StakeholderMeeting",
    title,
    schoolName: undefined,
    district: r.district,
    plannedDay: "Wed",
    costBreakdown: {
      transport:  UGX(Math.floor(amount * 0.35)),
      allowance:  UGX(Math.floor(amount * 0.25)),
      meals:      UGX(Math.floor(amount * 0.20)),
      materials:  UGX(Math.floor(amount * 0.15)),
      misc:       UGX(amount - Math.floor(amount * 0.35) - Math.floor(amount * 0.25) - Math.floor(amount * 0.20) - Math.floor(amount * 0.15)),
    },
    totalCost: UGX(amount),
    status: "Confirmed",
    note: `${activitiesCount} sub-activities`,
  };
  return {
    id,
    staffId: r.staffId,
    staffName: r.staffName,
    staffRole: "Other",
    requesterRole: r.role,
    approverRole: "CountryDirector",
    district: r.district,
    programLeadId: "STF-DM-014",
    programLeadName: "Daniel Mwangi",
    countryId: "UG",
    monthlyPlanId: `MP-2026-05-${r.staffId}`,
    weeklyPlanId: `WP-2026-05-W${weekOfMonth}-${r.staffId}`,
    period: {
      fyLabel: "FY 2026",
      quarter: "Q3",
      monthLabel: "May 2026",
      monthIso: "2026-05",
      weekOfMonth,
      weekStartIso: range.start,
      weekEndIso: range.end,
    },
    status,
    plannedAmount: UGX(amount),
    requestedAmount: UGX(amount),
    activities: [synthesizedActivity],
    adjustments: [],
    flags: [],
    notes: "",
    source: "AUTO_FROM_PLAN",
    ...extras,
  };
}

export const cdFundRequests: WeeklyFundRequest[] = [
  buildCdRequest(
    CD_REQUESTERS[0], "WFR-2026-05-W3-CD-PL-DM-014", 3, "SUBMITTED",
    "PL Week 3 team supervision · Kampala & Wakiso",
    3_400_000, 12,
    { submittedAt: "2026-05-16T18:45:00Z" },
  ),
  buildCdRequest(
    CD_REQUESTERS[1], "WFR-2026-05-W3-CD-PL-AD-021", 3, "SUBMITTED",
    "PL Week 3 field supervision · Wakiso cluster",
    2_850_000, 9,
    { submittedAt: "2026-05-16T19:30:00Z" },
  ),
  buildCdRequest(
    CD_REQUESTERS[2], "WFR-2026-05-W3-CD-IA-GA-042", 3, "APPROVED",
    "IA Week 3 verification visits · 14 schools",
    4_200_000, 14,
    {
      submittedAt: "2026-05-15T11:08:00Z",
      approvedAt: "2026-05-16T09:15:00Z",
      approvedByLeadId: "STF-SO-007",
    },
  ),
  buildCdRequest(
    CD_REQUESTERS[3], "WFR-2026-05-W3-CD-ACC-MT-031", 3, "SUBMITTED",
    "Accountant Q3 close-out · cash-pickup + bank fees",
    1_950_000, 5,
    { submittedAt: "2026-05-17T08:55:00Z" },
  ),
  buildCdRequest(
    CD_REQUESTERS[4], "WFR-2026-05-W3-CD-SP-LL-088", 3, "SUBMITTED",
    "Special Projects · Discipleship Clubs launch Wakiso",
    5_400_000, 6,
    {
      submittedAt: "2026-05-16T16:42:00Z",
      adjustments: [
        {
          activityId: "WFR-2026-05-W3-CD-SP-LL-088-A",
          type: "NewActivity",
          reason: "Added launch ceremony catering after CD review",
          costDelta: UGX(800_000),
          requiresLeadReApproval: true,
        },
      ],
    },
  ),
  buildCdRequest(
    CD_REQUESTERS[5], "WFR-2026-05-W3-CD-ADM-AB-099", 3, "APPROVED",
    "Admin Ops · Kampala office rent + utilities + ISP",
    2_300_000, 4,
    {
      submittedAt: "2026-05-15T14:00:00Z",
      approvedAt: "2026-05-16T10:42:00Z",
      approvedByLeadId: "STF-SO-007",
    },
  ),
];

// Convenience selectors for the CD queue.
export function cdQueueByRequesterType(
  status: WeeklyFundRequestStatus[] = ["SUBMITTED"],
): Record<RequesterRole, WeeklyFundRequest[]> {
  const buckets: Record<RequesterRole, WeeklyFundRequest[]> = {
    CCEO:                       [],
    ProgramLead:                [],
    ProgramAccountant:          [],
    ImpactAssessment:           [],
    SpecialProjectsCoordinator: [],
    Admin:                      [],
  };
  for (const r of cdFundRequests) {
    if (!status.includes(r.status)) continue;
    if (r.requesterRole) buckets[r.requesterRole].push(r);
  }
  return buckets;
}

export function cdApprovedAwaitingAccountant(): WeeklyFundRequest[] {
  return cdFundRequests.filter((r) => r.status === "APPROVED");
}

// ────────── Country Monthly Budget (RVP envelope) ─────────────────────

export const ugandaCountryBudget: CountryMonthlyBudget = {
  id: "CMB-UG-2026-05",
  countryId: "UG",
  countryName: "Uganda",
  flag: "🇺🇬",
  monthLabel: "May 2026",
  monthIso: "2026-05",
  fyLabel: "FY 2026",
  quarter: "Q3",
  status: "APPROVED",
  total: UGX(128_460_000),
  lines: [
    { category: "FieldWork",       label: "CCEO field work (visits + cluster)", amount: UGX(91_200_000), note: "6 CCEOs × 4 weeks" },
    { category: "AdminOps",        label: "Admin / operations",                 amount: UGX(18_400_000), note: "Rent, utilities, ISP, fees" },
    { category: "SpecialProjects", label: "Special projects",                   amount: UGX(12_800_000), note: "Discipleship Clubs launch + Partner work" },
    { category: "Contingency",     label: "Contingency",                        amount: UGX(6_060_000),  note: "Held by CD" },
  ],
  submittedByCdId:   "STF-SO-007",
  submittedByCdName: "Sarah Okello",
  submittedAt:       "2026-04-25T09:30:00Z",
  approvedByRvpId:   "STF-EW-003",
  approvedByRvpName: "Esther Wanjiru",
  approvedAt:        "2026-04-28T15:12:00Z",
};

export const pendingCountryBudgets: CountryMonthlyBudget[] = [
  {
    id: "CMB-KE-2026-06",
    countryId: "KE",
    countryName: "Kenya",
    flag: "🇰🇪",
    monthLabel: "June 2026",
    monthIso: "2026-06",
    fyLabel: "FY 2026",
    quarter: "Q3",
    status: "PENDING_RVP",
    total: UGX(112_300_000),
    lines: [
      { category: "FieldWork",       label: "CCEO field work",   amount: UGX(78_000_000) },
      { category: "AdminOps",        label: "Admin / ops",       amount: UGX(15_500_000) },
      { category: "SpecialProjects", label: "Partner programs",  amount: UGX(13_800_000) },
      { category: "Contingency",     label: "Contingency",       amount: UGX(5_000_000)  },
    ],
    submittedByCdId:   "STF-CD-KE-001",
    submittedByCdName: "Eunice Wambui",
    submittedAt:       "2026-05-12T08:22:00Z",
  },
  {
    id: "CMB-TZ-2026-06",
    countryId: "TZ",
    countryName: "Tanzania",
    flag: "🇹🇿",
    monthLabel: "June 2026",
    monthIso: "2026-06",
    fyLabel: "FY 2026",
    quarter: "Q3",
    status: "PENDING_RVP",
    total: UGX(98_700_000),
    lines: [
      { category: "FieldWork",       label: "CCEO field work",  amount: UGX(68_000_000) },
      { category: "AdminOps",        label: "Admin / ops",      amount: UGX(14_200_000) },
      { category: "Training",        label: "Teacher training", amount: UGX(11_500_000) },
      { category: "Contingency",     label: "Contingency",      amount: UGX(5_000_000)  },
    ],
    submittedByCdId:   "STF-CD-TZ-001",
    submittedByCdName: "Joachim Mwakasege",
    submittedAt:       "2026-05-13T10:08:00Z",
  },
];
