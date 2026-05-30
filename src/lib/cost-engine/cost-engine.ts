// Visit cost engine — pure functions that compose CD-configured rates
// into a full breakdown for a single visit (one staff or partner, one
// trip, one or many schools).
//
// Pure: no server-only, no I/O. Rates are passed in as VisitCostRates.
// The server-side helper `loadVisitCostRates()` (cost-engine-server.ts)
// reads them from cost-settings-mock. Client/test callers pass literal
// rates. This mirrors the plan-cost-calculator pattern.
//
// Rules encoded here, set by the Country Director:
//
//   A. Partner visit
//      • Lump sum per school (default UGX 40k). No further breakdown.
//
//   B. Staff visit, primary district (school district matches staff home base)
//      • Transport: 56k per school visited
//      • Lunch:     30k per day
//      • No overnight by default
//
//   C. Staff visit, secondary district (school district ≠ staff home base)
//      • Transport: 66k per school visited
//      • Lunch:     30k per day
//      • Dinner:    56k per day
//      • Accommodation: 150k per night (auto-included; nights = days - 1
//        unless explicitly overridden)
//
// Mixed-district trips (some primary, some secondary on the same day) are
// rare and routed to the *most expensive* district type for the trip:
// once one secondary district is included, accommodation and the higher
// transport rate kick in. This matches Edify's existing accountability
// practice: you can't half-pay for an overnight.

// ────────── Types ──────────

export type DistrictType = "primary" | "secondary";

export type SchoolStop = {
  schoolId: string;
  schoolName: string;
  /// Derived from the staff's StaffHomeBase vs. the school's district.
  /// For partner visits, every school is priced flat regardless.
  districtType: DistrictType;
};

export type VisitMode = "staff" | "partner";

export type VisitCostRates = {
  staffPrimaryTransportPerSchool:   number; // "Staff Commuting Transport"
  staffSecondaryTransportPerSchool: number; // "Staff Overnight Transport"
  staffLunchPerDay:                 number; // "Lunch Per Day"
  staffBreakfastPerDay:             number; // "Breakfast Per Day" — secondary only
  staffDinnerPerDay:                number; // "Dinner Per Day"      — secondary only
  staffAccommodationPerNight:       number; // "Accommodation Per Night" — secondary only
  partnerLumpSumPerSchool:          number; // "Partner Visit Cost Per School"
};

/** Rates that drive group-activity costs (training, cluster meeting). */
export type GroupActivityRates = {
  trainingSessionFee:                  number; // "Training Session Fee"
  trainingVenueFee:                    number; // "Venue Fee"
  trainingParticipantMeals:            number; // "Training Participant Meals" — per head
  trainingMobilisationPerParticipant:  number; // "Training Mobilisation Per Participant"
  clusterMeetingPerParticipant:        number; // "Cluster Meeting Cost Per Participant"
};

export type CostInputs = {
  mode: VisitMode;
  schools: SchoolStop[];
  /// Days the visit spans. Default: 1.
  days?: number;
  /// Override for overnight count (rare). Default: max(0, days - 1) when
  /// any school is secondary; 0 otherwise.
  nights?: number;
  rates: VisitCostRates;
};

export type CostLineKind =
  | "transport"
  | "lunch"
  | "breakfast"
  | "dinner"
  | "accommodation"
  | "partner-lump-sum"
  | "training-session-fee"
  | "training-venue-fee"
  | "training-participant-meals"
  | "training-mobilisation"
  | "cluster-meeting-participant";

export type CostLine = {
  kind: CostLineKind;
  label: string;       // human-readable label rendered in the breakdown
  qty: number;         // schools, days, nights, or 1 (lump sum)
  unitCost: number;    // UGX per unit
  amountUgx: number;   // qty × unitCost
  note?: string;       // optional driver — "secondary district", etc.
};

export type RateKey =
  | "staffPrimaryTransportPerSchool"
  | "staffSecondaryTransportPerSchool"
  | "staffLunchPerDay"
  | "staffBreakfastPerDay"
  | "staffDinnerPerDay"
  | "staffAccommodationPerNight"
  | "partnerLumpSumPerSchool"
  | "trainingSessionFee"
  | "trainingVenueFee"
  | "trainingParticipantMeals"
  | "trainingMobilisationPerParticipant"
  | "clusterMeetingPerParticipant";

export type CostBreakdown = {
  mode: VisitMode;
  /// Derived district type for the trip. Any secondary school in the
  /// trip → "secondary" (see "mixed-district trips" note above).
  tripDistrictType: DistrictType;
  schoolCount: number;
  days: number;
  nights: number;
  totalUgx: number;
  lines: CostLine[];
  /// True if any school was secondary. Drives the "accommodation
  /// included by default" badge in the UI.
  overnightRequired: boolean;
  /// Rate keys that were 0 — caller decides whether to surface "blocked
  /// — CD hasn't set this rate" or fall through.
  missingRates: RateKey[];
};

