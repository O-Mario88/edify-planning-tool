// Partner-work review workflow (spec section 7–11).
//
// Three distinct review outcomes — each routes the activity to a
// different next state and notifies a different set of reviewers:
//
//   • Confirm — work meets the bar; moves to "Awaiting PL Approval"
//   • Return   — evidence/report incomplete; partner corrects + resubmits
//   • Reject   — work not done / wrong work; partner must redo + resubmit
//
// The distinction matters because Return doesn't block re-doing the
// activity, while Reject does. Payment can't move forward in either
// case until resubmission is approved.

export type PartnerReviewOutcome = "confirm" | "return" | "reject";

export type PartnerReviewStatus =
  | "awaiting_review"        // Partner has submitted; CCEO hasn't decided
  | "awaiting_pl_approval"   // Confirmed by CCEO
  | "returned_for_correction"
  | "rejected_work_must_be_redone"
  | "approved_by_pl"
  | "sent_to_accountant"
  | "paid";

export type ReturnReason = {
  key:   string;
  label: string;
};

export type RejectReason = {
  key:           string;
  label:         string;
  /** Whether selecting this reason flips the severity to "serious" —
   *  CD + PL get a copy with Urgent priority. */
  serious?:      boolean;
  /** When true, the reviewer must add a free-text explanation. */
  requiresNotes?: boolean;
};

export type ReviewSubmission = {
  id:               string;
  activityId:       string;
  activityLabel:    string;
  schoolName:       string;
  reviewerUserId:   string;
  reviewerName:     string;
  outcome:          PartnerReviewOutcome;
  /** Selected reason key. For `confirm` this is undefined. */
  reasonKey?:       string;
  /** Reviewer free-text — required when reason demands it or always
   *  for reject/return per the spec. */
  reviewerComment?: string;
  /** Return only: by when the correction must land. */
  dueDate?:         string;
  /** Reject only: what the partner needs to do next. */
  requiredAction?:  string;
  createdAt:        string;
};
