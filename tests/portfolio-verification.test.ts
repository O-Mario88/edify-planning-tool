// Portfolio self-verification engine — the 10% quota math.

import { describe, expect, it } from "vitest";
import {
  CLIENT_SSA_VERIFICATION_RATE,
  portfolioTarget,
  verificationStatusFor,
  computePortfolioVerification,
  rollupPortfolioVerification,
  deterministicSample,
  type StaffPortfolio,
} from "@/lib/verification/portfolio-verification";
import { getClientVerificationFor } from "@/lib/verification/portfolio-verification-mock";

describe("quota math", () => {
  it("rate is 10%", () => expect(CLIENT_SSA_VERIFICATION_RATE).toBe(0.1));
  it("target rounds UP (ceil) per the 8 demo CCEO sizes", () => {
    expect([562, 560, 558, 560, 565, 561, 564, 560].map(portfolioTarget)).toEqual([57, 56, 56, 56, 57, 57, 57, 56]);
    expect(portfolioTarget(0)).toBe(0);
  });
});

describe("status thresholds (Met 100 / On Track 70 / At Risk 40 / Behind)", () => {
  it("boundaries", () => {
    expect(verificationStatusFor(100)).toBe("Met");
    expect(verificationStatusFor(70)).toBe("On Track");
    expect(verificationStatusFor(69)).toBe("At Risk");
    expect(verificationStatusFor(40)).toBe("At Risk");
    expect(verificationStatusFor(39)).toBe("Behind");
  });
});

describe("computePortfolioVerification", () => {
  const portfolios: StaffPortfolio[] = [
    { staffId: "A", staffName: "Aa", role: "CCEO", portfolioSize: 560, verified: 56 }, // 100% Met
    { staffId: "B", staffName: "Bb", role: "CCEO", portfolioSize: 560, verified: 42 }, // 75% On Track
    { staffId: "C", staffName: "Cc", role: "Program Lead", portfolioSize: 100, verified: 4 }, // 40% At Risk
  ];
  const rows = computePortfolioVerification(portfolios);
  it("per-staff verified / target / pct / status", () => {
    expect(rows[0]).toMatchObject({ assignedClients: 560, target: 56, verified: 56, pct: 100, status: "Met" });
    expect(rows[1]).toMatchObject({ target: 56, verified: 42, pct: 75, status: "On Track" });
    expect(rows[2]).toMatchObject({ assignedClients: 100, target: 10, verified: 4, pct: 40, status: "At Risk" });
  });
  it("attaches time-aware pace when fy is given", () => {
    const paced = computePortfolioVerification(portfolios, { fy: "2026", selectedQuarter: "Q1", now: "2025-11-15" });
    expect(paced[0].paceStatus).toBeTruthy();
    expect(typeof paced[0].expectedCumulative).toBe("number");
  });
});

describe("rollup", () => {
  it("sums totals + buckets sum to row count", () => {
    const rows = computePortfolioVerification([
      { staffId: "A", staffName: "A", role: "CCEO", portfolioSize: 560, verified: 56 },
      { staffId: "B", staffName: "B", role: "CCEO", portfolioSize: 560, verified: 20 },
    ]);
    const r = rollupPortfolioVerification(rows);
    expect(r.totalVerified).toBe(76);
    expect(r.totalTarget).toBe(112);
    expect(r.totalAssignedClients).toBe(1120);
    expect(r.met + r.onTrack + r.atRisk + r.behind).toBe(rows.length);
  });
});

describe("deterministic sample", () => {
  const ids = ["s1", "s2", "s3", "s4", "s5"];
  it("returns min(n,len), stable, subset", () => {
    const a = deterministicSample(ids, 2);
    const b = deterministicSample(ids, 2);
    expect(a).toEqual(b);
    expect(a.length).toBe(2);
    expect(a.every((x) => ids.includes(x))).toBe(true);
    expect(deterministicSample(ids, 99).length).toBe(5);
  });
});

describe("mock getClientVerificationFor", () => {
  it("known staff resolves; unknown falls back to a default", () => {
    const known = getClientVerificationFor("STF-DM-014");
    expect(known.staffId).toBe("STF-DM-014");
    expect(known.target).toBe(57);
    const unknown = getClientVerificationFor("STF-NOPE-999");
    expect(unknown.assignedClients).toBe(560);
    expect(unknown.target).toBe(56);
  });
});
