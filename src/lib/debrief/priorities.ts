import type { DebriefPriority } from "./types";

export type PriorityOption = {
  key:      DebriefPriority;
  label:    string;
  caption:  string;
  /** Tailwind tone identifier used by the UI for chip / badge colour. */
  tone:     "slate" | "blue" | "amber" | "rose";
};

export const PRIORITIES: PriorityOption[] = [
  { key: "Normal",    label: "Normal",    caption: "General field update.",                                                    tone: "slate" },
  { key: "Important", label: "Important", caption: "Needs review this week.",                                                   tone: "blue"  },
  { key: "Urgent",    label: "Urgent",    caption: "Requires action within 24–48 hours.",                                      tone: "amber" },
  { key: "Critical",  label: "Critical",  caption: "Safety, safeguarding, serious wellbeing, school crisis, fund emergency.",  tone: "rose"  },
];

export function priorityCaption(p: DebriefPriority): string {
  return PRIORITIES.find((x) => x.key === p)?.caption ?? "";
}
