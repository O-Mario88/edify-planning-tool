import { describe, it, expect } from "vitest";
import { buildRoleActionBoard } from "@/lib/actions/role-action-engine";
import type { EdifyRole } from "@/lib/auth-public";

// Role-action-engine is the single brain feeding the 10-Second Command
// dashboards. These tests pin (a) every role gets a board, (b) the
// Next-3 ranking is consistent, (c) Blocked items never appear in
// Next-3, (d) the inbox tab membership is correct.

const NOW = new Date("2026-05-15T14:00:00.000Z");
const ROLES: EdifyRole[] = [
  "CCEO", "CountryProgramLead", "CountryDirector",
  "RVP", "ProgramAccountant", "ImpactAssessment",
  "HumanResource", "Admin",
];

describe("buildRoleActionBoard — universal contract", () => {
  it.each(ROLES)("returns a fully-populated board for %s", (role) => {
    const board = buildRoleActionBoard({ role, name: "Test User", now: NOW });
    expect(board.role).toBe(role);
    expect(board.header.greeting).toMatch(/Test/);
    expect(board.header.mission.length).toBeGreaterThan(10);
    expect(board.header.periodLabel.length).toBeGreaterThan(0);
    expect(Array.isArray(board.nextThree)).toBe(true);
    expect(Array.isArray(board.inbox)).toBe(true);
    expect(Array.isArray(board.doneToday)).toBe(true);
    expect(Array.isArray(board.changedSince)).toBe(true);
  });

  it.each(ROLES)("never surfaces a Blocked or Completed item in Next-3 for %s", (role) => {
    const board = buildRoleActionBoard({ role, name: "Test User", now: NOW });
    for (const item of board.nextThree) {
      expect(item.approvalSafety).not.toBe("Blocked");
      expect(item.status).not.toBe("Completed");
    }
  });

  it.each(ROLES)("returns at most 3 items in Next-3 for %s (the contract)", (role) => {
    const board = buildRoleActionBoard({ role, name: "Test User", now: NOW });
    expect(board.nextThree.length).toBeLessThanOrEqual(3);
  });

  it.each(ROLES)("ranks Next-3 by ascending priority for %s", (role) => {
    const board = buildRoleActionBoard({ role, name: "Test User", now: NOW });
    const priorities = board.nextThree.map((i) => i.priority);
    const sorted = [...priorities].sort((a, b) => a - b);
    expect(priorities).toEqual(sorted);
  });
});

describe("CCEO board — top-3 reflects field workflow priority", () => {
  it("Visit today is priority 1 (the canonical CCEO daily decision)", () => {
    const board = buildRoleActionBoard({ role: "CCEO", name: "Paul Chinyama", now: NOW });
    expect(board.nextThree[0].category).toBe("FieldVisit");
  });

  it("includes the Done-for-Today checklist with visit, evidence, funds, debrief", () => {
    const board = buildRoleActionBoard({ role: "CCEO", name: "Paul", now: NOW });
    const labels = board.doneToday.map((d) => d.label.toLowerCase());
    expect(labels.some((l) => l.includes("visit")))    .toBe(true);
    expect(labels.some((l) => l.includes("evidence"))) .toBe(true);
    expect(labels.some((l) => l.includes("fund")))     .toBe(true);
    expect(labels.some((l) => l.includes("debrief")))  .toBe(true);
  });
});

describe("CPL board — drives the team coaching decision", () => {
  it("surfaces a behind-pace staff action when team-targets shows one", () => {
    const board = buildRoleActionBoard({ role: "CountryProgramLead", name: "Daniel", now: NOW });
    const staffActions = board.inbox.filter((i) => i.category === "StaffSupport");
    expect(staffActions.length).toBeGreaterThan(0);
    expect(staffActions[0].riskLevel).toMatch(/Critical|High/);
  });

  it("includes at least one PlanApproval action in the inbox", () => {
    const board = buildRoleActionBoard({ role: "CountryProgramLead", name: "Daniel", now: NOW });
    expect(board.inbox.some((i) => i.category === "PlanApproval")).toBe(true);
  });

  it("includes a SchoolRisk action when urgent schools exist", () => {
    const board = buildRoleActionBoard({ role: "CountryProgramLead", name: "Daniel", now: NOW });
    expect(board.inbox.some((i) => i.category === "SchoolRisk")).toBe(true);
  });

  it("places blocked items in the Blocked inbox tab", () => {
    const board = buildRoleActionBoard({ role: "CountryProgramLead", name: "Daniel", now: NOW });
    const blocked = board.inbox.filter((i) => i.approvalSafety === "Blocked");
    expect(blocked.length).toBeGreaterThan(0);
    expect(blocked.every((i) => i.inboxTab === "Blocked")).toBe(true);
  });
});

describe("CD board — surfaces the unblockers first", () => {
  it("priority 1 is cost-settings (the single biggest blocker downstream)", () => {
    const board = buildRoleActionBoard({ role: "CountryDirector", name: "Sarah", now: NOW });
    expect(board.nextThree[0].category).toBe("CostSettings");
  });

  it("flags final fund sign-off as a top-3 action", () => {
    const board = buildRoleActionBoard({ role: "CountryDirector", name: "Sarah", now: NOW });
    expect(board.nextThree.some((i) => i.category === "FundApproval")).toBe(true);
  });
});

describe("Last-login digest is per-role and ordered newest-first", () => {
  it("returns the role-scoped change stream when no cookie is present (first visit)", () => {
    const board = buildRoleActionBoard({ role: "CCEO", name: "Paul", now: NOW });
    expect(board.changedSince.length).toBeGreaterThan(0);
    // Ordered newest first.
    for (let i = 1; i < board.changedSince.length; i++) {
      expect(new Date(board.changedSince[i - 1].at).getTime())
        .toBeGreaterThanOrEqual(new Date(board.changedSince[i].at).getTime());
    }
  });

  it("filters out changes that happened before the user's last-viewed cookie", () => {
    // Synthetic cookie set to 1 hour ago — should drop everything in the
    // mock that's older than 1 hour, keeping only ~the 1-hour-ago and
    // 30-min-ago entries (mock has hoursAgo from 1 upward).
    const sinceIso = new Date(NOW.getTime() - 4 * 60 * 60 * 1000).toISOString();
    const cookieHeader = `edify-last-viewed=${encodeURIComponent(sinceIso)}`;
    const board = buildRoleActionBoard({
      role: "ProgramAccountant", name: "Moses", now: NOW, cookieHeader,
    });
    for (const entry of board.changedSince) {
      expect(new Date(entry.at).getTime()).toBeGreaterThan(Date.parse(sinceIso));
    }
  });
});
