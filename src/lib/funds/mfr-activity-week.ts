// Activity × Week aggregator.
//
// Cross-tabulates the Monthly Fund Request from "staff rows × activity
// columns" to "activity rows × week columns" — the cash-flow lens the
// CD / RVP / Accountant actually act on.
//
// Each line in the MFR contributes a slice of every category total to
// each week. We distribute using these rules (in priority order):
//
//   1. If the line carries a per-week breakdown for the category
//      (meals only, today) → use it verbatim.
//   2. If the line's source records have explicit `plannedWeek` values
//      (cluster trainings, group trainings, week-specific admin items)
//      → assign the whole amount to that week.
//   3. Otherwise (staff visits, partner visits, SSA, transport,
//      accommodation) → distribute proportionally to that line's
//      field-day shape (mealsByWeek). This is a defensible proxy: the
//      weeks the staff is on the field are the weeks money flows.
//      Lines with no field activity fall back to an even W1-W4 split.
//
// Admin items split: week-tagged items land on their week; "Monthly"
// items split evenly across W1-W4 (the 4 disbursement windows).
//
// The result is round-tripped to integers so totals always reconcile
// to the line-level grand total within ~UGX 5 of rounding.

import {
  CATEGORY_HEADER_LABEL,
  type MfrActivityCategory,
  type MonthlyFundRequest,
} from "./monthly-fund-request-types";

export type WeekIndex = 0 | 1 | 2 | 3 | 4;
const WEEK_KEYS = ["w1", "w2", "w3", "w4", "w5"] as const;

export type ActivityWeekRow = {
  category: MfrActivityCategory;
  label:    string;
  w1: number; w2: number; w3: number; w4: number; w5: number;
  total:    number;
};

export type ActivityWeekMatrix = {
  rows:           ActivityWeekRow[];
  weekTotals:     { w1: number; w2: number; w3: number; w4: number; w5: number };
  monthlyTotal:   number;
  // Category counts so the view can show "X activities in this category"
  categoryCounts: Record<MfrActivityCategory, number>;
};

const CATEGORY_ORDER: MfrActivityCategory[] = [
  "StaffVisits",
  "PartnerVisits",
  "SSA",
  "ClusterTraining",
  "GroupTrainings",
  "Meals",
  "Transport",
  "Accommodation",
  "Admin",
];

