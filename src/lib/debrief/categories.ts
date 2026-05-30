// Per-role category pickers + display labels.
//
// The category KEY is stable (used by routing + storage). The LABEL is
// what we show the user. Pickers are role-scoped so a CCEO doesn't see
// "Cluster Issue" (a PL concept) and a partner doesn't see "Staff
// Workload" (only PL can flag that on behalf of their team).

import type { DebriefCategory, DebriefSubmitterRole } from "./types";

export type CategoryOption = {
  key:   DebriefCategory;
  label: string;
};

const CCEO_CATEGORIES: CategoryOption[] = [
  { key: "school-support-issue",     label: "School Support Issue"     },
  { key: "workload-burnout",         label: "Workload / Burnout"       },
  { key: "travel-distance",          label: "Travel / Distance"        },
  { key: "funds-finance-delay",      label: "Funds / Finance Delay"    },
  { key: "partner-delay",            label: "Partner Delay"            },
  { key: "school-leadership-issue",  label: "School Leadership Issue"  },
  { key: "teacher-practice-issue",   label: "Teacher Practice Issue"   },
  { key: "safeguarding-safety",      label: "Safeguarding / Safety"    },
  { key: "data-evidence-issue",      label: "Data / Evidence Issue"    },
  { key: "success-story",            label: "Success Story"            },
  { key: "program-improvement-idea", label: "Program Improvement Idea" },
  { key: "urgent-escalation",        label: "Urgent Escalation"        },
];

const PL_CATEGORIES: CategoryOption[] = [
  { key: "staff-workload",           label: "Staff Workload"           },
  { key: "partner-performance",      label: "Partner Performance"      },
  { key: "planning-gap",             label: "Planning Gap"             },
  { key: "budget-funds-blocker",     label: "Budget / Funds Blocker"   },
  { key: "school-risk",              label: "School Risk"              },
  { key: "evidence-data-quality",    label: "Evidence / Data Quality"  },
  { key: "training-quality",         label: "Training Quality"         },
  { key: "cluster-issue",            label: "Cluster Issue"            },
  { key: "ssa-issue",                label: "SSA Issue"                },
  { key: "operational-risk",         label: "Operational Risk"         },
  { key: "program-improvement",      label: "Program Improvement"      },
  { key: "urgent-decision-needed",   label: "Urgent Decision Needed"   },
];

const PARTNER_CATEGORIES: CategoryOption[] = [
  { key: "school-needs-followup",    label: "School Needs Follow-Up"   },
  { key: "ssa-recommendation-issue", label: "SSA Recommendation Issue" },
  { key: "training-quality-issue",   label: "Training Quality Issue"   },
  { key: "school-leadership-issue",  label: "School Leadership Issue"  },
  { key: "teacher-practice-issue",   label: "Teacher Practice Issue"   },
  { key: "evidence-issue",           label: "Evidence Issue"           },
  { key: "schedule-delay",           label: "Schedule Delay"           },
  { key: "coordination-issue",       label: "Coordination Issue"       },
  { key: "transport-distance-issue", label: "Transport / Distance Issue" },
  { key: "partner-support-needed",   label: "Partner Support Needed"   },
  { key: "program-improvement-idea", label: "Program Improvement Idea" },
  { key: "success-story",            label: "Success Story"            },
];

export function categoriesForRole(role: DebriefSubmitterRole): CategoryOption[] {
  switch (role) {
    case "CCEO":               return CCEO_CATEGORIES;
    case "CountryProgramLead": return PL_CATEGORIES;
    case "Partner":            return PARTNER_CATEGORIES;
  }
}

// Single label lookup so review dashboards (which mix categories from
// multiple roles) can render any category key.
const ALL_LABELS: Record<DebriefCategory, string> = Object.fromEntries(
  [...CCEO_CATEGORIES, ...PL_CATEGORIES, ...PARTNER_CATEGORIES].map((c) => [c.key, c.label]),
) as Record<DebriefCategory, string>;

export function labelForCategory(key: DebriefCategory): string {
  return ALL_LABELS[key] ?? key;
}
