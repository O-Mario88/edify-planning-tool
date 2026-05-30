import { describe, it, expect } from "vitest";
import {
  computeSupportQuality,
  bandForQualityScore,
  type SupportQualityInputs,
} from "@/lib/quality/support-quality";

// Quality-of-support is the engine that lets the app stop rewarding
// activity volume. The headline test: a school with many activities but
// no measurable improvement scores LOWER than a school with fewer
// activities but real SSA + literacy gains.

function inputs(over: Partial<SupportQualityInputs> = {}): SupportQualityInputs {
  return {
    schoolId: "SCH-1",
    schoolName: "Hope Primary School",
    periodIso: "2026-05",
    activitiesAttempted: 8,
    activitiesCompleted: 8,
    evidenceCompletenessPct: 80,
    debriefQualityScore: 75,
    followUpCompletionPct: 80,
    schoolFeedbackScore: 80,
    ssaDelta: 0.6,
    trainingPrePostDeltaPct: 70,
    observationDeltaPct: 65,
    literacyDeltaPct: 65,
    verificationRatePct: 90,
    repeatSupportLandedPct: 80,
    ...over,
  };
}

describe("bandForQualityScore — boundary rules", () => {
  it.each([
    [95, "Excellent"], [85, "Excellent"],
    [84, "Strong"],    [70, "Strong"],
    [69, "Adequate"],  [55, "Adequate"],
    [54, "Inconsistent"], [40, "Inconsistent"],
    [39, "AtRisk"],    [0,  "AtRisk"],
  ] as const)("score %i maps to band %s", (score, band) => {
    expect(bandForQualityScore(score)).toBe(band);
  });
});

describe("computeSupportQuality — the headline product test", () => {
  it("a high-activity / no-improvement school scores LOWER than a low-activity / improving school", () => {
    const busyButFlat = computeSupportQuality(inputs({
      activitiesCompleted: 18,
      ssaDelta:               0.0,
      trainingPrePostDeltaPct: 50,
      observationDeltaPct:     50,
      literacyDeltaPct:        50,
      followUpCompletionPct:   60,
    }));
    const fewButImproving = computeSupportQuality(inputs({
      activitiesCompleted: 4,
      ssaDelta:               1.0,
      trainingPrePostDeltaPct: 85,
      observationDeltaPct:     80,
      literacyDeltaPct:        80,
      followUpCompletionPct:   95,
    }));
    expect(fewButImproving.score).toBeGreaterThan(busyButFlat.score);
  });

  it("breakdown sums to the displayed score (transparency contract)", () => {
    const r = computeSupportQuality(inputs());
    const sum = Math.round(Object.values(r.breakdown).reduce((a, b) => a + b, 0));
    expect(Math.abs(sum - r.score)).toBeLessThanOrEqual(1);
  });

  it("undefined optional deltas score as neutral 50, not 0 (don't penalise missing signals)", () => {
    const withSignals    = computeSupportQuality(inputs({ literacyDeltaPct: 80 }));
    const withoutSignals = computeSupportQuality(inputs({ literacyDeltaPct: undefined }));
    // Without the +80 signal but with neutral 50, the contribution falls
    // but doesn't crash to 0 — score difference is bounded.
    expect(withSignals.score - withoutSignals.score).toBeLessThan(10);
  });

  it("negative SSA delta drags the score down (deterioration is real signal)", () => {
    const improving = computeSupportQuality(inputs({ ssaDelta: 1.0 }));
    const declining = computeSupportQuality(inputs({ ssaDelta: -1.0 }));
    expect(improving.score - declining.score).toBeGreaterThan(15);
  });

  it("a 'Strong' or 'Excellent' band returns a reason that mentions the SSA delta", () => {
    const r = computeSupportQuality(inputs({ ssaDelta: 1.2 }));
    expect(r.band).toMatch(/Strong|Excellent/);
    expect(r.reason).toMatch(/SSA/);
  });

  it("'AtRisk' reason advises pausing + diagnosing before more visits", () => {
    const r = computeSupportQuality(inputs({
      ssaDelta:           -0.5,
      followUpCompletionPct: 20,
      schoolFeedbackScore:   20,
      evidenceCompletenessPct: 20,
      verificationRatePct:    20,
      debriefQualityScore:    20,
      trainingPrePostDeltaPct: 20,
      observationDeltaPct:     20,
      literacyDeltaPct:        20,
      repeatSupportLandedPct:  20,
    }));
    expect(r.band).toBe("AtRisk");
    expect(r.reason).toMatch(/pause|diagnose/i);
  });
});

describe("computeSupportQuality — weights are tunable per country", () => {
  it("setting all weights to zero floors the score at 0", () => {
    const r = computeSupportQuality(inputs(), {
      evidenceCompleteness: 0, debriefQuality: 0, followUpCompletion: 0,
      schoolFeedback: 0, ssaImprovement: 0, trainingPrePost: 0,
      observationDelta: 0, literacyDelta: 0, verificationRate: 0,
      repeatSupportLanded: 0,
    });
    expect(r.score).toBe(0);
  });
});
