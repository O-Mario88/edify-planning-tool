// Salesforce verification records — the SVE-/TS- ID layer + IA verification.
//
// Built by iterating the activity spine so prefixes obey salesforceKindFor by
// construction (visits SVE-, trainings/cluster TS-). A couple of activities have
// NO record (the Salesforce Completion Gate blocks them) and one carries the
// WRONG prefix (invalid → excluded from verified counts). Pure & client-safe.

import { rawActivities, ACTIVITY_TYPE_LABEL } from "@/lib/planning/school-activity-mock";
import { salesforceKindFor, SF_PREFIX } from "@/lib/salesforce-id";

export type SfPrefix = string; // derived from SF_PREFIX (e.g. "SVE-" | "TS-")
export type SfIaStatus = "not_submitted" | "awaiting_review" | "verified" | "rejected";

export type SalesforceVerificationRecord = {
  activityId: string;
  schoolId: string;
  salesforceId: string;
  prefix: SfPrefix;
  /** True when the prefix matches the activity's Salesforce object kind. */
  isValid: boolean;
  iaVerifiedStatus: SfIaStatus;
  enteredBy: string;
  enteredAt: string; // ISO
};

// Activities with no Salesforce ID entered yet (gate blocks completion).
const NO_SF_ID = new Set(["ACT-NSSA1-1"]);
// Activity where the wrong prefix was entered (invalid → not counted).
const WRONG_PREFIX = new Set(["ACT-NTR3-2"]);

function iaStatusFor(verificationStatus: string): SfIaStatus {
  if (verificationStatus === "verified" || verificationStatus === "counted") return "verified";
  if (verificationStatus === "rejected") return "rejected";
  if (verificationStatus === "awaiting_review") return "awaiting_review";
  return "not_submitted";
}

export const salesforceVerificationMock: SalesforceVerificationRecord[] = rawActivities
  .filter((a) => !NO_SF_ID.has(a.id))
  .map((a, i) => {
    const kind = salesforceKindFor(ACTIVITY_TYPE_LABEL[a.activityType]); // "visit" | "training"
    const correct = SF_PREFIX[kind]; // e.g. "SVE-" | "TS-"
    const wrong = SF_PREFIX[kind === "training" ? "visit" : "training"]; // the other object's prefix
    const isWrong = WRONG_PREFIX.has(a.id);
    const prefix = isWrong ? wrong : correct;
    return {
      activityId: a.id,
      schoolId: a.schoolId,
      salesforceId: `${prefix}${String(10000 + i).padStart(5, "0")}`,
      prefix,
      isValid: !isWrong,
      iaVerifiedStatus: iaStatusFor(a.verificationStatus),
      enteredBy: a.deliveredByName,
      enteredAt: a.date,
    };
  });

const BY_ACTIVITY = new Map(salesforceVerificationMock.map((r) => [r.activityId, r]));

export function sfRecordForActivity(activityId: string): SalesforceVerificationRecord | undefined {
  return BY_ACTIVITY.get(activityId);
}