// ────────── Core ──────────

export function computeVisitCost(input: CostInputs): CostBreakdown {
  const days = Math.max(1, input.days ?? 1);
  const schoolCount = input.schools.length;
  const anySecondary = input.schools.some((s) => s.districtType === "secondary");
  const overnightRequired = input.mode === "staff" && anySecondary;
  const nights = input.nights ?? (overnightRequired ? Math.max(0, days - 1) : 0);
  // "Mixed" trips inherit secondary rates — the moment one secondary
  // school is in the trip the daily allowance + transport tier shifts.
  const tripDistrictType: DistrictType = anySecondary ? "secondary" : "primary";

  if (input.mode === "partner") {
    return computePartnerCost({
      schoolCount,
      days,
      nights,
      tripDistrictType,
      rates: input.rates,
    });
  }
  return computeStaffCost({
    schoolCount,
    days,
    nights,
    tripDistrictType,
    overnightRequired,
    rates: input.rates,
  });
}

// ────────── Partner ──────────

function computePartnerCost(args: {
  schoolCount: number;
  days: number;
  nights: number;
  tripDistrictType: DistrictType;
  rates: VisitCostRates;
}): CostBreakdown {
  const lumpUnit = args.rates.partnerLumpSumPerSchool;
  const missingRates: RateKey[] = lumpUnit > 0 ? [] : ["partnerLumpSumPerSchool"];
  const amount = lumpUnit * args.schoolCount;
  const line: CostLine = {
    kind: "partner-lump-sum",
    label: `Partner visit (${args.schoolCount} school${args.schoolCount === 1 ? "" : "s"})`,
    qty: args.schoolCount,
    unitCost: lumpUnit,
    amountUgx: amount,
    note: "Set by Country Director · lump sum",
  };
  return {
    mode: "partner",
    tripDistrictType: args.tripDistrictType,
    schoolCount: args.schoolCount,
    days: args.days,
    nights: args.nights,
    totalUgx: amount,
    lines: [line],
    overnightRequired: false,
    missingRates,
  };
}

// ────────── Staff ──────────

function computeStaffCost(args: {
  schoolCount: number;
  days: number;
  nights: number;
  tripDistrictType: DistrictType;
  overnightRequired: boolean;
  rates: VisitCostRates;
}): CostBreakdown {
  const isSecondary = args.tripDistrictType === "secondary";
  const transportRate = isSecondary
    ? args.rates.staffSecondaryTransportPerSchool
    : args.rates.staffPrimaryTransportPerSchool;
  const lunchRate = args.rates.staffLunchPerDay;
  const breakfastRate = args.rates.staffBreakfastPerDay;
  const dinnerRate = args.rates.staffDinnerPerDay;
  const accommodationRate = args.rates.staffAccommodationPerNight;

  const missingRates: RateKey[] = [];
  if (transportRate <= 0) {
    missingRates.push(isSecondary ? "staffSecondaryTransportPerSchool" : "staffPrimaryTransportPerSchool");
  }
  if (lunchRate <= 0) missingRates.push("staffLunchPerDay");
  if (isSecondary && breakfastRate <= 0) missingRates.push("staffBreakfastPerDay");
  if (isSecondary && dinnerRate <= 0) missingRates.push("staffDinnerPerDay");
  if (isSecondary && args.nights > 0 && accommodationRate <= 0) {
    missingRates.push("staffAccommodationPerNight");
  }

  const lines: CostLine[] = [];

  // Transport — per school visited (NOT per day; the rate is per stop).
  const transportLabel = isSecondary
    ? `Transport (secondary district, ${args.schoolCount} school${args.schoolCount === 1 ? "" : "s"})`
    : `Transport (${args.schoolCount} school${args.schoolCount === 1 ? "" : "s"})`;
  lines.push({
    kind: "transport",
    label: transportLabel,
    qty: args.schoolCount,
    unitCost: transportRate,
    amountUgx: transportRate * args.schoolCount,
    note: isSecondary ? "Higher rate — district outside staff's home base" : undefined,
  });

  // Lunch — per day
  lines.push({
    kind: "lunch",
    label: `Lunch (${args.days} day${args.days === 1 ? "" : "s"})`,
    qty: args.days,
    unitCost: lunchRate,
    amountUgx: lunchRate * args.days,
  });

  // Breakfast + Dinner + Accommodation — secondary district only.
  // Order: Breakfast → Dinner → Accommodation so the breakdown reads
  // chronologically across a typical overnight day.
  if (isSecondary) {
    lines.push({
      kind: "breakfast",
      label: `Breakfast (${args.days} day${args.days === 1 ? "" : "s"})`,
      qty: args.days,
      unitCost: breakfastRate,
      amountUgx: breakfastRate * args.days,
      note: "Secondary district — auto-included",
    });
    lines.push({
      kind: "dinner",
      label: `Dinner (${args.days} day${args.days === 1 ? "" : "s"})`,
      qty: args.days,
      unitCost: dinnerRate,
      amountUgx: dinnerRate * args.days,
      note: "Secondary district — auto-included",
    });
    if (args.nights > 0) {
      lines.push({
        kind: "accommodation",
        label: `Accommodation (${args.nights} night${args.nights === 1 ? "" : "s"})`,
        qty: args.nights,
        unitCost: accommodationRate,
        amountUgx: accommodationRate * args.nights,
        note: "Auto-included — secondary district",
      });
    }
  }

  const totalUgx = lines.reduce((sum, line) => sum + line.amountUgx, 0);

  return {
    mode: "staff",
    tripDistrictType: args.tripDistrictType,
    schoolCount: args.schoolCount,
    days: args.days,
    nights: args.nights,
    totalUgx,
    lines,
    overnightRequired: args.overnightRequired,
    missingRates,
  };
}

