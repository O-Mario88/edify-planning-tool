// Canonical mapping from full internal status strings to short
// pill-friendly labels + tooltip-grade full text.
//
// Why this exists: status strings like "Submitted for Verification",
// "Salesforce ID Pending", "Pending Director" are used as enum keys
// and as type discriminators across the codebase. Renaming them
// everywhere would be invasive. Instead, every pill renders the
// short label here and exposes the long form via `title` for
// accessibility / hover detail.
//
// Rule: NO pill should display more than ~12 characters. Long form
// is tooltip-only.

const SHORT: Record<string, string> = {
  // Activity lifecycle
  "Planned":                    "Planned",
  "Ready":                      "Ready",
  "In Progress":                "In Progress",
  "Completed":                  "Completed",
  "Salesforce ID Pending":      "SF pending",
  "Submitted for Verification": "Awaiting verify",
  "Verified":                   "Verified",
  "Returned":                   "Returned",
  "Overdue":                    "Overdue",

  // Fund-request lifecycle
  "Pending Accountant":         "With Acct",
  "Pending Director":           "With CD",
  "Pending RVP":                "With RVP",
  "Disbursed":                  "Disbursed",

  // Monthly approval lifecycle
  "Draft":                       "Draft",
  "Submitted to Program Lead":   "With PL",
  "Returned by Program Lead":    "Returned by PL",
  "Approved by Program Lead":    "PL approved",
  "Submitted to Country Director": "With CD",
  "Returned by Country Director":  "Returned by CD",
  "Amended by Country Director":   "CD amended",
  "Approved by Country Director":  "CD approved",
  "Submitted to RVP":              "With RVP",
  "Returned by RVP":               "Returned by RVP",
  "Amended by RVP":                "RVP amended",
  "Approved by RVP":               "RVP approved",
  "Final Approved":                "Final approved",
  "Active Funding Plan":           "Active",
  "Closed":                        "Closed",

  // Weekly report lifecycle
  "Generated":                "Generated",
  "Ready for CD Review":      "With CD",
  "Reviewed by CD":           "CD reviewed",
  "Shared with RVP":          "With RVP",
  "Submitted to CD":          "With CD",
  "Returned for Clarification": "Returned",
};

const FULL: Record<string, string> = {
  "Salesforce ID Pending":      "Salesforce ID pending — capture the Salesforce record ID to move to verification.",
  "Submitted for Verification": "Submitted for Impact Assessment verification.",
  "Verified":                   "Verified by Impact Assessment.",
  "Pending Accountant":         "Awaiting Program Accountant review.",
  "Pending Director":           "Awaiting Country Director review.",
  "Pending RVP":                "Awaiting Regional Vice President final approval.",
  "Submitted to Program Lead":  "Submitted to Program Lead for plan + budget review.",
  "Approved by Program Lead":   "Program Lead has approved; submitted onward to Country Director.",
  "Submitted to Country Director": "With Country Director for budget review.",
  "Approved by Country Director":  "Country Director has approved; submitted onward to RVP.",
  "Amended by Country Director":   "Country Director has amended the requested budget.",
  "Submitted to RVP":              "With RVP for final approval.",
  "Approved by RVP":               "RVP has approved the funding plan.",
  "Final Approved":                "Final approved — pending activation as a funding plan.",
  "Active Funding Plan":           "Active funding plan — accountant may disburse.",
  "Returned by Program Lead":      "Returned by Program Lead with notes.",
  "Returned by Country Director":  "Returned by Country Director with notes.",
  "Returned by RVP":               "Returned by RVP with notes.",
};

export function shortStatusLabel(status: string): string {
  return SHORT[status] ?? status;
}

export function fullStatusLabel(status: string): string {
  return FULL[status] ?? status;
}