export function computeActivityWeekMatrix(
  mfr: MonthlyFundRequest,
): ActivityWeekMatrix {
  // Bucket store: [w1, w2, w3, w4, w5] per category
  const buckets: Record<MfrActivityCategory, [number, number, number, number, number]> = {
    StaffVisits:     [0, 0, 0, 0, 0],
    PartnerVisits:   [0, 0, 0, 0, 0],
    SSA:             [0, 0, 0, 0, 0],
    ClusterTraining: [0, 0, 0, 0, 0],
    GroupTrainings:  [0, 0, 0, 0, 0],
    Meals:           [0, 0, 0, 0, 0],
    Transport:       [0, 0, 0, 0, 0],
    Accommodation:   [0, 0, 0, 0, 0],
    Admin:           [0, 0, 0, 0, 0],
  };
  const counts: Record<MfrActivityCategory, number> = {
    StaffVisits: 0, PartnerVisits: 0, SSA: 0,
    ClusterTraining: 0, GroupTrainings: 0,
    Meals: 0, Transport: 0, Accommodation: 0, Admin: 0,
  };

  // Distribute lines
  for (const line of mfr.lines) {
    const share = fieldDayShare(line.mealsByWeek);

    // Meals — already weekly, copy verbatim
    buckets.Meals[0] += line.mealsByWeek.w1;
    buckets.Meals[1] += line.mealsByWeek.w2;
    buckets.Meals[2] += line.mealsByWeek.w3;
    buckets.Meals[3] += line.mealsByWeek.w4;
    buckets.Meals[4] += line.mealsByWeek.w5;
    if (line.mealsByWeek.w1 + line.mealsByWeek.w2 + line.mealsByWeek.w3 +
        line.mealsByWeek.w4 + line.mealsByWeek.w5 > 0) counts.Meals += 1;

    // Cluster training — use explicit plannedWeek from sources if any
    distribute(line.clusterTraining.total, "ClusterTraining", line.id, share, mfr, buckets);
    if (line.clusterTraining.count > 0) counts.ClusterTraining += 1;

    // Group trainings — same pattern
    distribute(line.groupTrainings.total, "GroupTrainings", line.id, share, mfr, buckets);
    if (line.groupTrainings.count > 0) counts.GroupTrainings += 1;

    // Staff visits / Partner visits / SSA / Transport / Accommodation —
    // no per-source week, distribute by field-day share.
    spread(line.staffVisits.total,        share, buckets.StaffVisits);
    if (line.staffVisits.count > 0) counts.StaffVisits += 1;
    spread(line.partnerVisits.total,      share, buckets.PartnerVisits);
    if (line.partnerVisits.count > 0) counts.PartnerVisits += 1;
    spread(line.ssa.total,                share, buckets.SSA);
    if (line.ssa.count > 0) counts.SSA += 1;
    spread(line.transportAllocation,      share, buckets.Transport);
    if (line.transportAllocation > 0) counts.Transport += 1;
    spread(line.accommodationAllocation,  share, buckets.Accommodation);
    if (line.accommodationAllocation > 0) counts.Accommodation += 1;
  }

  // Admin items
  for (const item of mfr.adminItems) {
    if (item.week === "Monthly") {
      // Spread across W1-W4 (4 disbursement windows)
      const each = item.totalCost / 4;
      buckets.Admin[0] += each;
      buckets.Admin[1] += each;
      buckets.Admin[2] += each;
      buckets.Admin[3] += each;
    } else {
      buckets.Admin[item.week - 1] += item.totalCost;
    }
    counts.Admin += 1;
  }

  // Build the row list in canonical order
  const rows: ActivityWeekRow[] = CATEGORY_ORDER
    .map((c) => {
      const b = buckets[c];
      const total = b[0] + b[1] + b[2] + b[3] + b[4];
      return {
        category: c,
        label:    CATEGORY_HEADER_LABEL[c],
        w1: Math.round(b[0]),
        w2: Math.round(b[1]),
        w3: Math.round(b[2]),
        w4: Math.round(b[3]),
        w5: Math.round(b[4]),
        total: Math.round(total),
      };
    })
    // Drop rows that ended up at zero so the matrix only shows
    // categories that actually carry value this month.
    .filter((r) => r.total > 0);

  const weekTotals = {
    w1: rows.reduce((s, r) => s + r.w1, 0),
    w2: rows.reduce((s, r) => s + r.w2, 0),
    w3: rows.reduce((s, r) => s + r.w3, 0),
    w4: rows.reduce((s, r) => s + r.w4, 0),
    w5: rows.reduce((s, r) => s + r.w5, 0),
  };
  const monthlyTotal = weekTotals.w1 + weekTotals.w2 + weekTotals.w3 + weekTotals.w4 + weekTotals.w5;

  return { rows, weekTotals, monthlyTotal, categoryCounts: counts };
}

// ────────── Helpers ──────────────────────────────────────────────────

function fieldDayShare(mealsByWeek: { w1: number; w2: number; w3: number; w4: number; w5: number }): [number, number, number, number, number] {
  const total = mealsByWeek.w1 + mealsByWeek.w2 + mealsByWeek.w3 + mealsByWeek.w4 + mealsByWeek.w5;
  if (total === 0) {
    // No field activity — fall back to even W1-W4 split, W5 zero.
    return [0.25, 0.25, 0.25, 0.25, 0];
  }
  return [
    mealsByWeek.w1 / total,
    mealsByWeek.w2 / total,
    mealsByWeek.w3 / total,
    mealsByWeek.w4 / total,
    mealsByWeek.w5 / total,
  ];
}

function spread(
  amount: number,
  share: [number, number, number, number, number],
  bucket: [number, number, number, number, number],
) {
  for (let i = 0; i < 5; i++) bucket[i] += amount * share[i];
}

// Cluster + group trainings: source records may carry explicit
// plannedWeek. When present, put the whole amount in that week.
// Otherwise fall back to field-day spread.
function distribute(
  amount: number,
  category: MfrActivityCategory,
  lineId: string,
  share: [number, number, number, number, number],
  mfr: MonthlyFundRequest,
  buckets: Record<MfrActivityCategory, [number, number, number, number, number]>,
) {
  if (amount <= 0) return;
  const sources = mfr.sources.filter(
    (s) => s.lineId === lineId && s.costCategory === category && s.plannedWeek != null,
  );
  if (sources.length > 0) {
    // Distribute proportionally across the explicit weeks
    const sourceTotal = sources.reduce((s, x) => s + x.amount, 0);
    if (sourceTotal > 0) {
      for (const src of sources) {
        const w = (src.plannedWeek as 1 | 2 | 3 | 4 | 5) - 1;
        buckets[category][w] += amount * (src.amount / sourceTotal);
      }
      return;
    }
  }
  spread(amount, share, buckets[category]);
}

// Used by the view to label the week columns. Returns "W1" / "W2" /…
export function weekColumnLabels(): string[] {
  return WEEK_KEYS.map((k) => k.toUpperCase());
}
