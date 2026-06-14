import type { PillTone } from "@/components/ui/Pill";

// Display vocabulary for the Leadership Decision Engine. Kept server+client safe.

export const DECISION_TYPE_LABEL: Record<string, string> = {
  recruitment: "Recruitment",
  staff_addition: "Staff Addition",
  partner: "Partners",
  staff_hr: "Staff & HR",
  regional_investment: "Regional Investment",
};

export const DECISION_TYPE_BLURB: Record<string, string> = {
  recruitment: "Recruit more schools, or focus on current ones?",
  staff_addition: "Where do we need more field staff?",
  partner: "Renew, condition, reduce, or review partner MOUs?",
  staff_hr: "Recognize, coach, support, or improve — fairly and in context.",
  regional_investment: "Where should leadership invest next?",
};

export function riskToPill(risk: string): PillTone {
  switch (risk) {
    case "critical": return "danger";
    case "high": return "danger";
    case "medium": return "warning";
    default: return "success";
  }
}

export function confidenceToPill(level: string): PillTone {
  switch (level) {
    case "high": return "success";
    case "medium": return "info";
    case "low": return "warning";
    default: return "neutral"; // insufficient
  }
}

export function confidenceLabel(level: string, score: number): string {
  const cap = level.charAt(0).toUpperCase() + level.slice(1);
  return `${cap} confidence · ${Math.round(score)}/100`;
}

export function statusLabel(status: string): string {
  return status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function statusToPill(status: string): PillTone {
  switch (status) {
    case "accepted": return "success";
    case "accepted_with_conditions": return "info";
    case "rejected": return "danger";
    case "deferred": return "warning";
    case "under_review": return "violet";
    case "converted_to_action_plan": return "success";
    default: return "neutral"; // new
  }
}

export function toneDot(tone?: string | null): string {
  switch (tone) {
    case "red": return "bg-rose-500";
    case "amber": return "bg-amber-500";
    case "green": return "bg-emerald-500";
    default: return "bg-slate-400";
  }
}

export const REVIEW_STATUSES: { value: string; label: string }[] = [
  { value: "under_review", label: "Mark Under Review" },
  { value: "accepted", label: "Accept" },
  { value: "accepted_with_conditions", label: "Accept with Conditions" },
  { value: "rejected", label: "Reject" },
  { value: "deferred", label: "Defer" },
  { value: "converted_to_action_plan", label: "Convert to Action Plan" },
];
