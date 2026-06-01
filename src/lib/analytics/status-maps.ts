// Workflow-status → pipeline-bucket mappers (the rule lives in ONE place).
//
// planned → completed → verified → donor-ready, encoding the gates:
//   • completed requires evidence complete/verified AND a valid Salesforce ID
//     (the Salesforce Completion Verification Gate).
//   • verified requires IA verification.
//   • donor-ready requires verified AND the SF record IA-verified.
// Pure & client-safe.

import type { SchoolActivityTimelineItem } from "@/lib/planning/school-activity-mock";
import { ACTIVITY_TYPE_LABEL } from "@/lib/planning/school-activity-mock";
import { salesforceKindFor } from "@/lib/salesforce-id";
import { sfRecordForActivity } from "@/lib/analytics/sources/salesforce-verification-mock";

/** Every in-scope activity is "planned" (it was at least planned). */
export function isPlanned(_item: SchoolActivityTimelineItem): boolean {
  return true;
}

/** Evidence done AND a valid Salesforce ID entered → completed (the SF gate). */
export function isCompleted(item: SchoolActivityTimelineItem): boolean {
  const evidenceOk = item.evidenceStatus === "complete" || item.evidenceStatus === "verified";
  const sf = sfRecordForActivity(item.id);
  return evidenceOk && !!sf?.isValid;
}

/** IA verification reached. */
export function isVerified(item: SchoolActivityTimelineItem): boolean {
  return item.verificationStatus === "verified" || item.verificationStatus === "counted";
}

/** Verified AND the Salesforce record IA-verified → counts for donors. */
export function isDonorReady(item: SchoolActivityTimelineItem): boolean {
  if (!isVerified(item)) return false;
  const sf = sfRecordForActivity(item.id);
  return sf?.iaVerifiedStatus === "verified";
}

/** Already paid + cleared. */
export function isPaid(item: SchoolActivityTimelineItem): boolean {
  return item.paymentStatus === "paid_cleared";
}

/** The Salesforce prefix an activity should carry (SV- visit / TS- training). */
export function expectedSfKind(item: SchoolActivityTimelineItem) {
  return salesforceKindFor(ACTIVITY_TYPE_LABEL[item.activityType]);
}
