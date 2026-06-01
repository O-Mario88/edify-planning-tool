// Portfolio self-verification — mock store.
//
// Roster mirrors coverage-mock's per-CCEO portfolio sizes (assignedSchools) plus
// representative Program Leads (PL portfolio ≈ schools visited). Verified counts
// are seeded to span all four statuses. Client-safe (no server-only); the store
// is mutable so the mark-verified server action increments in mock mode.

import {
  computePortfolioVerification,
  getClientVerificationDefault,
  progressFor,
  type StaffPortfolio,
  type ClientVerificationProgress,
} from "./portfolio-verification";

export const PORTFOLIO_FY = "2026";

// Mutable roster. CCEO sizes mirror coverage-mock cceoCoverageRows.assignedSchools;
// PL sizes use the schools-visited proxy (PLs own no school list).
const PORTFOLIOS: StaffPortfolio[] = [
  { staffId: "STF-DM-014", staffName: "Daniel Mwangi",  role: "CCEO",         portfolioSize: 562, verified: 57 },
  { staffId: "STF-GN-007", staffName: "Grace Njeri",    role: "CCEO",         portfolioSize: 560, verified: 48 },
  { staffId: "STF-PO-008", staffName: "Peter Ochieng",  role: "CCEO",         portfolioSize: 558, verified: 42 },
  { staffId: "STF-SN-009", staffName: "Sarah Namutebi", role: "CCEO",         portfolioSize: 560, verified: 31 },
  { staffId: "STF-BO-005", staffName: "Brian Okello",   role: "CCEO",         portfolioSize: 565, verified: 22 },
  { staffId: "STF-AD-021", staffName: "Aisha Dar",      role: "CCEO",         portfolioSize: 561, verified: 57 },
  { staffId: "STF-PM-031", staffName: "Purity Muthoni", role: "CCEO",         portfolioSize: 564, verified: 40 },
  { staffId: "STF-EN-012", staffName: "Esther Naluwu",  role: "CCEO",         portfolioSize: 560, verified: 18 },
  { staffId: "STF-PL-101", staffName: "Joan Akello",    role: "Program Lead", portfolioSize: 168, verified: 12 },
  { staffId: "STF-PL-102", staffName: "Robert Wanyama", role: "Program Lead", portfolioSize: 140, verified: 6 },
  { staffId: "STF-PL-103", staffName: "Ruth Nabwire",   role: "Program Lead", portfolioSize: 102, verified: 11 },
];

/** Fresh progress rows (recomputed from the mutable roster). */
export function getClientVerificationProgress(opts?: { selectedQuarter?: string; now?: string }): ClientVerificationProgress[] {
  return computePortfolioVerification(PORTFOLIOS, { fy: PORTFOLIO_FY, ...opts });
}

/** Static snapshot for components that take a default rows prop. */
export const clientVerificationProgress: ClientVerificationProgress[] = getClientVerificationProgress();

/** One staff's progress; falls back to a sensible default for unknown ids. */
export function getClientVerificationFor(staffId: string): ClientVerificationProgress {
  const found = PORTFOLIOS.find((p) => p.staffId === staffId);
  if (found) return progressFor(found, { fy: PORTFOLIO_FY });
  return getClientVerificationDefault(staffId);
}

/** Increment a staff's self-verified count (mock-mode mutation for the action). */
export function recordSelfVerification(staffId: string): ClientVerificationProgress | null {
  const p = PORTFOLIOS.find((x) => x.staffId === staffId);
  if (!p) return null;
  if (p.verified < p.portfolioSize) p.verified += 1;
  return progressFor(p, { fy: PORTFOLIO_FY });
}

/** Roster ids — used by the action's ownership guard. */
export function isPortfolioStaff(staffId: string): boolean {
  return PORTFOLIOS.some((p) => p.staffId === staffId);
}
