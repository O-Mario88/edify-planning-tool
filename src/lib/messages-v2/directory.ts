// User directory — the registered-users list the composer's "To"
// picker reads from. Each entry mirrors the spec's user identity:
// userId + name + email + role + organisation + scope. Email is the
// internal messaging identity.
//
// Today this is a hand-curated mock that pairs with `lib/auth.ts`
// demo users. Phase 2 swaps it for a real `users` table query.

import type { EdifyRole } from "@/lib/auth-public";
import type { MessageSenderRole } from "./types";

export type DirectoryUser = {
  userId:       string;
  name:         string;
  email:        string;
  role:         EdifyRole;
  /** Display-role shown in chips and headers. */
  displayRole:  MessageSenderRole;
  initials:     string;
  organization?: string;
  /** Scope label — country / region / cluster / partner-org. Used by
   *  the recipient-picker to filter and to show "where" the recipient
   *  sits. */
  scope:        string;
};

export const DIRECTORY: DirectoryUser[] = [
  // ─── Edify staff ───
  { userId: "STF-SO-007", name: "Sarah Okello",   email: "sarah.okello@edify.org",   role: "CountryDirector",    displayRole: "Country Director", initials: "SO", scope: "Uganda · Country Director" },
  { userId: "STF-EW-003", name: "Esther Wanjiru", email: "esther.wanjiru@edify.org", role: "RVP",                displayRole: "RVP",              initials: "EW", scope: "East Africa · Regional VP" },
  { userId: "STF-AW-019", name: "Anne Wairimu",   email: "anne.wairimu@edify.org",   role: "HumanResource",      displayRole: "HR",               initials: "AW", scope: "Uganda · People & Performance" },
  { userId: "STF-GA-042", name: "Grace Alimo",    email: "grace.alimo@edify.org",    role: "ImpactAssessment",   displayRole: "M&E",              initials: "GA", scope: "Uganda · M&E / Impact" },
  { userId: "STF-MT-006", name: "Moses Tindi",    email: "moses.tindi@edify.org",    role: "ProgramAccountant",  displayRole: "Accountant",       initials: "MT", scope: "Uganda · Finance" },
  { userId: "STF-DM-001", name: "Daniel Mwangi",  email: "daniel.mwangi@edify.org",  role: "CountryProgramLead", displayRole: "Program Lead",     initials: "DM", scope: "Uganda · Central Region PL" },
  { userId: "STF-PC-001", name: "Paul Chinyama",  email: "paul.chinyama@edify.org",  role: "CCEO",               displayRole: "CCEO",             initials: "PC", scope: "Mukono cluster · CCEO" },
  { userId: "STF-SN-101", name: "Sarah Nanyongo", email: "sarah.nanyongo@edify.org", role: "CCEO",               displayRole: "CCEO",             initials: "SN", scope: "Kayunga cluster · CCEO" },
  { userId: "STF-IM-005", name: "Irene Mutebi",   email: "irene.mutebi@edify.org",   role: "CCEO",               displayRole: "CCEO",             initials: "IM", scope: "Mukono cluster · CCEO" },

  // ─── Partner organisation users ───
  { userId: "PSF-SK-001", name: "Sarah Kanyi",    email: "sarah.kanyi@ltu.org",      role: "PartnerAdmin",        displayRole: "Partner",          initials: "SK", organization: "Bright Future Education Partners", scope: "Mukono + Kayunga · Partner Admin" },
  { userId: "PSF-AO-002", name: "Abel Opio",      email: "abel.opio@ltu.org",        role: "PartnerFieldOfficer", displayRole: "Partner",          initials: "AO", organization: "Bright Future Education Partners", scope: "Mukono + Kayunga · Field Officer" },
  { userId: "PSF-LD-001", name: "LTU Donor",      email: "donor@ltu-funder.org",     role: "PartnerViewer",       displayRole: "Partner",          initials: "LD", organization: "LTU Foundation",                   scope: "LTU Foundation · Viewer" },
];

export function userByEmail(email: string): DirectoryUser | undefined {
  return DIRECTORY.find((u) => u.email.toLowerCase() === email.toLowerCase());
}

