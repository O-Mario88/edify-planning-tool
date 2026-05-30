// Focus-mode composers — pure functions that translate the
// role-action-engine's ActionItem[] into FocusModeView props.
//
// Lives in its own non-client module so the server page can call them
// during SSR (the FocusModeView component itself is "use client" for
// useReducedMotion + motion variants).

import type { ActionItem } from "@/lib/actions/action-types";

// ────────── Public types ──────────

export type FocusStep = {
  key: string;
  label: string;
  detail: string;
  done: boolean;
  cta: { label: string; href: string };
  icon: "compass" | "camera" | "file" | "upload" | "check" | "users" | "mapPin" | "clipboardCheck";
};

export type FocusPrimaryStop = {
  schoolName: string;
  districtName?: string;
  purpose: string;
  distanceLabel?: string;
  /// Partner-only: the list of evidence items the field officer must
  /// capture during this activity. Surfaced above the steps so the
  /// partner knows what to gather BEFORE walking into the school.
  requiredEvidence?: string[];
  startCta: { label: string; href: string };
};

export type FocusNextUp = { schoolName: string; whenLabel: string; href: string };

export type CceoFocusProps = {
  greeting: string;
  primaryStop: FocusPrimaryStop;
  steps: FocusStep[];
  nextUp?: FocusNextUp;
};

export type PartnerFocusProps = {
  greeting: string;
  primaryStop: FocusPrimaryStop;
  steps: FocusStep[];
};

// ────────── Composer: CCEO ──────────

export function cceoFocusFromActions(name: string, items: ActionItem[]): CceoFocusProps {
  const firstName = name.split(" ")[0];
  const visit     = items.find((i) => i.category === "FieldVisit");
  const evidence  = items.find((i) => i.category === "EvidenceUpload");
  const debrief   = items.find((i) => i.category === "Debrief");
  const fund      = items.find((i) => i.category === "FundApproval");
  const nextVisit = items.filter((i) => i.category === "FieldVisit").slice(1)[0];

  const primaryStop: FocusPrimaryStop = {
    schoolName: visit?.affectedEntity.label ?? "No school assigned today",
    purpose:    visit?.description           ?? "Open the planning tool to schedule today's stops.",
    distanceLabel: undefined,
    startCta: {
      label: visit ? "Start visit" : "Open plan",
      href:  visit?.primaryAction.href ?? "/my-plan",
    },
  };

  const steps: FocusStep[] = ([
    visit ? {
      key: "visit", label: "Confirm arrival",
      detail: "Tap once you've reached the school.",
      done: visit.status === "Completed",
      cta: { label: visit.status === "Completed" ? "Arrived" : "Arrive", href: visit.primaryAction.href ?? "/route" },
      icon: "mapPin",
    } : null,
    evidence ? {
      key: "evidence", label: "Upload Evidence",
      detail: evidence.description,
      done: evidence.status === "Completed",
      cta: { label: evidence.status === "Completed" ? "Uploaded" : "Upload", href: evidence.primaryAction.href ?? "/data-intake" },
      icon: "camera",
    } : null,
    debrief ? {
      key: "debrief", label: "Submit today's debrief",
      detail: "Two lines on what you saw is enough.",
      done: debrief.status === "Completed",
      cta: { label: debrief.status === "Completed" ? "Submitted" : "Write", href: debrief.primaryAction.href ?? "/today" },
      icon: "file",
    } : null,
    fund ? {
      key: "fund", label: "Confirm funds",
      detail: "Submit week's fund slip + receipts.",
      done: fund.status === "Completed",
      cta: { label: fund.status === "Completed" ? "Submitted" : "Submit", href: fund.primaryAction.href ?? "/weekly-funds" },
      icon: "clipboardCheck",
    } : null,
  ] as (FocusStep | null)[]).filter((s): s is FocusStep => s !== null);

  const nextUp = nextVisit ? {
    schoolName: nextVisit.affectedEntity.label,
    whenLabel: nextVisit.dueDate ? humaniseDue(nextVisit.dueDate) : "Next on your route",
    href: nextVisit.primaryAction.href ?? "/route",
  } : undefined;

  return {
    greeting: `${greetingForHour()}, ${firstName}.`,
    primaryStop, steps, nextUp,
  };
}

// ────────── Composer: Partner ──────────

export function partnerFocusFromActions(name: string, items: ActionItem[]): PartnerFocusProps {
  const firstName  = name.split(" ")[0];
  const primary    = items.find((i) => i.category === "FieldVisit");
  const evidence   = items.find((i) => i.category === "EvidenceUpload");
  const correction = items.find((i) => i.approvalSafety === "NeedsReview" && i.category === "DataVerification");

  const steps: FocusStep[] = ([
    primary ? {
      key: "attendance", label: "Capture attendance",
      detail: "Tap once participants are signed in.",
      done: false,
      cta: { label: "Capture", href: primary.primaryAction.href ?? "/dashboards/partner" },
      icon: "users",
    } : null,
    evidence ? {
      key: "evidence", label: "Upload Evidence",
      detail: evidence.description,
      done: false,
      cta: { label: "Upload", href: evidence.primaryAction.href ?? "/dashboards/partner" },
      icon: "upload",
    } : null,
    {
      key: "report", label: "Submit training report",
      detail: "M&E can verify once the report is in.",
      done: false,
      cta: { label: "Submit", href: "/dashboards/partner" },
      icon: "file",
    },
    correction ? {
      key: "correction", label: "Fix returned items",
      detail: correction.description,
      done: false,
      cta: { label: "Fix", href: correction.primaryAction.href ?? "/dashboards/partner" },
      icon: "check",
    } : null,
  ] as (FocusStep | null)[]).filter((s): s is FocusStep => s !== null);

  // Required evidence hint — surfaces what the partner must capture
  // BEFORE walking into the school, so they're not missing anything.
  // Derived from activity category; production swaps for the actual
  // contract-defined evidence requirements.
  const requiredEvidence = primary
    ? deriveRequiredEvidence(primary.category)
    : undefined;

  return {
    greeting: `${greetingForHour()}, ${firstName}.`,
    primaryStop: {
      schoolName: primary?.affectedEntity.label ?? "No activity assigned today",
      purpose:    primary?.description ?? "Open the partner dashboard to see scheduled work.",
      requiredEvidence,
      startCta: { label: "Start", href: primary?.primaryAction.href ?? "/dashboards/partner" },
    },
    steps,
  };
}

function deriveRequiredEvidence(category: ActionItem["category"]): string[] {
  switch (category) {
    case "FieldVisit":
      return ["Visit report", "School staff met", "Coaching focus", "Agreed next action"];
    case "EvidenceUpload":
      return ["Attendance sheet", "Topic covered", "Facilitator name", "Number of teachers"];
    case "DataVerification":
      return ["Corrected report", "Updated photos", "Revised debrief"];
    default:
      return ["Activity report", "Supporting documents"];
  }
}

// ────────── Helpers ──────────

function greetingForHour(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

function humaniseDue(iso: string): string {
  const due = Date.parse(iso);
  if (!Number.isFinite(due)) return "Soon";
  const diff = due - Date.now();
  const day = 24 * 60 * 60 * 1000;
  if (diff < 0) return "now";
  if (diff < day) return "later today";
  if (diff < 2 * day) return "tomorrow";
  return `in ${Math.round(diff / day)} days`;
}
