// Per-activity-type budget calculators. Each takes planned activities + CD cost
// settings and emits BudgetLine. Daily grouping for staff visits prevents
// double-counting meals when multiple schools are visited in one day.

import type { CostSettings } from "./cost-settings";
import type { PlannedActivity } from "./planned-activities";
import { classifyDistrict, isBudgetable, type StaffProfile } from "./staff-district";

export type BudgetLineStatus =
  | "Calculated"
  | "Incomplete"
  | "Estimated"
  | "Blocked"
  | "Excluded";

export type BudgetLine = {
  activityId: string;
  status: BudgetLineStatus;
  statusReason?: string;
  kind: PlannedActivity["kind"];
  deliveryOwner: "STAFF" | "PARTNER";
  staffId?: string;
  partnerId?: string;
  districtId: string;
  districtName: string;
  districtType: "PRIMARY" | "SECONDARY" | "NA";
  plannedWeek: 1 | 2 | 3 | 4 | 5;
  plannedMonthIso: string;
  quarter: "Q1" | "Q2" | "Q3" | "Q4";
  fyLabel: string;
  transport: number;
  breakfast: number;
  lunch: number;
  dinner: number;
  accommodation: number;
  sessionFee: number;
  venueFee: number;
  participantMeals: number;
  mobilisation: number;
  partnerLumpSum: number;
  other: number;
  total: number;
  costSettingsVersionId: string;
  sourceActivityIds: string[];
  calculationMethod: string;
};

// ---------- internal helpers ----------

type AnyActivity = PlannedActivity & Record<string, unknown>;

const ZERO_COST_FIELDS = {
  transport: 0,
  breakfast: 0,
  lunch: 0,
  dinner: 0,
  accommodation: 0,
  sessionFee: 0,
  venueFee: 0,
  participantMeals: 0,
  mobilisation: 0,
  partnerLumpSum: 0,
  other: 0,
  total: 0,
} as const;

function num(v: unknown, fallback = 0): number {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))) {
    return Number(v);
  }
  return fallback;
}

function str(v: unknown, fallback = ""): string {
  if (typeof v === "string") return v;
  if (v == null) return fallback;
  return String(v);
}

function pickWeek(v: unknown): 1 | 2 | 3 | 4 | 5 {
  const n = num(v, 1);
  if (n === 1 || n === 2 || n === 3 || n === 4 || n === 5) return n;
  return 1;
}

function pickQuarter(v: unknown): "Q1" | "Q2" | "Q3" | "Q4" {
  const s = str(v, "Q1");
  if (s === "Q1" || s === "Q2" || s === "Q3" || s === "Q4") return s;
  return "Q1";
}

function totalOf(parts: Partial<Record<keyof typeof ZERO_COST_FIELDS, number>>): number {
  return (
    num(parts.transport) +
    num(parts.breakfast) +
    num(parts.lunch) +
    num(parts.dinner) +
    num(parts.accommodation) +
    num(parts.sessionFee) +
    num(parts.venueFee) +
    num(parts.participantMeals) +
    num(parts.mobilisation) +
    num(parts.partnerLumpSum) +
    num(parts.other)
  );
}

