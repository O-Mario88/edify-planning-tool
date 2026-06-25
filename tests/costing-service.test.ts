// Contract test for the central CostingService façade.
//
// Verifies that the FE `calculateActivityCost()` returns a normalized
// `CostingResult` with the exact fields the Schedule drawer needs:
//
//   • ok=true → totalCost, currency, breakdown lines, catalogueVersion,
//     missingItems (empty), canSchedule=true
//   • ok=false → reason, missingItems list, canSchedule=false
//
// We mock the `backendCostPreview` surface so this test doesn't need a
// running backend or a `BACKEND_BASE_URL`.

import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@/lib/api/surfaces", async (orig) => {
  const original = await orig() as Record<string, unknown>;
  return {
    ...original,
    backendCostPreview: vi.fn(),
  };
});

import { calculateActivityCost } from "@/lib/costing";
import { backendCostPreview } from "@/lib/api/surfaces";

const FAKE_USER = { id: "u1", role: "CCEO" } as never;

describe("calculateActivityCost — contract", () => {
  beforeEach(() => vi.resetAllMocks());

  it("returns ok=true with normalized shape when the backend is happy", async () => {
    (backendCostPreview as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      live: true,
      data: {
        source: "Uganda · FY2026 Country Cost Register",
        currency: "UGX",
        amount: 65000,
        costMissing: false,
        missingItems: [],
        catalogueVersion: 3,
        canSchedule: true,
        lines: [
          { label: "Transport (primary)", key: "staff_visit_transport_primary", unit: 50000, qty: 1, amount: 50000, missing: false },
          { label: "Lunch", key: "lunch", unit: 15000, qty: 1, amount: 15000, missing: false },
        ],
      },
    });

    const result = await calculateActivityCost(
      { activityType: "school_visit", deliveryType: "staff", districtType: "primary" },
      FAKE_USER,
    );

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.totalCost).toBe(65000);
    expect(result.currency).toBe("UGX");
    expect(result.catalogueVersion).toBe(3);
    expect(result.canSchedule).toBe(true);
    expect(result.lines).toHaveLength(2);
    expect(result.lines[0].costSettingKey).toBe("staff_visit_transport_primary");
    expect(result.missingItems).toEqual([]);
  });

  it("returns ok=false with reason=missing_cost_items when canSchedule=false", async () => {
    (backendCostPreview as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      live: true,
      data: {
        source: "Uganda · FY2026 Country Cost Register",
        currency: "UGX",
        amount: 0,
        costMissing: true,
        missingItems: ["breakfast", "dinner"],
        catalogueVersion: 3,
        canSchedule: false,
        lines: [],
      },
    });

    const result = await calculateActivityCost(
      { activityType: "school_visit", deliveryType: "staff", districtType: "secondary" },
      FAKE_USER,
    );

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.reason).toBe("missing_cost_items");
    expect(result.missingItems).toEqual(["breakfast", "dinner"]);
    expect(result.canSchedule).toBe(false);
  });

  it("returns ok=false with reason=fetch_failed when the backend is unreachable", async () => {
    (backendCostPreview as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      live: false,
      error: "no_base_url",
      data: null,
    });

    const result = await calculateActivityCost(
      { activityType: "school_visit", deliveryType: "staff" },
      FAKE_USER,
    );

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.reason).toBe("fetch_failed");
    expect(result.canSchedule).toBe(false);
  });
});
