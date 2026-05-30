// Planned activities are the single source of truth the budget engine reads from.
// Each carries enough metadata for the engine to classify district type, group by
// day, and apply CD cost settings.

export type ActivityKind =
  | "staff_visit"
  | "follow_up_visit"
  | "coaching_visit"
  | "ssa_visit"
  | "core_visit"
  | "partner_visit"
  | "partner_follow_up"
  | "partner_in_school_activity"
  | "training"
  | "core_training"
  | "school_improvement_training"
  | "cluster_training"
  | "cluster_meeting"
  | "special_project";

export type ActivityStatus =
  | "Draft"
  | "Scheduled"
  | "Partner Planned"
  | "Approved Plan"
  | "Ready for Funds"
  | "Cancelled"
  | "Rejected"
  | "Returned"
  | "Unscheduled"
  | "Completed";

export type PlannedActivity = {
  id: string;
  kind: ActivityKind;
  deliveryOwner: "STAFF" | "PARTNER";
  facilitatorType?: "STAFF" | "PARTNER";
  staffId?: string;
  partnerId?: string;
  partnerName?: string;
  schoolId?: string;
  schoolName?: string;
  clusterId?: string;
  clusterName?: string;
  districtId: string;
  districtName: string;
  subCountyId?: string;
  parishId?: string;
  scheduledDateIso?: string;
  plannedMonthIso: string;
  plannedWeek: 1 | 2 | 3 | 4 | 5;
  nights?: number;
  participantCount?: number;
  schoolCount?: number;
  status: ActivityStatus;
  notes?: string;
};

export const BUDGETABLE_STATUSES: ReadonlySet<ActivityStatus> = new Set([
  "Scheduled",
  "Partner Planned",
  "Approved Plan",
  "Ready for Funds",
]);

export function isBudgetableActivity(a: PlannedActivity): boolean {
  return BUDGETABLE_STATUSES.has(a.status);
}

// ---------------------------------------------------------------------------
// Mock dataset
// ---------------------------------------------------------------------------

const MONTH = "2026-04";

// Week date pools (April 2026):
//   W1: Apr 6-10, W2: Apr 13-17, W3: Apr 20-24, W4: Apr 27-30, W5: empty
const W1 = ["2026-04-06", "2026-04-07", "2026-04-08", "2026-04-09", "2026-04-10"];
const W2 = ["2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16", "2026-04-17"];
const W3 = ["2026-04-20", "2026-04-21", "2026-04-22", "2026-04-23", "2026-04-24"];
const W4 = ["2026-04-27", "2026-04-28", "2026-04-29", "2026-04-30"];

// Staff <-> district pairing. Districts come from the allowed Ugandan set.
type StaffSeed = {
  staffId: string;
  districtId: string;
  districtName: string;
};

const STAFF: StaffSeed[] = [
  { staffId: "STF-DEMO-X", districtId: "UG-KIT", districtName: "Kitgum" },
  { staffId: "STF-PC-001", districtId: "UG-PAD", districtName: "Pader" },
  { staffId: "STF-MO-002", districtId: "UG-LAM", districtName: "Lamwo" },
  { staffId: "STF-JN-003", districtId: "UG-AGA", districtName: "Agago" },
  { staffId: "STF-AK-004", districtId: "UG-GUL", districtName: "Gulu" },
  { staffId: "STF-DM-005", districtId: "UG-LIR", districtName: "Lira" },
  { staffId: "STF-DA-011", districtId: "UG-ARU", districtName: "Arua" },
  { staffId: "STF-AH-012", districtId: "UG-NEB", districtName: "Nebbi" },
  { staffId: "STF-NL-013", districtId: "UG-KAM", districtName: "Kampala" },
  { staffId: "STF-SS-015", districtId: "UG-WAK", districtName: "Wakiso" },
  { staffId: "STF-KK-016", districtId: "UG-MUK", districtName: "Mukono" },
  { staffId: "STF-MR-017", districtId: "UG-MBA", districtName: "Mbale" },
  { staffId: "STF-RN-018", districtId: "UG-TOR", districtName: "Tororo" },
  { staffId: "STF-AN-021", districtId: "UG-SOR", districtName: "Soroti" },
  { staffId: "STF-RB-022", districtId: "UG-JIN", districtName: "Jinja" },
  { staffId: "STF-LO-023", districtId: "UG-IGA", districtName: "Iganga" },
  { staffId: "STF-CT-031", districtId: "UG-MBR", districtName: "Mbarara" },
  { staffId: "STF-SX-032", districtId: "UG-BUS", districtName: "Bushenyi" },
];

