import { ActivityType, DeliveryType } from '@prisma/client';

// ── The automatic costing engine ────────────────────────────────────────────
// Every scheduled activity is costed from the CD-owned rate card (CostSetting,
// keyed by a stable string). No staff invents a cost. If a required rate is
// missing, the activity is flagged `costMissing` and must not enter a budget /
// fund request until the CD resolves it (spec §10).
//
// This is the SINGLE source of truth for activity cost on the backend.
// Frontend cost-preview surfaces should consume this via
// `POST /budget/costing/preview` rather than re-implementing the formulas.

export type RateCard = Record<string, number>; // CostSetting.key -> unitCost

export interface CostLine {
  label: string;
  key: string;
  unit: number | null; // null = rate missing
  qty: number;
  amount: number; // 0 when the rate is missing
  missing: boolean;
}

export interface ActivityCost {
  amount: number;
  lines: CostLine[];
  costMissing: boolean;
  /** Stable list of missing CostSetting keys — used by Cost Blocker UI and
   *  System Health to surface exactly what the CD needs to add. */
  missingItems: string[];
}

// Minimal shape the engine needs from an Activity row.
export interface CostableActivity {
  activityType: ActivityType;
  deliveryType: DeliveryType;
  /** 'primary' | 'secondary' — affects staff transport + per-diem package. */
  districtType?: string | null;
  teachersAttended?: number | null;
  leadersAttended?: number | null;
  otherParticipants?: number | null;
  /** For trainings: planned participant count (used when no attendance yet).
   *  Falls back to DEFAULT_TRAINING_PARTICIPANTS. */
  expectedParticipants?: number | null;
  /** For multi-day staff visits in a secondary district: number of nights
   *  the staff stays. Defaults to 0 (day trip) → no accommodation, single
   *  breakfast/lunch/dinner package only when nights > 0. */
  nights?: number | null;
  /** Optional project ID. When set, project-specific rates
   *  (`project_{kind}_lump_sum`) are preferred over the generic rate. */
  projectId?: string | null;
}

// Default participant estimate for a not-yet-delivered training, used only when
// no attendance figures exist yet (planning-time estimate).
const DEFAULT_TRAINING_PARTICIPANTS = 25;
/** Default cluster meeting participant estimate (2 per school × ~5 schools). */
const DEFAULT_CLUSTER_MEETING_PARTICIPANTS = 10;

const VISIT_TYPES: ActivityType[] = [
  ActivityType.school_visit,
  ActivityType.follow_up_visit,
  ActivityType.coaching_visit,
  ActivityType.in_school_support,
  ActivityType.core_visit,
];
const TRAINING_TYPES: ActivityType[] = [
  ActivityType.training,
  ActivityType.school_improvement_training,
  ActivityType.cluster_training,
  ActivityType.core_training,
];

function participantsOf(a: CostableActivity, defaultN: number): number {
  const counted =
    (a.teachersAttended ?? 0) + (a.leadersAttended ?? 0) + (a.otherParticipants ?? 0);
  if (counted > 0) return counted;
  const expected = a.expectedParticipants ?? 0;
  return expected > 0 ? expected : defaultN;
}

