// Portfolio self-verification records on the analytics (GAP) spine.
//
// Which reached Client schools a staff has personally self-verified this cycle —
// feeds the analytics "Self-Verification (10%)" metric. Pure & client-safe.

export const selfVerifiedSchoolIds = new Set<string>([
  "GAP-NSSA-1",
  "GAP-NV-3",
  "GAP-NTR-1",
]);

export function isSelfVerified(schoolId: string): boolean {
  return selfVerifiedSchoolIds.has(schoolId);
}
