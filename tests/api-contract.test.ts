import { describe, it, expect, beforeEach } from "vitest";
import { z } from "zod";
import {
  validateContract,
  recordContractViolation,
  getContractViolations,
  clearContractViolations,
} from "@/lib/api/contract";
import {
  leadershipBoardsSchema,
  budgetBoardsSchema,
  activityPipelineSchema,
  dashboardSchema,
} from "@/lib/api/schemas";

// The golden rule under test: a payload that passes validation is fully valid
// (arrays are arrays, never undefined); a payload that fails is downgraded to a
// recorded contract violation — it must NOT reach the UI.

beforeEach(() => clearContractViolations());

describe("validateContract", () => {
  const schema = z.object({
    title: z.string(),
    rows: z.array(z.object({ id: z.string() })).default([]),
  });

  it("accepts a valid payload and returns typed data", () => {
    const r = validateContract(schema, { title: "x", rows: [{ id: "a" }] }, { endpoint: "/x" });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.data.rows).toHaveLength(1);
  });

  it("normalizes a missing array to [] (does not violate)", () => {
    const r = validateContract(schema, { title: "x" }, { endpoint: "/x" });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.data.rows).toEqual([]);
    expect(getContractViolations()).toHaveLength(0);
  });

  it("rejects null where an array is expected (real violation)", () => {
    const r = validateContract(schema, { title: "x", rows: null }, { endpoint: "/leadership" });
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.violation.errorType).toBe("DATA_CONTRACT_VIOLATION");
      expect(r.violation.missingFieldPath).toBe("rows");
      expect(r.violation.receivedType).toBe("null");
    }
  });

  it("rejects a wrong scalar type and records the field path", () => {
    const r = validateContract(schema, { title: 123, rows: [] }, { endpoint: "/x" });
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.violation.missingFieldPath).toBe("title");
      expect(r.violation.expectedType).toBe("string");
    }
  });

  it("records the violation in the registry with endpoint + role", () => {
    validateContract(schema, { title: 1 }, { endpoint: "/dash", role: "Admin", component: "X" });
    const v = getContractViolations();
    expect(v).toHaveLength(1);
    expect(v[0].endpoint).toBe("/dash");
    expect(v[0].role).toBe("Admin");
    expect(v[0].component).toBe("X");
  });
});

describe("contract violation registry", () => {
  it("dedupes repeated violations by endpoint+path and counts them", () => {
    const base = {
      errorType: "DATA_CONTRACT_VIOLATION" as const,
      severity: "error" as const,
      endpoint: "/leadership",
      missingFieldPath: "boards",
      message: "boards: expected array",
    };
    recordContractViolation(base);
    recordContractViolation(base);
    recordContractViolation(base);
    const v = getContractViolations();
    expect(v).toHaveLength(1);
    expect(v[0].count).toBe(3);
  });

  it("clears cleanly", () => {
    recordContractViolation({
      errorType: "FETCH_FAILED",
      severity: "warn",
      endpoint: "/x",
      message: "boom",
    });
    expect(getContractViolations().length).toBeGreaterThan(0);
    clearContractViolations();
    expect(getContractViolations()).toHaveLength(0);
  });
});

describe("dashboard schemas normalize arrays", () => {
  it("leadershipBoards: missing boards/visibleBoards default to []", () => {
    const r = validateContract(leadershipBoardsSchema, { fy: "2026" }, { endpoint: "/leadership/decision-engine" });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect((r.data as { boards: unknown[] }).boards).toEqual([]);
      expect((r.data as { visibleBoards: unknown[] }).visibleBoards).toEqual([]);
    }
  });

  it("leadershipBoards: nested insights default to [] per board", () => {
    const r = validateContract(
      leadershipBoardsSchema,
      { fy: "2026", boards: [{ decisionType: "staff", canReview: true }] },
      { endpoint: "/leadership/decision-engine" },
    );
    expect(r.ok).toBe(true);
    if (r.ok) {
      const boards = (r.data as { boards: { insights: unknown[] }[] }).boards;
      expect(boards[0].insights).toEqual([]);
    }
  });

  it("leadershipBoards: boards:null is a violation (not silently coerced)", () => {
    const r = validateContract(leadershipBoardsSchema, { fy: "2026", boards: null }, { endpoint: "/leadership/decision-engine" });
    expect(r.ok).toBe(false);
  });

  it("budgetBoards: missing insights defaults to []", () => {
    const r = validateContract(budgetBoardsSchema, { fy: "2026" }, { endpoint: "/budget-intelligence" });
    expect(r.ok).toBe(true);
    if (r.ok) expect((r.data as { insights: unknown[] }).insights).toEqual([]);
  });

  it("activityPipeline: missing byStatus/byDelivery default to []", () => {
    const r = validateContract(activityPipelineSchema, { total: 0 }, { endpoint: "/analytics/activity-pipeline" });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect((r.data as { byStatus: unknown[] }).byStatus).toEqual([]);
      expect((r.data as { byDelivery: unknown[] }).byDelivery).toEqual([]);
    }
  });

  it("dashboard: a missing required scalar is a violation", () => {
    const r = validateContract(dashboardSchema, { role: "CD" }, { endpoint: "/analytics/dashboard" });
    expect(r.ok).toBe(false);
  });
});
