// Portfolio self-verification engine.
//
// Rule: every staff (CCEO and Program Lead) must self-verify at least 10% of
// the Client schools in their portfolio each FY cycle. This module owns the
// math — denominator (portfolio size), target (ceil 10%), achieved, %, status,
// and pace — so every dashboard + the analytics engine read one definition.
// Pure & client-safe (no server-only, no mock imports).

import { computePeriodTarget } from "@/lib/targets/period-target";

/** The org-wide quota: 10% of portfolio Client schools per cycle. */
export const CLIENT_SSA_VERIFICATION_RATE = 0.1;

export type SelfVerificationStatus = "pending" | "self_verified";

/** One per (staff, school, FY) self-verification record — flips pending → self_verified. */
export type SchoolSelfVerification = {
  schoolId: string;
  staffId: string;
  fy: string; // "2026"
  status: SelfVerificationStatus;
  verifiedAt?: string;
  verifiedBy?: string; // staffId
};

export type ClientVerificationBadge = "Met" | "On Track" | "At Risk" | "Behind";

/** Per-staff progress row — the contract ClientVerificationCard consumes. */
export type ClientVerificationProgress = {
  staffId: string;
  staffName: string;
  role: string;
  assignedClients: number; // portfolio size (denominator)
  target: number; // ceil(10% of assignedClients)
  verified: number; // schools self-verified this cycle
  pct: number; // verified / target * 100
  status: ClientVerificationBadge;
  // Additive, time-aware pace (from computePeriodTarget) — optional so existing
  // consumers keep type-checking.
  paceStatus?: string;
  expectedCumulative?: number;
  gapToExpected?: number;
};

export type ClientVerificationRollup = {
  totalVerified: number;
  totalTarget: number;
  totalAssignedClients: number;
  pct: number;
  met: number;
  onTrack: number;
  atRisk: number;
  behind: number;
};

/** Quota for a portfolio of `size` Client schools — round UP (562 → 57). */
export function portfolioTarget(size: number): number {
  return Math.ceil(CLIENT_SSA_VERIFICATION_RATE * Math.max(0, size));
}

/** Badge thresholds (mirror the card's captions): 100 Met / 70 On Track / 40 At Risk. */
export function verificationStatusFor(pct: number): ClientVerificationBadge {
  if (pct >= 100) return "Met";
  if (pct >= 70) return "On Track";
  if (pct >= 40) return "At Risk";
  return "Behind";
}

export type StaffPortfolio = {
  staffId: string;
  staffName: string;
  role: string;
  portfolioSize: number;
  verified: number;
};

export type ProgressOpts = { fy?: string; selectedQuarter?: string; now?: string };

/** Compute one staff's verification progress (+ optional time-aware pace). */
export function progressFor(p: StaffPortfolio, opts?: ProgressOpts): ClientVerificationProgress {
  const target = portfolioTarget(p.portfolioSize);
  const pct = target > 0 ? Math.round((p.verified / target) * 100) : 0;
  const row: ClientVerificationProgress = {
    staffId: p.staffId,
    staffName: p.staffName,
    role: p.role,
    assignedClients: p.portfolioSize,
    target,
    verified: p.verified,
    pct,
    status: verificationStatusFor(pct),
  };
  if (opts?.fy) {
    const pt = computePeriodTarget({
      fyTarget: target,
      selectedFy: opts.fy,
      selectedQuarter: opts.selectedQuarter,
      achieved: p.verified,
      now: opts.now,
    });
    row.paceStatus = pt.paceStatus;
    row.expectedCumulative = pt.expectedCumulative;
    row.gapToExpected = pt.gapToExpected;
  }
  return row;
}

export function computePortfolioVerification(portfolios: StaffPortfolio[], opts?: ProgressOpts): ClientVerificationProgress[] {
  return portfolios.map((p) => progressFor(p, opts));
}

/** Fallback row for a staff not in the roster (uses the documented 560 FY size). */
export function getClientVerificationDefault(staffId: string, staffName = "You"): ClientVerificationProgress {
  return progressFor({ staffId, staffName, role: "CCEO", portfolioSize: 560, verified: 31 });
}

export function rollupPortfolioVerification(rows: ClientVerificationProgress[]): ClientVerificationRollup {
  const totalVerified = rows.reduce((s, r) => s + r.verified, 0);
  const totalTarget = rows.reduce((s, r) => s + r.target, 0);
  const totalAssignedClients = rows.reduce((s, r) => s + r.assignedClients, 0);
  return {
    totalVerified,
    totalTarget,
    totalAssignedClients,
    pct: totalTarget > 0 ? Math.round((totalVerified / totalTarget) * 100) : 0,
    met: rows.filter((r) => r.status === "Met").length,
    onTrack: rows.filter((r) => r.status === "On Track").length,
    atRisk: rows.filter((r) => r.status === "At Risk").length,
    behind: rows.filter((r) => r.status === "Behind").length,
  };
}

// Stable hash for deterministic 10% sampling — which schools form the quota.
function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Deterministic 10% sample of school ids for a staff (reproducible across renders). */
export function deterministicSample(schoolIds: string[], size: number, salt = ""): string[] {
  return schoolIds
    .slice()
    .sort((a, b) => hash(a + salt) - hash(b + salt))
    .slice(0, Math.max(0, Math.min(size, schoolIds.length)));
}
