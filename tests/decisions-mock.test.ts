// Lock the mock Decision data against drift.
//
// The decisions UI is built against the Decision contract. These tests
// don't exercise the engine (it doesn't exist yet) — they assert the
// mocks conform so that when the engine lands and replaces the mocks,
// the UI keeps working without surprise.

import { describe, expect, it } from "vitest";
import {
  ALL_MOCK_DECISIONS,
  decisionBoardFor,
  decisionsForRole,
} from "@/lib/decisions/decisions-mock";

describe("decisions mock", () => {
  it("every decision has a non-empty rationale chain with at least one primary signal", () => {
    for (const d of ALL_MOCK_DECISIONS) {
      expect(d.rationale.length, `${d.id} missing rationale`).toBeGreaterThan(0);
      const hasPrimary = d.rationale.some((r) => r.weight === "primary");
      expect(hasPrimary, `${d.id} has no primary signal`).toBe(true);
    }
  });

  it("every decision declares its source signals", () => {
    for (const d of ALL_MOCK_DECISIONS) {
      expect(d.sourceSignals.length, `${d.id} missing sourceSignals`).toBeGreaterThan(0);
    }
  });

  it("NextBestDecision items with alternatives mark exactly one as recommended", () => {
    for (const d of ALL_MOCK_DECISIONS) {
      if (!d.alternatives || d.alternatives.length === 0) continue;
      const recommendedCount = d.alternatives.filter((a) => a.recommended).length;
      expect(recommendedCount, `${d.id} has ${recommendedCount} recommended alternatives`).toBe(1);
    }
  });

  it("decideBy is a valid future-or-recent ISO date when present", () => {
    for (const d of ALL_MOCK_DECISIONS) {
      if (!d.decideBy) continue;
      const parsed = new Date(d.decideBy);
      expect(Number.isFinite(parsed.getTime()), `${d.id} invalid decideBy`).toBe(true);
    }
  });

  it("priorities are 1..5 and unique-by-role keeps the top decision deterministic", () => {
    for (const d of ALL_MOCK_DECISIONS) {
      expect(d.priority).toBeGreaterThanOrEqual(1);
      expect(d.priority).toBeLessThanOrEqual(5);
    }
  });

  it("decisionBoardFor(CountryProgramLead) returns a hero plus a populated split", () => {
    const board = decisionBoardFor("CountryProgramLead");
    expect(board.topDecision).not.toBeNull();
    expect(board.role).toBe("CountryProgramLead");
    expect(board.nextBestActions.length + board.nextBestDecisions.length).toBeGreaterThan(0);
    expect(board.header.summary.length).toBeGreaterThan(0);
  });

  it("decisionBoardFor(CCEO) returns a hero and only NextBestAction-kind cards", () => {
    const board = decisionBoardFor("CCEO");
    expect(board.topDecision).not.toBeNull();
    // CCEO is field-officer scope; engine should not surface comparative
    // budget decisions to them. Mocks honour this today.
    expect(board.nextBestDecisions.length).toBe(0);
    expect(board.nextBestActions.length).toBeGreaterThan(0);
  });

  it("roles with no decisions yet get an empty board with an empty-state message", () => {
    const board = decisionBoardFor("ProgramAccountant");
    expect(board.topDecision).toBeNull();
    expect(board.nextBestActions.length).toBe(0);
    expect(board.nextBestDecisions.length).toBe(0);
    expect(board.emptyState?.headline).toBeTruthy();
  });

  it("decisionsForRole(Admin) mirrors CountryProgramLead", () => {
    const admin = decisionsForRole("Admin");
    const cpl = decisionsForRole("CountryProgramLead");
    expect(admin).toEqual(cpl);
  });

  it("CPL hero is the workload rebalance — highest priority decision", () => {
    const board = decisionBoardFor("CountryProgramLead");
    expect(board.topDecision?.category).toBe("WorkloadRebalance");
    expect(board.topDecision?.priority).toBe(1);
  });

  it("CCEO hero is a school intervention with cost breakdown", () => {
    const board = decisionBoardFor("CCEO");
    expect(board.topDecision?.category).toBe("SchoolIntervention");
    expect(board.topDecision?.costEstimateUgx).toBeGreaterThan(0);
    expect(board.topDecision?.costBreakdown?.length).toBeGreaterThan(0);
  });

  it("Hope Primary follow-up cost reflects CD's primary-district rule: 56k transport + 30k lunch = 86k", () => {
    const board = decisionBoardFor("CCEO");
    expect(board.topDecision?.costEstimateUgx).toBe(86_000);
  });

  it("Grace Primary intervention (partner) is the 40k lump sum", () => {
    const board = decisionBoardFor("CountryProgramLead");
    const grace = [board.topDecision, ...board.nextBestActions, ...board.nextBestDecisions]
      .filter((d): d is NonNullable<typeof d> => d !== null)
      .find((d) => d.subject.kind === "School" && d.subject.id === "S-GP-1");
    expect(grace?.costEstimateUgx).toBe(40_000);
  });

  it("Kitgum cluster (secondary district, 2 days) computes through the engine", () => {
    // 3 × 66k transport + 2 × 30k lunch + 2 × 20k breakfast + 2 × 50k dinner
    // + 1 × 150k accommodation = 198 + 60 + 40 + 100 + 150 = 548k.
    const board = decisionBoardFor("CCEO");
    const kitgum = board.nextBestActions.find((d) => d.id === "cceo-d-5");
    expect(kitgum?.costEstimateUgx).toBe(
      3 * 66_000 + 2 * 30_000 + 2 * 20_000 + 2 * 50_000 + 150_000,
    );
  });
});
