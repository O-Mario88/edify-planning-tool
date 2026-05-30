// Routing engine — pure function. Given a submitter role + categories
// + priority, return the set of reviewer roles that should see the
// debrief. The spec lays the rules out per-role; this file is the
// single source of truth so the form and the review dashboards agree
// on who sees what.

import type {
  DebriefCategory,
  DebriefPriority,
  DebriefReviewerRole,
  DebriefSubmitterRole,
} from "./types";

type CategoryRule = (cat: DebriefCategory) => DebriefReviewerRole[];

// CCEO debrief — base recipients (HR + CD), with category-driven adds
// for Finance.
const ROUTE_CCEO: CategoryRule = (cat) => {
  // Every CCEO debrief reaches HR + CD per spec.
  const base: DebriefReviewerRole[] = ["HumanResource", "CountryDirector"];
  if (cat === "funds-finance-delay")    return [...base, "ProgramAccountant"];
  if (cat === "data-evidence-issue")    return [...base, "ImpactAssessment"];
  return base;
};

// PL debrief — base HR + CD; Finance for fund blockers; IA for evidence.
const ROUTE_PL: CategoryRule = (cat) => {
  const base: DebriefReviewerRole[] = ["HumanResource", "CountryDirector"];
  if (cat === "budget-funds-blocker")   return [...base, "ProgramAccountant"];
  if (cat === "evidence-data-quality")  return [...base, "ImpactAssessment"];
  if (cat === "training-quality")       return [...base, "ImpactAssessment"];
  return base;
};

// Partner debrief — every partner debrief reaches CD + PL + CCEO; some
// categories add reviewers.
const ROUTE_PARTNER: CategoryRule = (cat) => {
  const base: DebriefReviewerRole[] = ["CountryDirector", "CountryProgramLead", "CCEO"];
  if (cat === "evidence-issue")         return [...base, "ImpactAssessment"];
  if (cat === "ssa-recommendation-issue") return [...base, "ImpactAssessment"];
  return base;
};

export function routeRecipients(
  submitter:  DebriefSubmitterRole,
  categories: DebriefCategory[],
  priority:   DebriefPriority,
): DebriefReviewerRole[] {
  const rule =
    submitter === "CCEO"               ? ROUTE_CCEO :
    submitter === "CountryProgramLead" ? ROUTE_PL :
                                          ROUTE_PARTNER;

  // Union of per-category recipients. Empty categories still get the
  // base recipients (use a single dummy call with a never-matching
  // category to surface them).
  const sink = new Set<DebriefReviewerRole>();
  if (categories.length === 0) {
    rule("school-support-issue").forEach((r) => sink.add(r));
  } else {
    categories.forEach((c) => rule(c).forEach((r) => sink.add(r)));
  }

  // Critical priority always escalates to CD + HR regardless of
  // category — safety/safeguarding/crisis can't get filtered out by a
  // category choice.
  if (priority === "Critical") {
    sink.add("CountryDirector");
    sink.add("HumanResource");
  }

  return [...sink];
}

// Human-readable label for the recipient chip ("HR", "Country Director",
// "PL", "CCEO", "Finance", "Impact").
const RECIPIENT_LABELS: Record<DebriefReviewerRole, string> = {
  HumanResource:      "HR",
  CountryDirector:    "Country Director",
  CountryProgramLead: "Program Lead",
  CCEO:               "CCEO",
  ProgramAccountant:  "Finance",
  ImpactAssessment:   "Impact",
};

export function labelForRecipient(role: DebriefReviewerRole): string {
  return RECIPIENT_LABELS[role];
}
