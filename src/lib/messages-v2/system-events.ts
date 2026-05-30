// System-generated messages.
//
// When operational events fire (debrief submitted, evidence returned,
// payment cleared, partner assigned, …), the system writes a Message
// into the same inbox the rest of the app uses. The recipient set is
// pre-computed; context is always populated; `isSystemGenerated` is
// `true` so the reply box hides itself.
//
// Phase 2: this is the helper layer. Callers from server actions or
// post-write hooks invoke `emitSystemMessage(event)` and the right
// rows land in the right inboxes. Phase 4 swaps `appendMessage` for a
// real DB write — this function's shape doesn't change.

import { appendMessage } from "./mock";
import type {
  MessageCategory,
  MessageContext,
  MessagePriority,
  MessageSenderRole,
} from "./types";

// Stable system-sender identity. Real deployment uses a synthetic
// "Edify System" user with a known userId; we mirror that here.
const SYSTEM_USER = {
  userId: "SYS-EDIFY",
  role:   "System" as MessageSenderRole,
};

export type SystemMessageInput = {
  subject:    string;
  body:       string;
  category:   MessageCategory;
  priority:   MessagePriority;
  context:    MessageContext;
  /** Per-user delivery targets. Each entry gets its own
   *  MessageRecipient row with the supplied status (defaults to
   *  "action_required" for system-generated routing — actionable by
   *  construction). */
  recipients: { userId: string; status?: "unread" | "action_required" }[];
  /** Optional pre-resolved primary action label/href so the action bar
   *  reads correctly without runtime category branching. */
  primaryAction?: {
    key:   "view-evidence" | "view-payment" | "view-debrief" | "view-school" | "view-activity" | "acknowledge";
    label: string;
    href?: string;
  };
};

export function emitSystemMessage(input: SystemMessageInput) {
  return appendMessage({
    id: `SYS-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    subject:    input.subject,
    body:       input.body,
    sender:     SYSTEM_USER,
    recipients: input.recipients.map((r) => ({
      userId:         r.userId,
      status:         r.status ?? "action_required",
      actionRequired: (r.status ?? "action_required") === "action_required",
    })),
    category:   input.category,
    priority:   input.priority,
    context:    input.context,
    // Note: the `isSystemGenerated` flag is set by appendMessage's
    // caller currently; for system messages we want it true so the
    // reply box hides. Phase 4 may add a dedicated parameter.
  });
}

// ────────── Spec section 11: emit hooks for common events ──────────
//
// Thin convenience wrappers so the callsite reads like the spec.

export function emitDebriefSubmitted(args: {
  debriefId:        string;
  submittedByName:  string;
  submittedByRole:  string;
  category:         string;
  priority:         MessagePriority;
  recipientUserIds: string[];
}) {
  return emitSystemMessage({
    subject:  `${args.submittedByRole} debrief submitted · ${args.category}`,
    body:     `${args.submittedByName} just submitted a ${args.submittedByRole} debrief.\n\nCategory: ${args.category}\nPriority: ${args.priority}\n\nReview the full debrief and acknowledge so the submitter knows it's been seen.`,
    category: "field-debrief",
    priority: args.priority,
    context: {
      type:  "field_debrief",
      id:    args.debriefId,
      label: `${args.submittedByRole} field debrief · ${args.category}`,
    },
    recipients: args.recipientUserIds.map((userId) => ({ userId, status: "action_required" })),
    primaryAction: {
      key:   "view-debrief",
      label: "Review debrief",
      href:  `/debriefs/${args.debriefId}`,
    },
  });
}

export function emitEvidenceReturned(args: {
  evidenceId:   string;
  schoolName:   string;
  activityType: string;
  reason:       string;
  partnerUserIds: string[];
  cceoUserId?:  string;
}) {
  const recipients = [
    ...args.partnerUserIds.map((userId) => ({ userId, status: "action_required" as const })),
    ...(args.cceoUserId ? [{ userId: args.cceoUserId, status: "unread" as const }] : []),
  ];
  return emitSystemMessage({
    subject:  `Evidence returned · ${args.schoolName} · ${args.activityType}`,
    body:     `Evidence for ${args.activityType} at ${args.schoolName} has been returned for correction.\n\nReason: ${args.reason}\n\nFix and re-upload to unblock CCEO confirmation and partner payment.`,
    category: "correction-request",
    priority: "Important",
    context: {
      type:  "evidence",
      id:    args.evidenceId,
      label: `Evidence · ${args.schoolName} · ${args.activityType}`,
    },
    recipients,
    primaryAction: {
      key:   "view-evidence",
      label: "Correct submission",
      href:  "/partner/corrections",
    },
  });
}

/** Reschedule notification (spec section 5). Staff or partner has
 *  rescheduled an activity — recipients are pre-resolved by
 *  `reviewerPlan(actor)` in lib/reschedule/routing. */
