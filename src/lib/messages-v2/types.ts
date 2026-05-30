// Unified messaging — shared types.
//
// One Message shape across every role inbox (Partner, CCEO, PL, CD, HR,
// IA, Accountant, Admin) and every message origin (direct send, debrief
// route, evidence return, payment update, planning assignment, system
// notification). The detail page adapts its rendering by `category` +
// the optional `related` block.

import type { EdifyRole } from "@/lib/auth-public";

export type MessagePriority = "Normal" | "Important" | "Urgent" | "Critical";

export type MessageStatus =
  | "unread"
  | "read"
  | "acknowledged"
  | "action_required"
  | "in_progress"
  | "resolved"
  | "archived";

// Spec's 15 categories. Keys are stable; labels + icons in `categories.ts`.
export type MessageCategory =
  | "field-debrief"
  | "partner-debrief"
  | "evidence-review"
  | "correction-request"
  | "payment-update"
  | "planning-assignment"
  | "partner-scheduling"
  | "school-followup"
  | "cluster-update"
  | "ssa-update"
  | "finance"
  | "hr-support"
  | "system-notification"
  | "leadership-decision"
  | "general";

export type MessageSenderRole =
  | "CCEO"
  | "Program Lead"
  | "Country Director"
  | "RVP"
  | "M&E"
  | "HR"
  | "Accountant"
  | "Partner"
  | "Admin"
  | "System";

export type MessageAttachment = {
  id:    string;
  name:  string;
  /** Display-only hint — "PDF · 1.2 MB". Real shape uses url + mime. */
  meta?: string;
  href?: string;
};

// Adaptive context block — only the fields relevant to the message
// category are populated. The detail page chooses which to render.
export type MessageRelated = {
  schoolId?:        string;
  schoolName?:      string;
  clusterId?:       string;
  clusterName?:     string;
  activityId?:      string;
  activityType?:    string;
  partnerId?:       string;
  partnerName?:     string;
  evidenceId?:      string;
  evidenceStatus?:  string;
  paymentId?:       string;
  paymentAmount?:   string;   // pre-formatted ("UGX 350K")
  paymentStatus?:   string;
  ssaArea?:         string;
  debriefId?:       string;
  debriefCategory?: string;
  dueDate?:         string;   // pre-formatted ("Sat May 16")
};

// Spec's role-aware action set. The action bar filters by recipient
// role + message status — `actionsForMessage(msg, role)` returns the
// permitted subset.
export type MessageActionKey =
  | "reply"
  | "acknowledge"
  | "mark-done"
  | "create-followup"
  | "assign-action"
  | "view-school"
  | "view-cluster"
  | "view-activity"
  | "view-evidence"
  | "view-payment"
  | "view-debrief"
  | "correct-submission"
  | "escalate"
  | "archive"
  | "mark-unread";

// ─────────────────────────── Context ───────────────────────────
//
// Every NEW message must declare a context — what the message is
// about. Context is then locked at the thread level and inherited by
// replies. This is what keeps the inbox searchable and connected to
// operational records (schools, evidence, payments, debriefs, …).

export type MessageContextType =
  | "school"
  | "cluster"
  | "partner_activity"
  | "staff_activity"
  | "training"
  | "ssa"
  | "evidence"
  | "payment"
  | "planning_item"
  | "field_debrief"
  | "partner_debrief"
  | "hr_case"
  | "leadership_decision"
  | "regional_oversight"
  | "general_internal";

export type MessageContext = {
  type:   MessageContextType;
  /** Stable id of the related record. For `general_internal` we use a
   *  predictable sentinel like "general-internal" so search still
   *  groups them. */
  id:     string;
  /** Human label rendered in the chip + reply read-only strip, e.g.
   *  "Hope Primary School · Training · Attendance Sheet". */
  label:  string;
  /** Optional attribution fields used by the suggestion engine. The
   *  picker enriches these from the directory of operational records
   *  so `suggestedReceivers()` can reason about location + ownership
   *  without re-querying. Phase 4 replaces this with real joins. */
  district?:         string;
  region?:           string;
  /** Directory userId of the CCEO who monitors / owns this context. */
  assignedCceoId?:   string;
  /** Directory userId of the PL responsible for this context. */
  assignedPlId?:     string;
  /** Directory userId of the partner contact assigned to this context. */
  assignedPartnerId?: string;
  /** Status snapshot at send time — used by category-specific groups
   *  ("Schools not scheduled", "Evidence returned", …). */
  status?:           string;
};

// How a multi-context message was sent.
export type MessageContextMode = "single" | "bulk";

// Per-user delivery record. Separated from Message so two recipients
// of the same message can have independent read / acknowledged /
// resolved states. Mirrors the spec's MessageRecipient table.
export type MessageRecipient = {
  id:             string;
  messageId:      string;
  userId:         string;
  recipientName:  string;
  recipientEmail: string;
  recipientRole:  MessageSenderRole;
  status:         MessageStatus;
  deliveredAt:    string;
  readAt?:        string;
  acknowledgedAt?: string;
  resolvedAt?:    string;
  archivedAt?:    string;
  actionRequired: boolean;
};

export type Message = {
  id:            string;
  subject:       string;
  preview:       string;        // truncated body
  body:          string;        // full body — supports \n paragraph breaks

  // ─── Sender identity (registered user, with email-as-identity) ───
  senderId:      string;
  senderName:    string;
  senderEmail:   string;
  senderRole:    MessageSenderRole;
  senderInitials?: string;

  // ─── Threading ───
  /** Stable id of the conversation thread. The first message in a
   *  thread has threadId === id; replies share that threadId. */
  threadId:      string;
  /** When set, this message is a reply to that message. The detail
   *  page renders the full thread by filtering all messages with the
   *  same threadId in date order. */
  parentMessageId?: string;

  // ─── Recipients ───
  /** Per-user delivery records. Each registered recipient gets one. */
  recipients:    MessageRecipient[];
  /** Convenience for role-based access filtering — derived from
   *  `recipients[].recipientRole`. Kept on Message so list queries
   *  don't have to JOIN. Updated whenever recipients change. */
  recipientRoles: EdifyRole[];

  createdAt:     string;        // ISO timestamp
  updatedAt:     string;
  status:        MessageStatus; // aggregate: derived from recipients

  priority:      MessagePriority;
  category:      MessageCategory;

  /** Spec-required: every new message has at least one context.
   *  Replies inherit the parent thread's full context list. The
   *  multi-context list (`contexts`) drives bulk-message threads
   *  (e.g. "12 schools awaiting partner planning"); `context` is the
   *  primary one (always `contexts[0]`) and is kept for back-compat
   *  with the inbox + detail-header chips. */
  context:       MessageContext;
  contexts:      MessageContext[];
  /** Distinguishes single-context messages from grouped multi-context
   *  threads. Bulk-mode threads render the expandable context list in
   *  the detail page. */
  contextMode:   MessageContextMode;

  related?:      MessageRelated;
  attachments?:  MessageAttachment[];
  /** Pre-resolved primary action label, e.g. "Correct submission",
   *  "View evidence". Server-rendered so the action bar reads the
   *  same on every device without runtime category branching. */
  primaryAction?: { key: MessageActionKey; label: string; href?: string };

  /** True when the system auto-generated this message (e.g. evidence
   *  returned, payment cleared). System messages can't be replied to. */
  isSystemGenerated: boolean;

  archived?:     boolean;
  resolvedAt?:   string;
  resolvedBy?:   string;
};
