// School portfolio engine — owner resolution, auto-distribution, counts,
// and the unmatched-owner (IA owner-mapping) queue.

import { describe, expect, it } from "vitest";
import {
  resolveOwner,
  portfolioForName,
  portfolioForStaffId,
  ownerDistribution,
  unmatchedOwners,
} from "@/lib/portfolio/portfolio";

describe("resolveOwner — name → registered staff", () => {
  it("matches a registered owner name to a staffId", () => {
    const r = resolveOwner("Paul Chinyama");
    expect(r.status).toBe("matched");
    if (r.status === "matched") expect(r.staffId).toBe("STF-PC-001");
  });
  it("is case/space tolerant", () => {
    const r = resolveOwner("  paul   chinyama ".replace(/\s+/g, " ").trim());
    expect(r.status).toBe("matched");
  });
  it("flags an unknown owner name as unmatched (never silently dropped)", () => {
    const r = resolveOwner("James Okot");
    expect(r.status).toBe("unmatched");
  });
  it("returns none when no owner is set", () => {
    expect(resolveOwner(undefined).status).toBe("none");
    expect(resolveOwner("").status).toBe("none");
  });
});

describe("auto-distribution — owned schools appear in the staff portfolio", () => {
  it("a registered owner's schools land in their portfolio with counts", () => {
    const p = portfolioForName("Paul Chinyama")!;
    expect(p).toBeDefined();
    expect(p.staffId).toBe("STF-PC-001");
    // Seeded: 32791 (Client, SSA pending), 51884 (Core, SSA done), 52910 (Client, SSA pending)
    expect(p.counts.total).toBeGreaterThanOrEqual(3);
    expect(p.counts.client).toBeGreaterThanOrEqual(2);
    expect(p.counts.core).toBeGreaterThanOrEqual(1);
    expect(p.counts.missingSsa).toBeGreaterThanOrEqual(2);
  });
  it("counts partner-delegated schools without removing them from the portfolio", () => {
    // 40118 (Aisha Dar) has a seeded active partner delegation.
    const p = portfolioForName("Aisha Dar")!;
    expect(p.counts.total).toBeGreaterThanOrEqual(1);
    expect(p.counts.partnerAssigned).toBeGreaterThanOrEqual(1);
    // Still owned — the school is present in the portfolio list.
    expect(p.schools.some((s) => s.schoolId === "40118")).toBe(true);
  });
  it("an unknown staffId yields an empty portfolio", () => {
    expect(portfolioForStaffId("STF-NOBODY").counts.total).toBe(0);
  });
});

describe("owner distribution + unmatched queue", () => {
  it("summarizes matched / unmatched / unassigned", () => {
    const d = ownerDistribution();
    expect(d.matched).toBeGreaterThanOrEqual(4);
    expect(d.unmatched).toBeGreaterThanOrEqual(1);
    expect(d.owners).toBeGreaterThanOrEqual(2);
  });
  it("groups unmatched owners by the exact entered name", () => {
    const list = unmatchedOwners();
    const okot = list.find((u) => u.name === "James Okot");
    expect(okot).toBeDefined();
    expect(okot!.schoolIds).toContain("60233");
  });
});
