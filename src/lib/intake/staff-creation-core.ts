// Staff creation core — pure validation for the CD/HR "Add Staff" workflow.
//
// First step of the Staff Onboarding & Activation workflow: create the staff
// record. A staff member is NOT operational yet — creation only produces the
// account + role + supervisor; schools, primary district, and targets come
// later and the activation engine gates "Active" on all of them.
//
// Pure & client-safe: used by the drawer (inline validation) AND the server
// action (authoritative). The supervisor-role check is injected so this module
// never imports the roster.

import type { EdifyRole } from "@/lib/auth";
import { supervisorRoleFor } from "@/lib/org/supervision";

/** Roles a CD/HR can create. (RVP/CD onboarding is a higher-level concern.) */
export const CREATABLE_STAFF_ROLES: EdifyRole[] = [
  "CCEO",
  "CountryProgramLead",
  "ImpactAssessment",
  "ProgramAccountant",
  "HumanResource",
  "CountryDirector",
];

/** Field roles that must carry a geography (region + district) at creation. */
const FIELD_ROLES = new Set<EdifyRole>(["CCEO", "CountryProgramLead"]);

export type NewStaffInput = {
  name: string;
  email: string;
  role: EdifyRole | "";
  region?: string;
  district?: string;
  jobTitle?: string;
  supervisorStaffId?: string;
};

export type ValidationResult = { ok: boolean; errors: Record<string, string> };

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/**
 * Validate a new-staff submission.
 * @param existingEmails  lower-cased set of emails already in the directory.
 * @param supervisorRoleById  resolve a candidate supervisor's role (for the
 *        chain check) — injected so this stays roster-free.
 */
export function validateNewStaff(
  input: NewStaffInput,
  existingEmails: ReadonlySet<string>,
  supervisorRoleById: (staffId: string) => EdifyRole | undefined,
): ValidationResult {
  const errors: Record<string, string> = {};

  if (!input.name?.trim()) errors.name = "Full name is required.";

  const email = input.email?.trim().toLowerCase();
  if (!email) errors.email = "Registered email is required.";
  else if (!EMAIL_RE.test(email)) errors.email = "Enter a valid email address.";
  else if (existingEmails.has(email)) errors.email = "A staff member with this email already exists.";

  if (!input.role) {
    errors.role = "Role is required.";
  } else {
    const role = input.role as EdifyRole;
    if (FIELD_ROLES.has(role)) {
      if (!input.region?.trim()) errors.region = "Region is required for field roles.";
      if (!input.district?.trim()) errors.district = "District is required for field roles.";
    }
    // Supervisor: required + must match the reporting chain, unless the role
    // sits at the top (RVP/Admin have no supervisor role).
    const needed = supervisorRoleFor(role);
    if (needed) {
      if (!input.supervisorStaffId?.trim()) {
        errors.supervisorStaffId = `Assign a supervisor (a ${labelForRole(needed)}).`;
      } else {
        const supRole = supervisorRoleById(input.supervisorStaffId);
        if (supRole !== needed) {
          errors.supervisorStaffId = `Supervisor of a ${labelForRole(role)} must be a ${labelForRole(needed)}.`;
        }
      }
    }
  }

  return { ok: Object.keys(errors).length === 0, errors };
}

/** Human label for a role (e.g. "CountryProgramLead" → "Program Lead"). */
export function labelForRole(role: EdifyRole): string {
  switch (role) {
    case "CountryProgramLead": return "Program Lead";
    case "CountryDirector": return "Country Director";
    case "ImpactAssessment": return "Impact Assessment";
    case "ProgramAccountant": return "Accountant";
    case "HumanResource": return "HR";
    case "CCEO": return "CCEO";
    case "RVP": return "RVP";
    default: return role;
  }
}
