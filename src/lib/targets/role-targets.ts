// Per-role annual FY targets — the single client-safe source.
//
// CCEO and Program Lead carry DIFFERENT annual targets; PL must never be
// measured against the CCEO number. Lives here (not coverage-mock, which is
// server-only) so client target cards can read them too.

import type { EdifyRole } from "@/lib/auth-public";

/** CCEO annual client-school visit target. */
export const CCEO_ANNUAL_TARGET = 560;

/** Program Lead annual supervisory-visit target (lower than CCEO, by design). */
export const PL_ANNUAL_TARGET = 280;

/** Annual FY target for a role. Defaults to the CCEO target for field roles
 *  without a distinct number; callers may always pass an explicit target. */
export function fyTargetForRole(role: EdifyRole | string): number {
  switch (role) {
    case "CCEO":
      return CCEO_ANNUAL_TARGET;
    case "CountryProgramLead":
      return PL_ANNUAL_TARGET;
    default:
      return CCEO_ANNUAL_TARGET;
  }
}
