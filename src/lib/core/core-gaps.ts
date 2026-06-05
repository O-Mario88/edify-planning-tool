// Core planning gap buckets (§10). Pure functions over a CorePlanCardVM — no
// store access, so this is safe to import from client components (the gap-tab
// workspace) as well as the server board. Keep server-only logic in core-board.

import type { CorePlanCardVM } from "./core-board";

export const CORE_GAP_TABS = [
  "No First Visit", "No Second Visit", "No Third Visit", "No Fourth Visit",
  "No First Training", "No Second Training", "No Third Training", "No Fourth Training",
  "Follow-Up SSA Due", "Impact Not Measured", "Champion Review",
] as const;
export type CoreGapTab = typeof CORE_GAP_TABS[number];

const VISIT_GAP: CoreGapTab[] = ["No First Visit", "No Second Visit", "No Third Visit", "No Fourth Visit"];
const TRAINING_GAP: CoreGapTab[] = ["No First Training", "No Second Training", "No Third Training", "No Fourth Training"];

/** Which gap buckets a plan currently falls into (open work only). */
export function coreCardGaps(c: CorePlanCardVM): CoreGapTab[] {
  const gaps: CoreGapTab[] = [];
  const done = (type: "visit" | "training", n: number) =>
    c.slots.some((s) => s.activityType === type && s.sequenceNumber === n && s.status === "Completed");
  for (let n = 1; n <= 4; n++) {
    if (!done("visit", n)) gaps.push(VISIT_GAP[n - 1]);
    if (!done("training", n)) gaps.push(TRAINING_GAP[n - 1]);
  }
  if (c.plan.status === "Completed Pending Follow-Up SSA" || c.plan.status === "Follow-Up SSA Scheduled") gaps.push("Follow-Up SSA Due");
  if (c.progress.readyForFollowUpSSA && !c.impact) gaps.push("Impact Not Measured");
  if (c.championStatus !== "Not Eligible" && c.championStatus !== "Verified Champion") gaps.push("Champion Review");
  return gaps;
}

/** Count of plans in each gap bucket — drives the tab badges. */
export function coreGapCounts(cards: CorePlanCardVM[]): Record<CoreGapTab, number> {
  const counts = Object.fromEntries(CORE_GAP_TABS.map((t) => [t, 0])) as Record<CoreGapTab, number>;
  for (const c of cards) for (const g of coreCardGaps(c)) counts[g] += 1;
  return counts;
}