function baseLine(
  activity: AnyActivity,
  overrides: Partial<BudgetLine> & { status: BudgetLineStatus },
  settings: CostSettings,
): BudgetLine {
  const versionId = str(
    (settings as unknown as { versionId?: string; id?: string }).versionId ??
      (settings as unknown as { id?: string }).id,
    "unknown",
  );

  const line: BudgetLine = {
    activityId: str(activity?.id ?? overrides.activityId, ""),
    status: overrides.status,
    statusReason: overrides.statusReason,
    kind: (activity?.kind ?? overrides.kind) as PlannedActivity["kind"],
    deliveryOwner: overrides.deliveryOwner ?? "STAFF",
    staffId: overrides.staffId ?? (activity?.staffId as string | undefined),
    partnerId:
      overrides.partnerId ?? (activity?.partnerId as string | undefined),
    districtId: str(overrides.districtId ?? activity?.districtId, ""),
    districtName: str(overrides.districtName ?? activity?.districtName, ""),
    districtType: overrides.districtType ?? "NA",
    plannedWeek: overrides.plannedWeek ?? pickWeek(activity?.plannedWeek),
    plannedMonthIso: str(
      overrides.plannedMonthIso ?? activity?.plannedMonthIso,
      "",
    ),
    quarter: overrides.quarter ?? pickQuarter(activity?.quarter),
    fyLabel: str(overrides.fyLabel ?? activity?.fyLabel, ""),
    transport: 0,
    breakfast: 0,
    lunch: 0,
    dinner: 0,
    accommodation: 0,
    sessionFee: 0,
    venueFee: 0,
    participantMeals: 0,
    mobilisation: 0,
    partnerLumpSum: 0,
    other: 0,
    total: 0,
    costSettingsVersionId: versionId,
    sourceActivityIds: overrides.sourceActivityIds ?? [
      str(activity?.id, ""),
    ],
    calculationMethod: overrides.calculationMethod ?? "",
  };

  // Apply numeric overrides
  const costKeys: (keyof typeof ZERO_COST_FIELDS)[] = [
    "transport",
    "breakfast",
    "lunch",
    "dinner",
    "accommodation",
    "sessionFee",
    "venueFee",
    "participantMeals",
    "mobilisation",
    "partnerLumpSum",
    "other",
  ];
  for (const k of costKeys) {
    if (overrides[k] != null) {
      (line[k] as number) = num(overrides[k]);
    }
  }
  line.total =
    overrides.total != null
      ? num(overrides.total)
      : totalOf({
          transport: line.transport,
          breakfast: line.breakfast,
          lunch: line.lunch,
          dinner: line.dinner,
          accommodation: line.accommodation,
          sessionFee: line.sessionFee,
          venueFee: line.venueFee,
          participantMeals: line.participantMeals,
          mobilisation: line.mobilisation,
          partnerLumpSum: line.partnerLumpSum,
          other: line.other,
        });

  return line;
}

function blockedLine(
  activity: AnyActivity,
  reason: string,
  settings: CostSettings,
  overrides: Partial<BudgetLine> = {},
): BudgetLine {
  return baseLine(
    activity,
    {
      status: "Blocked",
      statusReason: reason,
      calculationMethod: "blocked",
      ...overrides,
      ...ZERO_COST_FIELDS,
    },
    settings,
  );
}

function incompleteLine(
  activity: AnyActivity,
  reason: string,
  settings: CostSettings,
  overrides: Partial<BudgetLine> = {},
): BudgetLine {
  return baseLine(
    activity,
    {
      status: "Incomplete",
      statusReason: reason,
      calculationMethod: "incomplete",
      ...overrides,
      ...ZERO_COST_FIELDS,
    },
    settings,
  );
}

// ---------- groupStaffVisitsByDay ----------

export function groupStaffVisitsByDay(
  activities: PlannedActivity[],
): PlannedActivity[][] {
  const groups = new Map<string, PlannedActivity[]>();
  const singletons: PlannedActivity[][] = [];

  for (const a of activities) {
    const act = a as AnyActivity;
    const staffId = act.staffId as string | undefined;
    if (!staffId) {
      singletons.push([a]);
      continue;
    }
    const districtId = str(act.districtId, "");
    const scheduled = str(act.scheduledDateIso, "");
    const dayKey = scheduled !== ""
      ? scheduled
      : `${pickWeek(act.plannedWeek)}|${str(act.plannedMonthIso, "")}`;
    const key = `${staffId}::${dayKey}::${districtId}`;

    const existing = groups.get(key);
    if (existing) {
      existing.push(a);
    } else {
      groups.set(key, [a]);
    }
  }

  return [...groups.values(), ...singletons];
}

// ---------- staff visit ----------