// ────────── District-type derivation ──────────
//
// Pure helper: staff's home district + a target school's district →
// district type. Colocated with the pricing logic so the rule lives
// in one place.

export function deriveDistrictType(
  staffHomeDistrictId: string,
  schoolDistrictId: string,
): DistrictType {
  return staffHomeDistrictId === schoolDistrictId ? "primary" : "secondary";
}

// ────────── Training cost ──────────
//
// Training cost is composed of four CD-controlled rates:
//   • Session fee — flat per training
//   • Venue fee   — flat per training
//   • Participant meals — per head
//   • Mobilisation       — per head (transport / outreach reimbursement)
//
// Staff travel to facilitate the training is NOT included here — that
// is computed separately via computeVisitCost() and added to the plan
// total. This keeps the training budget auditable on its own terms.

export type TrainingCostInputs = {
  participants: number;
  rates:        GroupActivityRates;
};

export type GroupCostBreakdown = {
  kind:         "training" | "cluster-meeting";
  participants: number;
  totalUgx:     number;
  lines:        CostLine[];
  missingRates: RateKey[];
};

export function computeTrainingCost(input: TrainingCostInputs): GroupCostBreakdown {
  const p           = Math.max(0, Math.floor(input.participants));
  const session     = input.rates.trainingSessionFee;
  const venue       = input.rates.trainingVenueFee;
  const meals       = input.rates.trainingParticipantMeals;
  const mob         = input.rates.trainingMobilisationPerParticipant;

  const missingRates: RateKey[] = [];
  if (session <= 0) missingRates.push("trainingSessionFee");
  if (venue   <= 0) missingRates.push("trainingVenueFee");
  if (meals   <= 0) missingRates.push("trainingParticipantMeals");
  if (mob     <= 0) missingRates.push("trainingMobilisationPerParticipant");

  const lines: CostLine[] = [
    {
      kind: "training-session-fee",
      label: "Session fee",
      qty: 1,
      unitCost: session,
      amountUgx: session,
      note: "Set by Country Director",
    },
    {
      kind: "training-venue-fee",
      label: "Venue fee",
      qty: 1,
      unitCost: venue,
      amountUgx: venue,
    },
    {
      kind: "training-participant-meals",
      label: `Participant meals (${p} participant${p === 1 ? "" : "s"})`,
      qty: p,
      unitCost: meals,
      amountUgx: meals * p,
    },
    {
      kind: "training-mobilisation",
      label: `Mobilisation (${p} participant${p === 1 ? "" : "s"})`,
      qty: p,
      unitCost: mob,
      amountUgx: mob * p,
      note: "Transport / outreach reimbursement to participants",
    },
  ];

  const totalUgx = lines.reduce((sum, l) => sum + l.amountUgx, 0);
  return { kind: "training", participants: p, totalUgx, lines, missingRates };
}

// ────────── Cluster meeting cost ──────────
//
// Single rate × participants. Staff travel handled separately via
// computeVisitCost(), as with training.

export type ClusterMeetingCostInputs = {
  participants: number;
  rates:        GroupActivityRates;
};

