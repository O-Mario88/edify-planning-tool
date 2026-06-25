// Cluster Planning Intelligence — engine tests.
//
// These prove the open-ended cluster planning model:
//   • SSA per-intervention averages + improvement / decline math
//   • coverage gap counts
//   • cadence counts NEVER cap at 3 (the user mandate)
//   • recommendation priority ordering (drop > weak > not-visited > not-trained
//     > no-meeting-this-fy > no-meeting-this-quarter > on-track) AND the
//     URGENT escalation for schools with neither visit nor training
//   • gap category mapping for the planning board

import { describe, expect, it } from "vitest";

import {
  computeClusterIntelligence,
  statusForScore,
  CLUSTER_GAP_CATEGORY_LABEL,
  type ClusterIntelActivity,
  type ClusterIntelInput,
  type ClusterIntelSchool,
} from "../src/lib/cluster/cluster-intelligence";

// A reference "now" so quarter math is deterministic. Q1 2026.
const NOW = new Date("2026-02-15T12:00:00Z");

function school(
  schoolId: string,
  opts: Partial<ClusterIntelSchool> = {},
): ClusterIntelSchool {
  return {
    schoolId,
    schoolName: `School ${schoolId}`,
    schoolType: "Client",
    hasCurrentFySsa: true,
    visitedThisPeriod: true,
    trainedThisPeriod: true,
    ...opts,
  };
}

function meeting(
  id: string,
  date: string,
  status: ClusterIntelActivity["status"] = "Completed",
): ClusterIntelActivity {
  return { id, activityType: "cluster_meeting", date, status };
}

function training(
  id: string,
  date: string,
  status: ClusterIntelActivity["status"] = "Completed",
): ClusterIntelActivity {
  return { id, activityType: "cluster_training", date, status };
}

function input(overrides: Partial<ClusterIntelInput>): ClusterIntelInput {
  return {
    schools: [],
    activities: [],
    now: NOW,
    ...overrides,
  };
}

describe("statusForScore", () => {
  it("maps SSA score → status using the spec thresholds", () => {
    expect(statusForScore(0)).toBe("Critical");
    expect(statusForScore(4.9)).toBe("Critical");
    expect(statusForScore(5)).toBe("Needs Support");
    expect(statusForScore(6.9)).toBe("Needs Support");
    expect(statusForScore(7)).toBe("Good");
    expect(statusForScore(8.9)).toBe("Good");
    expect(statusForScore(9)).toBe("Strong");
    expect(statusForScore(10)).toBe("Strong");
  });
});

describe("computeClusterIntelligence — SSA math", () => {
  it("computes per-intervention averages, weakest, strongest, and delta", () => {
    const intel = computeClusterIntelligence(
      input({
        schools: [
          school("s1", {
            currentSsa: { "Teaching & Learning": 8, "Leadership": 4 },
            previousSsa: { "Teaching & Learning": 6, "Leadership": 5 },
          }),
          school("s2", {
            currentSsa: { "Teaching & Learning": 6, "Leadership": 4 },
            previousSsa: { "Teaching & Learning": 5, "Leadership": 5 },
          }),
        ],
      }),
    );

    const teaching = intel.ssaPerformance.find(
      (p) => p.intervention === "Teaching & Learning",
    )!;
    const leadership = intel.ssaPerformance.find(
      (p) => p.intervention === "Leadership",
    )!;
    expect(teaching.averageScore).toBe(7);
    expect(teaching.previousAverage).toBe(5.5);
    expect(teaching.delta).toBe(1.5);
    expect(teaching.status).toBe("Good");
    expect(leadership.averageScore).toBe(4);
    expect(leadership.delta).toBe(-1);
    expect(leadership.status).toBe("Critical");

    expect(intel.weakestIntervention?.intervention).toBe("Leadership");
    expect(intel.strongestIntervention?.intervention).toBe(
      "Teaching & Learning",
    );
  });

  it("counts schools improved + declined per intervention", () => {
    const intel = computeClusterIntelligence(
      input({
        schools: [
          school("s1", {
            currentSsa: { "Teaching & Learning": 8 },
            previousSsa: { "Teaching & Learning": 6 },
          }),
          school("s2", {
            currentSsa: { "Teaching & Learning": 7 },
            previousSsa: { "Teaching & Learning": 5 },
          }),
          school("s3", {
            currentSsa: { "Leadership": 3 },
            previousSsa: { "Leadership": 6 },
          }),
        ],
      }),
    );
    const improved = intel.improved.find(
      (i) => i.intervention === "Teaching & Learning",
    );
    expect(improved).toBeDefined();
    expect(improved!.schoolsImproved).toBe(2);

    const declined = intel.declined.find((d) => d.intervention === "Leadership");
    expect(declined).toBeDefined();
    expect(declined!.schoolsDeclined).toBe(1);
    expect(declined!.drop).toBe(3);
  });
});