export function calculateStaffVisitBudget(
  dailyGroup: PlannedActivity[],
  staff: StaffProfile,
  settings: CostSettings,
): BudgetLine {
  const first = (dailyGroup[0] ?? {}) as AnyActivity;
  const sourceIds = dailyGroup.map((a) => str((a as AnyActivity).id, ""));
  const schoolCount = dailyGroup.length;

  // Budgetable / staff gate
  if (!isBudgetable(staff)) {
    const reason =
      ((staff as unknown as { nonBudgetableReason?: string })
        .nonBudgetableReason) ?? "Staff is not budgetable";
    return blockedLine(first, reason, settings, {
      deliveryOwner: "STAFF",
      staffId: (staff as unknown as { id?: string }).id ?? first.staffId as string | undefined,
      sourceActivityIds: sourceIds,
    });
  }

  const staffAny = staff as unknown as {
    id?: string;
    primaryDistrictId?: string | null;
  };
  if (!staffAny.primaryDistrictId) {
    return blockedLine(first, "Staff has no primary district", settings, {
      deliveryOwner: "STAFF",
      staffId: staffAny.id,
      sourceActivityIds: sourceIds,
    });
  }

  const districtId = str(first.districtId, "");
  if (!districtId) {
    return blockedLine(first, "Visit district missing", settings, {
      deliveryOwner: "STAFF",
      staffId: staffAny.id,
      sourceActivityIds: sourceIds,
    });
  }

  const districtClass = classifyDistrict(staff, districtId);
  const settingsAny = settings as unknown as {
    primaryTransportRate?: number;
    secondaryTransportRate?: number;
    breakfastRate?: number;
    lunchRate?: number;
    dinnerRate?: number;
    accommodationRate?: number;
  };

  if (districtClass === "PRIMARY") {
    const transport =
      schoolCount * num(settingsAny.primaryTransportRate);
    const lunch = num(settingsAny.lunchRate);
    return baseLine(
      first,
      {
        status: "Calculated",
        deliveryOwner: "STAFF",
        staffId: staffAny.id,
        districtType: "PRIMARY",
        transport,
        lunch,
        sourceActivityIds: sourceIds,
        calculationMethod: `staff-visit:PRIMARY schools=${schoolCount} transport=${schoolCount}*primaryRate lunchOnly`,
      },
      settings,
    );
  }

  if (districtClass === "SECONDARY") {
    const transport =
      schoolCount * num(settingsAny.secondaryTransportRate);
    const breakfast = num(settingsAny.breakfastRate);
    const lunch = num(settingsAny.lunchRate);
    const dinner = num(settingsAny.dinnerRate);
    const rawNights = num((first as AnyActivity).nights, 1);
    const nights = Math.max(1, rawNights);
    const accommodation = nights * num(settingsAny.accommodationRate);
    return baseLine(
      first,
      {
        status: "Calculated",
        deliveryOwner: "STAFF",
        staffId: staffAny.id,
        districtType: "SECONDARY",
        transport,
        breakfast,
        lunch,
        dinner,
        accommodation,
        sourceActivityIds: sourceIds,
        calculationMethod: `staff-visit:SECONDARY schools=${schoolCount} nights=${nights} fullMeals+accommodation`,
      },
      settings,
    );
  }

  return blockedLine(
    first,
    `District ${districtId} could not be classified as PRIMARY or SECONDARY for staff`,
    settings,
    {
      deliveryOwner: "STAFF",
      staffId: staffAny.id,
      sourceActivityIds: sourceIds,
    },
  );
}

// ---------- partner visit ----------

export function calculatePartnerVisitBudget(
  activity: PlannedActivity,
  settings: CostSettings,
): BudgetLine {
  const act = activity as AnyActivity;
  const partnerId = act.partnerId as string | undefined;

  if (!partnerId) {
    return blockedLine(act, "Partner missing", settings, {
      deliveryOwner: "PARTNER",
    });
  }

  const hasSchedule =
    str(act.scheduledDateIso, "") !== "" || act.plannedWeek != null;
  if (!hasSchedule) {
    return blockedLine(
      act,
      "Partner visit has no scheduledDate and no plannedWeek",
      settings,
      { deliveryOwner: "PARTNER", partnerId },
    );
  }

  const settingsAny = settings as unknown as {
    partnerVisitLumpSum?: number;
  };
  const lump = num(settingsAny.partnerVisitLumpSum);

  return baseLine(
    act,
    {
      status: "Calculated",
      deliveryOwner: "PARTNER",
      partnerId,
      partnerLumpSum: lump,
      calculationMethod: "partner-visit:lump-sum",
    },
    settings,
  );
}

