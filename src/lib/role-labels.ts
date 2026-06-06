import type { EdifyRole } from "@/lib/auth";

// Canonical human labels for EdifyRole. Two registers:
//   • VERBOSE — full descriptive labels (profile, detail views)
//   • CONCISE — short labels (sidebars, top bars, chips)
// (The accountant ReimbursementQueue keys off a DIFFERENT enum — staffRole, with
// values like ProgramLead/SpecialProjectsCoordinator — so it is intentionally
// NOT sourced from here.)

export const ROLE_LABEL_VERBOSE: Record<EdifyRole, string> = {
  CCEO: "Core Schools Officer (CCEO)",
  CountryProgramLead: "Country Program Lead",
  CountryDirector: "Country Director",
  RVP: "Regional Vice President",
  ProgramAccountant: "Program Accountant",
  ImpactAssessment: "M&E / Impact Assessment",
  HumanResource: "Human Resource",
  ProjectCoordinator: "Project Coordinator",
  Admin: "Administrator",
  PartnerAdmin: "Partner Admin",
  PartnerFieldOfficer: "Partner Field Officer",
  PartnerViewer: "Partner Viewer",
};

export const ROLE_LABEL_CONCISE: Record<EdifyRole, string> = {
  CCEO: "CCEO",
  CountryProgramLead: "Program Lead",
  CountryDirector: "Country Director",
  RVP: "Regional VP",
  ProgramAccountant: "Accountant",
  ImpactAssessment: "M&E / Impact",
  HumanResource: "Human Resource",
  ProjectCoordinator: "Project Coord",
  Admin: "Administrator",
  PartnerAdmin: "Partner Admin",
  PartnerFieldOfficer: "Partner Field Officer",
  PartnerViewer: "Partner Viewer",
};
