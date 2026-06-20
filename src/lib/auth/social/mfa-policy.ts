// MFA enforcement policy for social sign-in.
//
// Social auth proves the *provider* identity; it does NOT satisfy the app's MFA
// requirement. After a registered + allowed user passes the email gate, a
// privileged role must still complete MFA before a session is created. The
// privileged set below maps the spec's roles onto this app's EdifyRole names.

import type { EdifyRole } from "@/lib/auth-public";
import type { RegisteredUser } from "./types";

// Spec privileged roles → EdifyRole. SUPER_ADMIN + ADMIN both map to "Admin"
// (the super-admin domario@edify.org carries role "Admin").
const BASE_PRIVILEGED: ReadonlySet<EdifyRole> = new Set<EdifyRole>([
  "Admin", // SUPER_ADMIN + ADMIN
  "HumanResource", // HR
  "ProgramAccountant", // ACCOUNTANT
  "CountryDirector", // COUNTRY_DIRECTOR
  "RVP", // RVP
  "ImpactAssessment", // IMPACT_ASSESSMENT
]);

// CountryProgramLead (PROGRAM_LEAD) is privileged "if configured".
export function isPrivilegedRole(role: EdifyRole, includeProgramLead: boolean): boolean {
  if (role === "CountryProgramLead") return includeProgramLead;
  return BASE_PRIVILEGED.has(role);
}

export type MfaPolicyOptions = {
  /** Master switch — AUTH_SOCIAL_REQUIRE_MFA. */
  enforce: boolean;
  /** Treat CountryProgramLead as privileged — AUTH_SOCIAL_MFA_INCLUDE_PROGRAM_LEAD. */
  includeProgramLead: boolean;
};

/**
 * Whether this user must clear an MFA challenge after social auth before a
 * session is created. True when enforcement is on, the role is privileged, and
 * the user has not already satisfied MFA (enrolled + verified). Fail-closed:
 * an unknown enrolment state counts as NOT satisfied.
 */
export function socialMfaRequired(user: RegisteredUser, opts: MfaPolicyOptions): boolean {
  if (!opts.enforce) return false;
  if (!isPrivilegedRole(user.role, opts.includeProgramLead)) return false;
  return user.mfaEnrolled !== true;
}
