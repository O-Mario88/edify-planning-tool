"use server";

// Portfolio self-verification — server action.
//
// The workflow step behind "every CCEO / Program Lead self-verifies 10% of
// their Client schools each FY": marking one portfolio school self-verified
// flips its record pending → self_verified and advances the staff's quota.
// Mirrors the universal action pattern (role guard → mutate → audit → revalidate).

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { emitAudit } from "./audit";
import { recordSelfVerification, isPortfolioStaff, PORTFOLIO_FY } from "@/lib/verification/portfolio-verification-mock";

export type PortfolioVerificationResult =
  | { ok: true; verified: number; target: number; status: string }
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "NOT_IN_PORTFOLIO" };

// Only staff who hold a portfolio self-verify their own schools.
const VERIFIER_ROLES = new Set(["CCEO", "CountryProgramLead", "Admin"]);

export async function markSchoolSelfVerified(input: {
  schoolId: string;
  fy?: string;
}): Promise<PortfolioVerificationResult> {
  const user = await getCurrentUser();
  if (!VERIFIER_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!isPortfolioStaff(user.staffId)) return { ok: false, reason: "NOT_IN_PORTFOLIO" };

  const fy = input.fy ?? PORTFOLIO_FY;
  const row = recordSelfVerification(user.staffId);
  if (!row) return { ok: false, reason: "NOT_IN_PORTFOLIO" };

  emitAudit({
    action: "portfolioVerification.selfVerified",
    subjectKind: "School",
    subjectId: input.schoolId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { fy, verified: row.verified, target: row.target, status: row.status },
  });

  // Surfaces that track the quota.
  revalidatePath("/dashboards/cceo");
  revalidatePath("/dashboards/cpl");
  revalidatePath("/dashboards/director");
  revalidatePath("/analytics");
  revalidatePath(`/staff/${user.staffId}`);

  return { ok: true, verified: row.verified, target: row.target, status: row.status };
}
