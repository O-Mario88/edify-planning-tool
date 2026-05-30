// Canonical helper. The single source of truth for "does this activity
// count toward target completion?" Only Impact-Assessment-verified work
// counts. Submitted-for-Verification, Salesforce-ID-Pending, Completed
// (but unverified), Returned, Planned, and Draft do NOT count.
//
// Use this anywhere you reduce activities to a "verified count" — My
// Targets, Team Targets, Leaderboard, Core School progress, Coverage,
// dashboard KPIs.

import type { PlannedActivity } from "@/lib/cceo-my-targets-engine";

export function countsTowardTarget(a: Pick<PlannedActivity, "status">): boolean {
  return a.status === "Verified";
}

// For "this activity is done from the field's perspective even though
// it still needs SF / IA verification" — use only for *progress signals*
// (e.g. "X done today"), NEVER for target completion.
export function isFieldComplete(a: Pick<PlannedActivity, "status">): boolean {
  return (
    a.status === "Verified" ||
    a.status === "Submitted for Verification" ||
    a.status === "Salesforce ID Pending" ||
    a.status === "Completed"
  );
}