describe("computeClusterIntelligence — coverage", () => {
  it("counts schools visited / not-visited / trained / not-trained / neither", () => {
    const intel = computeClusterIntelligence(
      input({
        schools: [
          school("a", { visitedThisPeriod: true, trainedThisPeriod: true }),
          school("b", { visitedThisPeriod: true, trainedThisPeriod: false }),
          school("c", { visitedThisPeriod: false, trainedThisPeriod: true }),
          school("d", { visitedThisPeriod: false, trainedThisPeriod: false }),
          school("e", { visitedThisPeriod: false, trainedThisPeriod: false }),
        ],
      }),
    );
    expect(intel.coverage.total).toBe(5);
    expect(intel.coverage.visited).toBe(2);
    expect(intel.coverage.notVisited.map((s) => s.schoolId)).toEqual([
      "c", "d", "e",
    ]);
    expect(intel.coverage.notTrained.map((s) => s.schoolId)).toEqual([
      "b", "d", "e",
    ]);
    expect(intel.coverage.neitherVisitNorTraining.map((s) => s.schoolId)).toEqual([
      "d", "e",
    ]);
  });

  it("counts schools missing SSA", () => {
    const intel = computeClusterIntelligence(
      input({
        schools: [
          school("a", { hasCurrentFySsa: true }),
          school("b", { hasCurrentFySsa: false }),
          school("c", { hasCurrentFySsa: false }),
        ],
      }),
    );
    expect(intel.coverage.withCurrentFySsa).toBe(1);
    expect(intel.coverage.missingSsa).toBe(2);
  });
});

describe("computeClusterIntelligence — cadence (UNLIMITED MEETINGS)", () => {
  it("tracks a cluster with 4 completed meetings (NO 3-cap)", () => {
    const intel = computeClusterIntelligence(
      input({
        activities: [
          meeting("m1", "2026-01-05"),
          meeting("m2", "2026-01-15"),
          meeting("m3", "2026-01-25"),
          meeting("m4", "2026-02-05"), // 4th meeting — must NOT be blocked
        ],
      }),
    );
    expect(intel.cadence.meetingsThisFy).toBe(4);
  });

  it("tracks a cluster with 10 completed meetings + 2 scheduled", () => {
    const dates = Array.from({ length: 10 }, (_, i) =>
      `2026-0${1 + Math.floor(i / 4)}-${String((i % 4) * 5 + 1).padStart(2, "0")}`,
    );
    const intel = computeClusterIntelligence(
      input({
        activities: [
          ...dates.map((d, i) => meeting(`m${i}`, d)),
          meeting("m-up-1", "2026-03-10", "Scheduled"),
          meeting("m-up-2", "2026-03-20", "Scheduled"),
        ],
      }),
    );
    expect(intel.cadence.meetingsThisFy).toBe(10);
    expect(intel.cadence.meetingsScheduledThisFy).toBe(2);
  });

  it("identifies metThisQuarter = true when ANY completed meeting falls in the quarter", () => {
    const intel = computeClusterIntelligence(
      input({
        activities: [
          meeting("m-old", "2025-11-15"),    // prior quarter
          meeting("m-recent", "2026-02-01"), // this quarter (Q1 of 2026)
        ],
      }),
    );
    expect(intel.cadence.metThisQuarter).toBe(true);
  });

  it("identifies metThisQuarter = false when no completed meeting falls in the quarter", () => {
    const intel = computeClusterIntelligence(
      input({
        activities: [meeting("m-old", "2025-11-15")],
      }),
    );
    expect(intel.cadence.metThisQuarter).toBe(false);
  });
});

