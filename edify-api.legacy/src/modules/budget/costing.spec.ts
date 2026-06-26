import { describe, it, expect } from "vitest";
import { ActivityType, DeliveryType } from "@prisma/client";
import { costForActivity, resolveActivityCost, type RateCard } from "./costing";

// The CD rate card used across these cases — complete catalogue including
// secondary-district per diems, mobilisation, and per-participant cluster
// meeting rate.
const RATES: RateCard = {
  staff_visit_transport_primary: 50000,
  staff_visit_transport_secondary: 30000,
  breakfast: 8000,
  lunch: 15000,
  dinner: 20000,
  accommodation: 80000,
  partner_visit_lump_sum: 120000,
  partner_training_lump_sum: 250000,
  training_session_fee: 200000,
  venue: 150000,
  meals_per_participant: 12000,
  mobilisation_per_participant: 5000,
  cluster_meeting_cost: 10000, // per-participant
};

const act = (over: Partial<Parameters<typeof costForActivity>[0]>) => ({
  activityType: ActivityType.school_visit,
  deliveryType: DeliveryType.staff,
  ...over,
});

describe("costForActivity — the automatic costing engine", () => {
  it("staff visit in PRIMARY district = transport + lunch only", () => {
    const c = costForActivity(act({ activityType: ActivityType.school_visit }), RATES);
    expect(c.amount).toBe(50000 + 15000);
    expect(c.costMissing).toBe(false);
  });

  it("staff visit in SECONDARY district (day trip) = transport + breakfast + lunch + dinner", () => {
    const c = costForActivity(
      act({ activityType: ActivityType.school_visit, districtType: "secondary" }),
      RATES,
    );
    // 30000 + 8000 + 15000 + 20000 = 73000 (no accommodation, nights=0)
    expect(c.amount).toBe(30000 + 8000 + 15000 + 20000);
  });

  it("staff visit in SECONDARY district (2 nights) = transport + per diems + 2 × accommodation", () => {
    const c = costForActivity(
      act({ activityType: ActivityType.school_visit, districtType: "secondary", nights: 2 }),
      RATES,
    );
    expect(c.amount).toBe(30000 + 8000 + 15000 + 20000 + 80000 * 2);
  });

  it("partner-delivered work is a lump sum, regardless of activity type", () => {
    const c = costForActivity(
      act({ activityType: ActivityType.school_visit, deliveryType: DeliveryType.partner }),
      RATES,
    );
    expect(c.amount).toBe(120000);
  });

  it("partner-delivered TRAINING uses the partner_training_lump_sum when configured", () => {
    const c = costForActivity(
      act({ activityType: ActivityType.training, deliveryType: DeliveryType.partner }),
      RATES,
    );
    expect(c.amount).toBe(250000);
  });

  it("partner-delivered training FALLS BACK to partner_visit_lump_sum when training rate missing", () => {
    const { partner_training_lump_sum: _drop, ...rates } = RATES;
    const c = costForActivity(
      act({ activityType: ActivityType.training, deliveryType: DeliveryType.partner }),
      rates,
    );
    expect(c.amount).toBe(120000);
  });

  it("staff training = session + venue + meals × N + mobilisation × N (default 25)", () => {
    const c = costForActivity(act({ activityType: ActivityType.training }), RATES);
    expect(c.amount).toBe(200000 + 150000 + (12000 + 5000) * 25);
  });

  it("training participant count scales with EXPECTED participants at planning time", () => {
    const c = costForActivity(
      act({ activityType: ActivityType.training, expectedParticipants: 40 }),
      RATES,
    );
    expect(c.amount).toBe(200000 + 150000 + (12000 + 5000) * 40);
  });

  it("training participant count scales with ACTUAL attendance when present (overrides expected)", () => {
    const c = costForActivity(
      act({
        activityType: ActivityType.training,
        expectedParticipants: 40,
        teachersAttended: 8,
        leadersAttended: 2,
      }),
      RATES,
    );
    expect(c.amount).toBe(200000 + 150000 + (12000 + 5000) * 10);
  });

  it("cluster meeting cost = unit × participants (10 default, scaling with expected)", () => {
    const c = costForActivity(act({ activityType: ActivityType.cluster_meeting }), RATES);
    expect(c.amount).toBe(10000 * 10);

    const c2 = costForActivity(
      act({ activityType: ActivityType.cluster_meeting, expectedParticipants: 20 }),
      RATES,
    );
    expect(c2.amount).toBe(10000 * 20);
  });

  it("missing rate → costMissing: true, amount: 0, and missingItems lists the keys", () => {
    const c = costForActivity(act({ activityType: ActivityType.school_visit }), {});
    expect(c.costMissing).toBe(true);
    expect(c.amount).toBe(0);
    expect(c.missingItems).toContain("staff_visit_transport_primary");
    expect(c.missingItems).toContain("lunch");
  });

  it("missing only the secondary-district breakfast rate is surfaced explicitly", () => {
    const { breakfast: _drop, ...partialRates } = RATES;
    const c = costForActivity(
      act({ activityType: ActivityType.school_visit, districtType: "secondary" }),
      partialRates,
    );
    expect(c.costMissing).toBe(true);
    expect(c.missingItems).toEqual(["breakfast"]);
  });
});

describe("resolveActivityCost — snapshot vs live recalc", () => {
  it("uses schedule snapshot when no attendance is recorded", () => {
    const c = resolveActivityCost(
      {
        activityType: ActivityType.school_visit,
        deliveryType: DeliveryType.staff,
        estCostCents: 65000,
        costMissing: false,
      },
      RATES,
      [
        {
          label: "Transport",
          costSettingKey: "staff_visit_transport_primary",
          unitCost: 50000,
          quantity: 1,
          amount: 50000,
        },
      ],
    );
    expect(c.amount).toBe(65000);
    expect(c.costMissing).toBe(false);
  });

  it("recalculates from attendance when actuals exist (catches the post-delivery scale)", () => {
    const c = resolveActivityCost(
      {
        activityType: ActivityType.training,
        deliveryType: DeliveryType.staff,
        estCostCents: 999,
        teachersAttended: 5,
      },
      RATES,
      [
        {
          label: "Old",
          costSettingKey: "training_session_fee",
          unitCost: 1,
          quantity: 1,
          amount: 1,
        },
      ],
    );
    expect(c.amount).toBe(200000 + 150000 + (12000 + 5000) * 5);
  });
});