export function costForActivity(a: CostableActivity, rates: RateCard): ActivityCost {
  const lines: CostLine[] = [];
  const add = (label: string, key: string, qty = 1) => {
    const unit = rates[key];
    const missing = unit == null;
    lines.push({
      label,
      key,
      unit: missing ? null : unit,
      qty,
      amount: missing ? 0 : unit * qty,
      missing,
    });
  };

  const isPartner = a.deliveryType === DeliveryType.partner;
  const type = a.activityType;
  const isSecondary = a.districtType === 'secondary';

  if (isPartner) {
    // Partner work — project-specific rate when configured, else partner
    // training rate when this is a training, else the generic lump sum.
    const projectKey = a.projectId ? `project_partner_lump_sum` : null;
    const trainingKey = TRAINING_TYPES.includes(type) ? 'partner_training_lump_sum' : null;
    const fallback = 'partner_visit_lump_sum';
    let key = fallback;
    if (projectKey && rates[projectKey] != null) key = projectKey;
    else if (trainingKey && rates[trainingKey] != null) key = trainingKey;
    add('Partner lump sum', key);
  } else if (VISIT_TYPES.includes(type)) {
    // Staff visit. Primary district = transport + lunch (day trip).
    // Secondary district = transport (secondary rate) + breakfast + lunch +
    // dinner; if nights > 0, also accommodation × nights.
    if (isSecondary) {
      add('Transport (secondary)', 'staff_visit_transport_secondary');
      add('Breakfast', 'breakfast');
      add('Lunch', 'lunch');
      add('Dinner', 'dinner');
      const nights = Math.max(0, a.nights ?? 0);
      if (nights > 0) add('Accommodation', 'accommodation', nights);
    } else {
      add('Transport (primary)', 'staff_visit_transport_primary');
      add('Lunch', 'lunch');
    }
  } else if (TRAINING_TYPES.includes(type)) {
    // Staff training = session fee + venue + meals × participants + mobilisation × participants.
    // Mobilisation is the per-participant prep/airtime budget (spec §6/§7).
    const n = participantsOf(a, DEFAULT_TRAINING_PARTICIPANTS);
    add('Training session', 'training_session_fee');
    add('Venue', 'venue');
    add('Meals', 'meals_per_participant', n);
    add('Mobilisation', 'mobilisation_per_participant', n);
  } else if (type === ActivityType.cluster_meeting) {
    // Per-participant cluster meeting cost (UGX 10K × N is the FE default).
    // Backend uses the configurable `cluster_meeting_cost` rate as the
    // PER-PARTICIPANT unit, since a cluster meeting scales with attendance.
    const n = participantsOf(a, DEFAULT_CLUSTER_MEETING_PARTICIPANTS);
    add('Cluster meeting (per participant)', 'cluster_meeting_cost', n);
  } else if (type === ActivityType.partner_activity || type === ActivityType.project_activity) {
    const projectKey = a.projectId ? `project_partner_lump_sum` : null;
    const key = projectKey && rates[projectKey] != null ? projectKey : 'partner_visit_lump_sum';
    add('Partner/project lump sum', key);
  } else {
    // ssa_activity and anything else default to a staff visit cost.
    add('Transport', 'staff_visit_transport_primary');
    add('Lunch', 'lunch');
  }

  const costMissing = lines.some((l) => l.missing);
  const amount = lines.reduce((s, l) => s + l.amount, 0);
  const missingItems = lines.filter((l) => l.missing).map((l) => l.key);
  return { amount, lines, costMissing, missingItems };
}

export type SnapshotCostLine = {
  label: string;
  costSettingKey: string;
  unitCost: number;
  quantity: number;
  amount: number;
};

/** Prefer schedule-time snapshot; recalc from attendance when actuals exist. */
export function resolveActivityCost(
  a: CostableActivity & { estCostCents?: number | null; costMissing?: boolean | null },
  rates: RateCard,
  snapshotLines?: SnapshotCostLine[],
): ActivityCost {
  const attended =
    (a.teachersAttended ?? 0) + (a.leadersAttended ?? 0) + (a.otherParticipants ?? 0);
  if (attended > 0) return costForActivity(a, rates);

  if (snapshotLines?.length) {
    const lines: CostLine[] = snapshotLines.map((l) => ({
      label: l.label,
      key: l.costSettingKey,
      unit: l.unitCost,
      qty: l.quantity,
      amount: l.amount,
      missing: false,
    }));
    const amount = a.estCostCents != null && a.estCostCents > 0
      ? a.estCostCents
      : lines.reduce((s, l) => s + l.amount, 0);
    return { amount, lines, costMissing: a.costMissing ?? false, missingItems: [] };
  }

  if (a.estCostCents != null && a.estCostCents > 0) {
    return {
      amount: a.estCostCents,
      lines: [],
      costMissing: a.costMissing ?? false,
      missingItems: [],
    };
  }

  return costForActivity(a, rates);
}