export function userById(userId: string): DirectoryUser | undefined {
  return DIRECTORY.find((u) => u.userId === userId);
}

// Role-aware recipient picker. The spec's section 5 rule set:
// CCEO can message PL, Partner, IA, CD. PL can message CCEO/Partner/
// IA/CD/HR/Accountant. Partner can message CCEO+PL+(CD)+(IA). CD can
// message everyone in country scope. HR can message CCEO/PL/CD/staff.
// Accountant can message CCEO/PL/Partner/CD/Finance peers. IA can
// message CCEO/PL/Partner/CD/Evidence peers.
//
// This is intentionally permissive at the demo layer — production
// would add per-cluster + per-partner-org scope filtering.
// Per spec section 6 + 7. Key rules:
//   • HR cannot message partners (HR doesn't work with partners).
//   • RVP cannot message partners (RVP works through CDs/PLs).
//   • Partners can only message users connected to their assigned
//     scope — CCEO/PL under their org, CD if allowed, IA on evidence.
//   • CD can reach everyone in country scope including partners.
const ALLOWED_BY_SENDER: Record<EdifyRole, EdifyRole[]> = {
  CCEO:               ["CountryProgramLead", "PartnerAdmin", "PartnerFieldOfficer", "ImpactAssessment", "CountryDirector", "ProgramAccountant", "ProjectCoordinator"],
  CountryProgramLead: ["CCEO", "PartnerAdmin", "PartnerFieldOfficer", "ImpactAssessment", "CountryDirector", "HumanResource", "ProgramAccountant", "ProjectCoordinator"],
  PartnerAdmin:        ["CCEO", "CountryProgramLead", "CountryDirector", "ImpactAssessment", "ProjectCoordinator"],
  PartnerFieldOfficer: ["CCEO", "CountryProgramLead", "CountryDirector", "ImpactAssessment", "ProjectCoordinator"],
  PartnerViewer:       ["CCEO", "CountryProgramLead"],
  CountryDirector:    ["CCEO", "CountryProgramLead", "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "HumanResource", "ProgramAccountant", "ImpactAssessment", "RVP", "ProjectCoordinator"],
  HumanResource:      ["CCEO", "CountryProgramLead", "CountryDirector", "ProgramAccountant", "ImpactAssessment"], // ← NO partners
  ProgramAccountant:  ["CCEO", "CountryProgramLead", "PartnerAdmin", "PartnerFieldOfficer", "CountryDirector", "ProjectCoordinator"],
  ImpactAssessment:   ["CCEO", "CountryProgramLead", "PartnerAdmin", "PartnerFieldOfficer", "CountryDirector", "ProjectCoordinator"],
  RVP:                ["CountryDirector", "CountryProgramLead", "HumanResource", "ProgramAccountant", "ImpactAssessment"], // ← NO partners, NO direct CCEO
  // Project Coordinator coordinates delivery across staff + partners.
  ProjectCoordinator: ["CCEO", "CountryProgramLead", "CountryDirector", "PartnerAdmin", "PartnerFieldOfficer", "ImpactAssessment", "ProgramAccountant"],
  Admin:              ["CCEO", "CountryProgramLead", "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "CountryDirector", "HumanResource", "ProgramAccountant", "ImpactAssessment", "RVP", "Admin", "ProjectCoordinator"],
};

export function recipientsForSender(senderRole: EdifyRole): DirectoryUser[] {
  const allowed = new Set(ALLOWED_BY_SENDER[senderRole] ?? []);
  return DIRECTORY.filter((u) => allowed.has(u.role));
}

export function searchDirectory(users: DirectoryUser[], query: string): DirectoryUser[] {
  const q = query.trim().toLowerCase();
  if (!q) return users;
  return users.filter((u) =>
    u.name.toLowerCase().includes(q) ||
    u.email.toLowerCase().includes(q) ||
    u.displayRole.toLowerCase().includes(q) ||
    (u.organization?.toLowerCase().includes(q) ?? false) ||
    u.scope.toLowerCase().includes(q),
  );
}