export function computeClusterMeetingCost(input: ClusterMeetingCostInputs): GroupCostBreakdown {
  const p    = Math.max(0, Math.floor(input.participants));
  const rate = input.rates.clusterMeetingPerParticipant;

  const missingRates: RateKey[] = rate > 0 ? [] : ["clusterMeetingPerParticipant"];
  const lines: CostLine[] = [
    {
      kind: "cluster-meeting-participant",
      label: `Cluster meeting (${p} participant${p === 1 ? "" : "s"})`,
      qty: p,
      unitCost: rate,
      amountUgx: rate * p,
      note: "Single CD-set rate × participants",
    },
  ];
  return { kind: "cluster-meeting", participants: p, totalUgx: rate * p, lines, missingRates };
}

// ────────── Approval status ──────────
//
// Maps a cost breakdown + activity context to one of three states the
// approval queue and the planning UI read:
//
//   safe          — every rate present, sane values, ready to approve
//   needs_review  — unusual values (very high cost, many nights, big
//                   participant count) — supervisor should eyeball before
//                   approving but the plan is not blocked
//   blocked       — missing CD rate or invalid input — plan cannot be
//                   approved until the gap is fixed
//
// Pure: callers (approval queue cards, schedule rows) pass the
// breakdown + context and render the resulting badge + reason.

export type CostApprovalState = "safe" | "needs_review" | "blocked";

export type CostApprovalVerdict = {
  state:  CostApprovalState;
  reason: string;
};

export type ApprovalContext = {
  /** Activity type as it appears on the plan. */
  activityType?:        "Visit" | "Follow-Up Visit" | "Cluster Training" | "Cluster Meeting";
  /** Participants for training / cluster meeting; undefined for visits. */
  participants?:        number;
  /** Nights for visits; undefined for group activities. */
  nights?:              number;
  /** Total amount about to be approved — used for the high-cost gate. */
  totalUgx:             number;
  /** Any missing-rate gaps from the engine output. */
  missingRates:         RateKey[];
};

const HIGH_TRAINING_PARTICIPANTS_THRESHOLD = 60;
const HIGH_VISIT_NIGHTS_THRESHOLD          = 4;
const HIGH_VISIT_COST_THRESHOLD_UGX        = 1_200_000;
const HIGH_TRAINING_COST_THRESHOLD_UGX     = 1_800_000;

export function costApprovalStatus(ctx: ApprovalContext): CostApprovalVerdict {
  // BLOCKED — must precede every other check.
  if (ctx.missingRates.length > 0) {
    return {
      state:  "blocked",
      reason: `CD cost rate${ctx.missingRates.length === 1 ? "" : "s"} not set: ${ctx.missingRates.join(", ")}. Approval blocked until the Country Director activates the rate.`,
    };
  }
  if (ctx.totalUgx <= 0) {
    return {
      state:  "blocked",
      reason: "Computed cost is zero — required inputs missing (schools, days, or participants).",
    };
  }

  // NEEDS REVIEW — flag unusual values without blocking.
  const reasons: string[] = [];
  if ((ctx.nights ?? 0) > HIGH_VISIT_NIGHTS_THRESHOLD) {
    reasons.push(`${ctx.nights} overnight nights — unusually long trip`);
  }
  if (
    (ctx.activityType === "Cluster Training" || ctx.activityType === "Cluster Meeting") &&
    (ctx.participants ?? 0) > HIGH_TRAINING_PARTICIPANTS_THRESHOLD
  ) {
    reasons.push(`${ctx.participants} participants — above the ${HIGH_TRAINING_PARTICIPANTS_THRESHOLD}-head threshold`);
  }
  if (
    (ctx.activityType === "Visit" || ctx.activityType === "Follow-Up Visit") &&
    ctx.totalUgx > HIGH_VISIT_COST_THRESHOLD_UGX
  ) {
    reasons.push(`Visit total ${formatUgx(ctx.totalUgx)} exceeds the typical ${formatUgx(HIGH_VISIT_COST_THRESHOLD_UGX)} ceiling`);
  }
  if (
    (ctx.activityType === "Cluster Training" || ctx.activityType === "Cluster Meeting") &&
    ctx.totalUgx > HIGH_TRAINING_COST_THRESHOLD_UGX
  ) {
    reasons.push(`Group activity total ${formatUgx(ctx.totalUgx)} exceeds the typical ${formatUgx(HIGH_TRAINING_COST_THRESHOLD_UGX)} ceiling`);
  }
  if (reasons.length > 0) {
    return {
      state:  "needs_review",
      reason: reasons.join(" · "),
    };
  }

  // SAFE — every rate present, values within typical ranges.
  return {
    state:  "safe",
    reason: "All CD-set rates applied. Values within typical ranges.",
  };
}

function formatUgx(amount: number): string {
  if (amount >= 1_000_000) return `UGX ${(amount / 1_000_000).toFixed(1)}M`;
  if (amount >= 1_000)     return `UGX ${(amount / 1_000).toFixed(0)}K`;
  return `UGX ${amount}`;
}