export function emitReschedule(args: {
  activityLabel:   string;
  activityType:    string;
  schoolName?:     string;
  actorName:       string;
  actorRole:       string;
  actor:           "staff" | "partner";
  reasonLabels:    string[];
  notes?:          string;
  originalDate:    string;
  newDate:         string;
  recipientUserIds: string[];
}) {
  const subject = args.actor === "staff"
    ? "Activity rescheduled by staff"
    : "Partner activity rescheduled";
  const reasonBlock = args.reasonLabels.map((l) => `• ${l}`).join("\n");
  return emitSystemMessage({
    subject:  `${subject} · ${args.activityLabel}`,
    body:     `${args.actorName} (${args.actorRole}) just rescheduled ${args.activityType}${args.schoolName ? ` at ${args.schoolName}` : ""}.\n\nReason(s):\n${reasonBlock}${args.notes ? `\n\nNotes: ${args.notes}` : ""}\n\nOriginal: ${args.originalDate}\nNew:      ${args.newDate}`,
    category: args.actor === "staff" ? "planning-assignment" : "partner-scheduling",
    priority: "Important",
    context: {
      type:  args.actor === "staff" ? "staff_activity" : "partner_activity",
      id:    `resched:${Date.now()}`,
      label: `${args.activityLabel}${args.schoolName ? ` · ${args.schoolName}` : ""}`,
    },
    recipients: args.recipientUserIds.map((userId) => ({ userId, status: "unread" })),
    primaryAction: {
      key:   "view-activity",
      label: "View activity",
      href:  args.actor === "partner" ? "/partner/schedule" : "/my-plan",
    },
  });
}

/** Partner work returned for correction (spec section 8). */
export function emitWorkReturned(args: {
  activityLabel:  string;
  schoolName:     string;
  reason:         string;
  reviewerComment: string;
  dueDate:        string;
  partnerUserIds: string[];
}) {
  return emitSystemMessage({
    subject:  `Returned for correction · ${args.activityLabel}`,
    body:     `Your evidence for ${args.activityLabel} at ${args.schoolName} has been returned for correction.\n\nReason: ${args.reason}\n\nReviewer note: ${args.reviewerComment}\n\nDue: ${args.dueDate}`,
    category: "correction-request",
    priority: "Important",
    context: {
      type:  "evidence",
      id:    `return:${Date.now()}`,
      label: `${args.schoolName} · ${args.activityLabel} · Returned for correction`,
    },
    recipients: args.partnerUserIds.map((userId) => ({ userId, status: "action_required" })),
    primaryAction: { key: "view-evidence", label: "Correct submission", href: "/partner/corrections" },
  });
}

/** Partner work rejected (spec section 8 + 11). Severity-1: work must
 *  be redone, payment blocked. PL + CD get a copy if serious. */
export function emitWorkRejected(args: {
  activityLabel:    string;
  schoolName:       string;
  reason:           string;
  reviewerComment:  string;
  requiredAction:   string;
  partnerUserIds:   string[];
  /** Internal reviewers (CCEO + PL + CD + IA + Accountant where the
   *  rejection affects each). */
  reviewerUserIds:  string[];
}) {
  return emitSystemMessage({
    subject:  `Work rejected — action required · ${args.activityLabel}`,
    body:     `Claimed work for ${args.activityLabel} at ${args.schoolName} has been rejected.\n\nReason: ${args.reason}\n\nReviewer note: ${args.reviewerComment}\n\nRequired action: ${args.requiredAction}\n\nStatus: Rejected — Work Must Be Redone\nPayment is blocked until the work is redone and confirmed.`,
    category: "correction-request",
    priority: "Urgent",
    context: {
      type:  "partner_activity",
      id:    `reject:${Date.now()}`,
      label: `${args.schoolName} · ${args.activityLabel} · Rejected`,
    },
    recipients: [
      ...args.partnerUserIds.map((userId) => ({ userId, status: "action_required" as const })),
      ...args.reviewerUserIds.map((userId) => ({ userId, status: "unread" as const })),
    ],
    primaryAction: { key: "view-activity", label: "View activity", href: "/partner/assignments" },
  });
}

export function emitPaymentCleared(args: {
  paymentId:    string;
  partnerName:  string;
  amountLabel:  string;
  bankRef:      string;
  partnerUserIds: string[];
}) {
  return emitSystemMessage({
    subject:  `Payment cleared · ${args.amountLabel} · ${args.partnerName}`,
    body:     `Your payment of ${args.amountLabel} has cleared.\n\nBank reference: ${args.bankRef}\n\nNo action needed — keep evidence quality steady for the next batch.`,
    category: "payment-update",
    priority: "Normal",
    context: {
      type:  "payment",
      id:    args.paymentId,
      label: `Payment · ${args.partnerName} · ${args.amountLabel}`,
    },
    recipients: args.partnerUserIds.map((userId) => ({ userId, status: "unread" })),
    primaryAction: {
      key:   "view-payment",
      label: "View ledger",
      href:  "/partner/payments",
    },
  });
}