// Two extra districts (Kabarole, Hoima) used by partner activities below to
// exercise the allowed-district set even where no staff lives.
const PARTNER_DISTRICTS = [
  { districtId: "UG-KAB", districtName: "Kabarole" },
  { districtId: "UG-HOI", districtName: "Hoima" },
];

function weekOf(dateIso: string): 1 | 2 | 3 | 4 | 5 {
  if (W1.includes(dateIso)) return 1;
  if (W2.includes(dateIso)) return 2;
  if (W3.includes(dateIso)) return 3;
  if (W4.includes(dateIso)) return 4;
  return 5;
}

// Deterministic, dense school namer: keeps tests reproducible.
function schoolFor(districtName: string, n: number): { id: string; name: string } {
  return {
    id: `SCH-${districtName.slice(0, 3).toUpperCase()}-${String(n).padStart(3, "0")}`,
    name: `${districtName} Primary ${n}`,
  };
}

type Builder = (a: Partial<PlannedActivity>) => PlannedActivity;

let _seq = 0;
function nextId(prefix: string): string {
  _seq += 1;
  return `${prefix}-${String(_seq).padStart(4, "0")}`;
}

function staffVisit(
  s: StaffSeed,
  dateIso: string,
  schoolN: number,
  overrides: Partial<PlannedActivity> = {},
): PlannedActivity {
  const sc = schoolFor(s.districtName, schoolN);
  return {
    id: nextId("PA"),
    kind: "staff_visit",
    deliveryOwner: "STAFF",
    facilitatorType: "STAFF",
    staffId: s.staffId,
    schoolId: sc.id,
    schoolName: sc.name,
    districtId: s.districtId,
    districtName: s.districtName,
    scheduledDateIso: dateIso,
    plannedMonthIso: MONTH,
    plannedWeek: weekOf(dateIso),
    nights: 0,
    status: "Scheduled",
    ...overrides,
  };
}

const ALL: PlannedActivity[] = [];

// ---- Per-staff allocations -------------------------------------------------
// Each staff gets 6 activities by default. Some staff get an extra activity to
// host special cases (multi-school days, missing participantCount, etc.).

for (let i = 0; i < STAFF.length; i += 1) {
  const s = STAFF[i];

  // Week 1: two staff_visits on different days
  ALL.push(staffVisit(s, W1[i % W1.length], 1));
  ALL.push(staffVisit(s, W1[(i + 2) % W1.length], 2, { kind: "follow_up_visit" }));

  // Week 2: coaching or ssa visit
  ALL.push(
    staffVisit(s, W2[i % W2.length], 3, {
      kind: i % 2 === 0 ? "coaching_visit" : "ssa_visit",
    }),
  );

  // Week 3: cluster meeting + training mix
  const clusterDate = W3[i % W3.length];
  ALL.push({
    id: nextId("PA"),
    kind: "cluster_meeting",
    deliveryOwner: "STAFF",
    facilitatorType: "STAFF",
    staffId: s.staffId,
    clusterId: `CL-${s.districtName.slice(0, 3).toUpperCase()}-01`,
    clusterName: `${s.districtName} Cluster A`,
    districtId: s.districtId,
    districtName: s.districtName,
    scheduledDateIso: clusterDate,
    plannedMonthIso: MONTH,
    plannedWeek: 3,
    nights: 0,
    participantCount: 20 + (i % 6),
    schoolCount: 4 + (i % 3),
    status: "Approved Plan",
  });

  // Week 3 training (every other staff hosts one; the rest get a W4 core_visit).
  // Either branch keeps each staff at exactly 5 base activities.
  if (i % 2 === 0) {
    ALL.push({
      id: nextId("PA"),
      kind: i % 3 === 0 ? "cluster_training" : "training",
      deliveryOwner: "STAFF",
      facilitatorType: "STAFF",
      staffId: s.staffId,
      districtId: s.districtId,
      districtName: s.districtName,
      scheduledDateIso: W3[(i + 1) % W3.length],
      plannedMonthIso: MONTH,
      plannedWeek: 3,
      nights: i % 4 === 0 ? 1 : 0,
      participantCount: 25 + (i % 8),
      schoolCount: 6 + (i % 4),
      status: "Ready for Funds",
    });
  } else {
    // Week 4: core_visit so every staff still has exactly 5
    ALL.push(staffVisit(s, W4[i % W4.length], 5, { kind: "core_visit" }));
  }
}