describe("computeClusterIntelligence — recommendation priority", () => {
  it("Priority 6 (escalated): schools with NEITHER visit nor training wins over everything", () => {
    const intel = computeClusterIntelligence(
      input({
        schools: [
          school("a", { visitedThisPeriod: false, trainedThisPeriod: false }),
          school("b", { visitedThisPeriod: false, trainedThisPeriod: false }),
          school("c", { visitedThisPeriod: true, trainedThisPeriod: true,
            currentSsa: { "Leadership": 2 }, previousSsa: { "Leadership": 9 } }),
        ],
        activities: [meeting("m", "2026-02-01")],
      }),
    );
    expect(intel.recommendation.priority).toBe("schools_neither");
    expect(intel.gapCategory).toBe("schools_neither_visit_nor_training");
  });

  it("Priority 1: SSA performance drop wins over weak intervention", () => {
    const intel = computeClusterIntelligence(
      input({
        schools: [
          school("a", {
            currentSsa: { "Teaching & Learning": 4 },
            previousSsa: { "Teaching & Learning": 8 },
          }),
          school("b", {
            currentSsa: { "Teaching & Learning": 5 },
            previousSsa: { "Teaching & Learning": 8 },
          }),
        ],
        activities: [meeting("m", "2026-02-01")],
      }),
    );
    expect(intel.recommendation.priority).toBe("ssa_drop");
    expect(intel.recommendation.focusIntervention).toBe("Teaching & Learning");
    expect(intel.gapCategory).toBe("ssa_performance_drop");
  });

  it("Priority 2: weakest intervention when no big drop", () => {
    const intel = computeClusterIntelligence(
      input({
        schools: [
          school("a", { currentSsa: { "Leadership": 4 } }),
          school("b", { currentSsa: { "Leadership": 4 } }),
        ],
        activities: [meeting("m", "2026-02-01")],
      }),
    );
    expect(intel.recommendation.priority).toBe("weak_intervention");
    expect(intel.recommendation.focusIntervention).toBe("Leadership");
    expect(intel.gapCategory).toBe("weak_ssa_intervention");
  });

  it("Priority 5: no meetings this FY when SSA is healthy and coverage is fine", () => {
    const intel = computeClusterIntelligence(
      input({
        schools: [school("a", { currentSsa: { "Leadership": 9 } })],
        activities: [],
      }),
    );
    expect(intel.recommendation.priority).toBe("no_meetings_this_fy");
    expect(intel.gapCategory).toBe("no_meetings_this_fy");
  });

  it("returns on_track when SSA is healthy and cluster met this quarter", () => {
    const intel = computeClusterIntelligence(
      input({
        schools: [
          school("a", { currentSsa: { "Teaching & Learning": 9 } }),
          school("b", { currentSsa: { "Teaching & Learning": 9 } }),
        ],
        activities: [
          meeting("m", "2026-02-01"),
          training("t", "2026-01-10"),
        ],
      }),
    );
    expect(intel.recommendation.priority).toBe("on_track");
    expect(intel.gapCategory).toBe("on_track");
  });
});

describe("CLUSTER_GAP_CATEGORY_LABEL", () => {
  it("never references 1st/2nd/3rd meeting (legacy vocabulary removed)", () => {
    for (const label of Object.values(CLUSTER_GAP_CATEGORY_LABEL)) {
      expect(label).not.toMatch(/1st|2nd|3rd|first cluster meeting|second cluster meeting|third cluster meeting/i);
    }
  });
});