// ---------- training ----------

export function calculateTrainingBudget(
  activity: PlannedActivity,
  settings: CostSettings,
): BudgetLine {
  const act = activity as AnyActivity;
  const participantCount = act.participantCount;
  if (participantCount == null || !Number.isFinite(Number(participantCount))) {
    return incompleteLine(
      act,
      "Training participantCount missing",
      settings,
      { deliveryOwner: "STAFF" },
    );
  }
  const pc = num(participantCount);

  const settingsAny = settings as unknown as {
    trainingSessionFee?: number;
    trainingVenueFee?: number;
    participantMealRate?: number;
    mobilisationPerParticipant?: number;
  };

  const sessionFee = num(settingsAny.trainingSessionFee);
  const venueFee = num(settingsAny.trainingVenueFee);
  const participantMeals = pc * num(settingsAny.participantMealRate);
  const mobilisation = pc * num(settingsAny.mobilisationPerParticipant);

  return baseLine(
    act,
    {
      status: "Calculated",
      deliveryOwner: "STAFF",
      sessionFee,
      venueFee,
      participantMeals,
      mobilisation,
      calculationMethod: `training: sessionFee+venueFee + ${pc}*(meal+mobilisation)`,
    },
    settings,
  );
}

// ---------- cluster meeting ----------

export function calculateClusterMeetingBudget(
  activity: PlannedActivity,
  settings: CostSettings,
): BudgetLine {
  const act = activity as AnyActivity;
  const participantCount = act.participantCount;
  if (participantCount == null || !Number.isFinite(Number(participantCount))) {
    return incompleteLine(
      act,
      "Cluster meeting participantCount missing",
      settings,
      { deliveryOwner: "STAFF" },
    );
  }
  const pc = num(participantCount);

  const settingsAny = settings as unknown as {
    clusterMeetingParticipantRate?: number;
  };
  const participantMeals = pc * num(settingsAny.clusterMeetingParticipantRate);

  return baseLine(
    act,
    {
      status: "Calculated",
      deliveryOwner: "STAFF",
      participantMeals,
      calculationMethod: `cluster-meeting: ${pc}*clusterMeetingParticipantRate`,
    },
    settings,
  );
}

// ---------- admin ----------

export function calculateAdminBudget(
  item: {
    id: string;
    quantity: number;
    unitCost: number;
    week: 1 | 2 | 3 | 4 | 5 | "Monthly";
    monthIso: string;
    name?: string;
  },
  settings: CostSettings,
): BudgetLine {
  const qty = num(item.quantity);
  const unit = num(item.unitCost);
  const total = qty * unit;
  const week: 1 | 2 | 3 | 4 | 5 = item.week === "Monthly" ? 1 : item.week;

  const pseudoActivity = {
    id: item.id,
    kind: "ADMIN",
    districtId: "",
    districtName: "",
    plannedWeek: week,
    plannedMonthIso: item.monthIso,
  } as unknown as AnyActivity;

  return baseLine(
    pseudoActivity,
    {
      activityId: item.id,
      status: "Calculated",
      deliveryOwner: "STAFF",
      districtType: "NA",
      districtId: "",
      districtName: "",
      plannedWeek: week,
      plannedMonthIso: item.monthIso,
      other: total,
      sourceActivityIds: [item.id],
      calculationMethod:
        item.week === "Monthly"
          ? `admin:monthly ${qty}*${unit} (single line week=1)`
          : `admin:weekly ${qty}*${unit}`,
    },
    settings,
  );
}