// ---- Multi-school days -----------------------------------------------------
// Two staff each get a 3-school day (drives the daily-group logic test).
// Reuse STF-DEMO-X on W1 day Apr 7 and STF-PC-001 on W2 day Apr 14.
const MULTI: Array<{ s: StaffSeed; dateIso: string; schoolNums: number[] }> = [
  { s: STAFF[0], dateIso: "2026-04-07", schoolNums: [11, 12, 13] },
  { s: STAFF[1], dateIso: "2026-04-14", schoolNums: [21, 22, 23] },
];
for (const m of MULTI) {
  for (const n of m.schoolNums) {
    ALL.push(staffVisit(m.s, m.dateIso, n));
  }
}

// ---- Partner activities (W2 and W4) ----------------------------------------
// Partner kinds get deliveryOwner=PARTNER.
function partnerActivity(
  kind: Extract<
    ActivityKind,
    "partner_visit" | "partner_follow_up" | "partner_in_school_activity"
  >,
  dateIso: string,
  districtIdx: number,
  schoolN: number,
  overrides: Partial<PlannedActivity> = {},
): PlannedActivity {
  const d =
    districtIdx < PARTNER_DISTRICTS.length
      ? PARTNER_DISTRICTS[districtIdx]
      : { districtId: STAFF[districtIdx % STAFF.length].districtId, districtName: STAFF[districtIdx % STAFF.length].districtName };
  const sc = schoolFor(d.districtName, schoolN);
  return {
    id: nextId("PA"),
    kind,
    deliveryOwner: "PARTNER",
    facilitatorType: "PARTNER",
    partnerId: `PRT-${String((districtIdx % 5) + 1).padStart(3, "0")}`,
    partnerName: `Partner Org ${(districtIdx % 5) + 1}`,
    schoolId: sc.id,
    schoolName: sc.name,
    districtId: d.districtId,
    districtName: d.districtName,
    scheduledDateIso: dateIso,
    plannedMonthIso: MONTH,
    plannedWeek: weekOf(dateIso),
    nights: 0,
    status: "Partner Planned",
    ...overrides,
  };
}

// Week 2 partner visits
ALL.push(partnerActivity("partner_visit", "2026-04-13", 0, 31));
ALL.push(partnerActivity("partner_visit", "2026-04-15", 1, 32));
ALL.push(partnerActivity("partner_follow_up", "2026-04-16", 0, 33));
ALL.push(partnerActivity("partner_in_school_activity", "2026-04-17", 1, 34));

// Week 4 partner visits
ALL.push(partnerActivity("partner_visit", "2026-04-27", 0, 41));
ALL.push(partnerActivity("partner_follow_up", "2026-04-28", 1, 42));
ALL.push(partnerActivity("partner_in_school_activity", "2026-04-29", 0, 43));
ALL.push(partnerActivity("partner_visit", "2026-04-30", 1, 44));

// ---- Required edge cases ---------------------------------------------------

// One Cancelled activity (engine should exclude).
ALL.push(
  staffVisit(STAFF[4], "2026-04-08", 99, {
    status: "Cancelled",
    notes: "Cancelled — school closed for exams",
  }),
);

// One training with missing participantCount (engine should flag Incomplete).
ALL.push({
  id: nextId("PA"),
  kind: "training",
  deliveryOwner: "STAFF",
  facilitatorType: "STAFF",
  staffId: STAFF[7].staffId,
  districtId: STAFF[7].districtId,
  districtName: STAFF[7].districtName,
  scheduledDateIso: "2026-04-22",
  plannedMonthIso: MONTH,
  plannedWeek: 3,
  nights: 0,
  // participantCount intentionally omitted
  schoolCount: 5,
  status: "Scheduled",
  notes: "Participant count pending headcount confirmation",
});

// One partner activity in Draft (engine should exclude).
ALL.push(
  partnerActivity("partner_visit", "2026-04-13", 0, 77, {
    status: "Draft",
    notes: "Partner draft — awaiting submission",
  }),
);

export const PLANNED_ACTIVITIES: PlannedActivity[] = ALL;

// ---------------------------------------------------------------------------
// Query helper
// ---------------------------------------------------------------------------

export function getPlannedActivities(opts: {
  monthIso?: string;
  fyLabel?: string;
  countryId?: string;
  staffIds?: string[];
}): PlannedActivity[] {
  const { monthIso, staffIds } = opts;
  return PLANNED_ACTIVITIES.filter((a) => {
    if (monthIso && a.plannedMonthIso !== monthIso) return false;
    if (staffIds && staffIds.length > 0) {
      if (!a.staffId || !staffIds.includes(a.staffId)) return false;
    }
    // fyLabel and countryId are accepted for forward-compatibility; the mock
    // dataset is single-FY (FY26) and single-country (UG), so they pass-through.
    return true;
  });
}
