// Unified message store. Per-user recipient records, thread support,
// email-as-identity. Phase 2 wires real debrief / evidence / payment
// events into the same store; today this is a curated demo slice.

import { userById, type DirectoryUser } from "./directory";
import type { EdifyRole } from "@/lib/auth-public";
import type {
  Message,
  MessageContext,
  MessageRecipient,
  MessageSenderRole,
  MessageStatus,
} from "./types";

// ───────────────────── helpers ─────────────────────

function recipient(
  messageId: string,
  user: DirectoryUser,
  status: MessageStatus,
  deliveredAt: string,
  actionRequired = false,
  overrides: Partial<MessageRecipient> = {},
): MessageRecipient {
  return {
    id:             `R-${messageId}-${user.userId}`,
    messageId,
    userId:         user.userId,
    recipientName:  user.name,
    recipientEmail: user.email,
    recipientRole:  user.displayRole,
    status,
    deliveredAt,
    actionRequired,
    ...overrides,
  };
}

function recipients(messageId: string, when: string, list: { userId: string; status: MessageStatus; actionRequired?: boolean }[]): MessageRecipient[] {
  return list
    .map(({ userId, status, actionRequired }) => {
      const u = userById(userId);
      if (!u) return null;
      return recipient(messageId, u, status, when, actionRequired);
    })
    .filter((r): r is MessageRecipient => r !== null);
}

function recipientRolesFrom(recs: MessageRecipient[]): EdifyRole[] {
  // Reverse-lookup the EdifyRole for each recipient via the directory.
  const out = new Set<EdifyRole>();
  for (const r of recs) {
    const u = userById(r.userId);
    if (u) out.add(u.role);
  }
  return [...out];
}

// Build a Message with sensible defaults. Reduces boilerplate when
// authoring the demo data.
function msg(input: {
  id:        string;
  threadId?: string;
  parentMessageId?: string;
  subject:   string;
  body:      string;
  preview?:  string;
  sender:    { userId: string; role: MessageSenderRole };
  recipients: { userId: string; status: MessageStatus; actionRequired?: boolean }[];
  createdAt: string;
  updatedAt?: string;
  status:    MessageStatus;
  priority:  Message["priority"];
  category:  Message["category"];
  /** Required on every message. Pass either a single `context` or a
   *  multi-context `contexts` list (bulk messages). Replies inherit
   *  the parent's full list. */
  context?:  MessageContext;
  contexts?: MessageContext[];
  related?:  Message["related"];
  attachments?: Message["attachments"];
  primaryAction?: Message["primaryAction"];
  isSystemGenerated?: boolean;
}): Message {
  const senderUser = userById(input.sender.userId);
  if (!senderUser) throw new Error(`Unknown sender ${input.sender.userId}`);
  const recs = recipients(input.id, input.createdAt, input.recipients);
  const preview =
    input.preview ?? (input.body.replace(/\s+/g, " ").slice(0, 120) + (input.body.length > 120 ? "…" : ""));
  return {
    id:                input.id,
    threadId:          input.threadId ?? input.id,
    parentMessageId:   input.parentMessageId,
    subject:           input.subject,
    preview,
    body:              input.body,
    senderId:          senderUser.userId,
    senderName:        senderUser.name,
    senderEmail:       senderUser.email,
    senderRole:        input.sender.role,
    senderInitials:    senderUser.initials,
    recipients:        recs,
    recipientRoles:    recipientRolesFrom(recs),
    createdAt:         input.createdAt,
    updatedAt:         input.updatedAt ?? input.createdAt,
    status:            input.status,
    priority:          input.priority,
    category:          input.category,
    // Normalise inputs: a caller may pass `context` (legacy / single)
    // OR `contexts` (multi). Both end up populated on the row.
    ...(() => {
      const list = input.contexts && input.contexts.length > 0
        ? input.contexts
        : input.context
          ? [input.context]
          : [];
      if (list.length === 0) throw new Error(`Message ${input.id} is missing context`);
      return {
        context:     list[0],
        contexts:    list,
        contextMode: list.length > 1 ? "bulk" as const : "single" as const,
      };
    })(),
    related:           input.related,
    attachments:       input.attachments,
    primaryAction:     input.primaryAction,
    isSystemGenerated: input.isSystemGenerated ?? false,
  };
}

// ───────────────────── demo data ─────────────────────

export const MESSAGES: Message[] = [
  // Thread T-1: Sarah → Abel (partner) — correction request, with a reply
  msg({
    id: "M-1",
    subject: "Kireka debrief — attendance sheet unclear",
    body:
      "Hi Daniel,\n\nThe attendance sheet you uploaded for the Kireka training debrief is missing teacher names — please re-upload with names, school, date, and facilitator visible.\n\nI've returned the activity in your Corrections queue, due Sat May 16.\n\nThanks,\nSarah",
    sender: { userId: "STF-SN-101", role: "CCEO" },
    recipients: [
      { userId: "PSF-SK-001", status: "action_required", actionRequired: true },
      { userId: "PSF-AO-002", status: "action_required", actionRequired: true },
    ],
    createdAt: "2026-05-13T09:34:00+03:00",
    status: "action_required",
    priority: "Important",
    category: "correction-request",
    context: {
      type:  "evidence",
      id:    "evidence:kireka-attendance",
      label: "Kireka Primary · Training debrief · Attendance sheet",
    },
    related: {
      schoolName: "Kireka Primary School",
      activityType: "Training debrief",
      evidenceStatus: "Returned for correction",
      dueDate: "Sat May 16",
    },
    attachments: [{ id: "att-1", name: "kireka-debrief-attendance.pdf", meta: "PDF · 0.8 MB" }],
    primaryAction: { key: "correct-submission", label: "Correct submission", href: "/partner/corrections" },
  }),
  msg({
    id: "M-1R1",
    threadId: "M-1",
    parentMessageId: "M-1",
    subject: "Re: Kireka debrief — attendance sheet unclear",
    body:
      "Hi Sarah,\n\nThanks for flagging. I'll re-upload the corrected attendance sheet by Friday with all the requested fields visible.\n\nWill confirm once it's in the Corrections queue.\n\n— Abel",
    sender: { userId: "PSF-AO-002", role: "Partner" },
    recipients: [{ userId: "STF-SN-101", status: "unread" }],
    createdAt: "2026-05-13T11:08:00+03:00",
    status: "unread",
    priority: "Normal",
    category: "correction-request",
    // Inherits the parent thread's context.
    context: {
      type:  "evidence",
      id:    "evidence:kireka-attendance",
      label: "Kireka Primary · Training debrief · Attendance sheet",
    },
    related: { schoolName: "Kireka Primary School", activityType: "Training debrief" },
    primaryAction: { key: "acknowledge", label: "Acknowledge" },
  }),

  // Thread T-2: Daniel (PL) → Partner team — recognition
  msg({
    id: "M-2",
    subject: "Strong delivery this week — keep it up",
    body:
      "Just a note to say your follow-up coaching visits at Hope and Grace have shown up clean in the inbox. CCEO confirmation is moving fast and payment is on track.\n\nKeep the same evidence quality.\n\n— Daniel (PL)",
    sender: { userId: "STF-DM-001", role: "Program Lead" },
    recipients: [
      { userId: "PSF-SK-001", status: "unread" },
      { userId: "PSF-AO-002", status: "unread" },
    ],
    createdAt: "2026-05-12T16:12:00+03:00",
    status: "unread",
    priority: "Normal",
    category: "general",
    context: {
      type:  "general_internal",
      id:    "general-internal",
      label: "Partner team recognition · Hope & Grace",
    },
    related: { schoolName: "Hope & Grace (multiple)" },
    primaryAction: { key: "acknowledge", label: "Acknowledge" },
  }),

  // Thread T-3: Sarah → Partner — scheduling reminder
  msg({
    id: "M-3",
    subject: "Schedule reminder — Maple Grove coaching visit",
    body:
      "Reminder: Maple Grove (Kayunga) literacy follow-up is still unscheduled 5 days after assignment. Please add it to a delivery week so I can monitor delivery.\n\n— Sarah",
    sender: { userId: "STF-SN-101", role: "CCEO" },
    recipients: [
      { userId: "PSF-SK-001", status: "read" },
      { userId: "PSF-AO-002", status: "read" },
    ],
    createdAt: "2026-05-12T14:01:00+03:00",
    status: "read",
    priority: "Important",
    category: "partner-scheduling",
    context: {
      type:  "partner_activity",
      id:    "pa:maple-coaching",
      label: "Partner coaching · Maple Grove · Literacy follow-up",
    },
    related: { schoolName: "Maple Grove Primary", activityType: "Literacy follow-up", dueDate: "Sun May 18" },
    primaryAction: { key: "view-school", label: "Open schedule", href: "/partner/schedule" },
  }),

  // Thread T-4: Grace (M&E) → Partner — evidence verified
  msg({
    id: "M-4",
    subject: "M&E verified 4 May activities — counted in May report",
    body:
      "Quick heads-up — your Namilyango resource delivery, Eastview follow-up, Mukono Central observation, and Bright Future delivery have all been verified by M&E and will count in the May impact report.\n\n— Grace, M&E",
    sender: { userId: "STF-GA-042", role: "M&E" },
    recipients: [
      { userId: "PSF-SK-001", status: "read" },
      { userId: "PSF-AO-002", status: "read" },
    ],
    createdAt: "2026-05-11T11:45:00+03:00",
    status: "read",
    priority: "Normal",
    category: "evidence-review",
    context: {
      type:  "evidence",
      id:    "evidence:namilyango-photos",
      label: "Evidence batch · 4 schools verified · May report",
    },
    related: { schoolName: "4 schools", evidenceStatus: "Verified" },
    primaryAction: { key: "view-evidence", label: "View evidence", href: "/partner/evidence" },
  }),

  // Thread T-5: Sarah → Partner — joint visit proposal
  msg({
    id: "M-5",
    subject: "Joint visit proposal — Bbaale cluster (May 28)",
    body:
      "I'd like to join your team for the Bbaale cluster visit on May 28 — quick alignment on coaching focus areas so the partner-led work and CCEO follow-up tell one story.\n\nLet me know if 9am at Bbaale Primary works.\n\n— Sarah",
    sender: { userId: "STF-SN-101", role: "CCEO" },
    recipients: [
      { userId: "PSF-SK-001", status: "read" },
      { userId: "PSF-AO-002", status: "read" },
    ],
    createdAt: "2026-05-10T08:20:00+03:00",
    status: "read",
    priority: "Normal",
    category: "cluster-update",
    context: {
      type:  "cluster",
      id:    "cluster:bbaale",
      label: "Bbaale cluster · Joint visit · May 28",
    },
    related: { clusterName: "Bbaale cluster", dueDate: "May 28" },
    primaryAction: { key: "reply", label: "Reply" },
  }),

  // Thread T-6: Moses (Accountant) → Partner — payment cleared
  msg({
    id: "M-6",
    subject: "April payment batch cleared — UGX 5.6M",
    body:
      "The April payment batch (16 activities) has cleared. Bank ref BANK-2026-04832.\n\nMay batch is in queue — 2 ready, 5 awaiting PL approval, 3 awaiting CCEO confirmation.\n\n— Moses, Accountant",
    sender: { userId: "STF-MT-006", role: "Accountant" },
    recipients: [
      { userId: "PSF-SK-001", status: "read" },
      { userId: "PSF-AO-002", status: "read" },
    ],
    createdAt: "2026-05-09T17:55:00+03:00",
    status: "read",
    priority: "Normal",
    category: "payment-update",
    context: {
      type:  "payment",
      id:    "payment:apr-batch",
      label: "Payment · April batch · UGX 5.6M",
    },
    related: { paymentAmount: "UGX 5.6M", paymentStatus: "Cleared" },
    primaryAction: { key: "view-payment", label: "View ledger", href: "/partner/payments" },
  }),

  // Thread T-7: Daniel (PL) → CD + HR — planning gap escalation
  msg({
    id: "M-7",
    subject: "PL debrief — Bbaale cluster planning gap",
    body:
      "Daniel flagged in his Tuesday debrief that two CCEOs covering Bbaale cluster don't have Q3 plan templates. This is blocking delivery on three schools where partner support is already scheduled.\n\nRecommend pushing templates today and a one-line note to the cluster lead.\n\n— Daniel (PL)",
    sender: { userId: "STF-DM-001", role: "Program Lead" },
    recipients: [
      { userId: "STF-SO-007", status: "action_required", actionRequired: true },
      { userId: "STF-AW-019", status: "unread" },
    ],
    createdAt: "2026-05-13T07:10:00+03:00",
    status: "action_required",
    priority: "Urgent",
    category: "field-debrief",
    context: {
      type:  "field_debrief",
      id:    "fd:weekly",
      label: "PL field debrief · Bbaale cluster · Planning gap",
    },
    related: { clusterName: "Bbaale cluster", debriefCategory: "Planning Gap" },
    primaryAction: { key: "view-debrief", label: "View debrief", href: "/debriefs" },
  }),

  // Thread T-8: System → HR + CD — fairness model auto-flag
  msg({
    id: "M-8",
    subject: "Staff wellbeing flag — Purity Muthoni",
    body:
      "Fairness rule triggered: Purity is at 70% pace this month, but her portfolio is in the 95th percentile by school count and travel distance.\n\nRecommend a support conversation, not a coaching warning.\n\n— Auto-routed from CCEO field debrief",
    sender: { userId: "STF-AW-019", role: "System" }, // attributed to HR for demo; real system uses SYS-FAIR
    recipients: [
      { userId: "STF-AW-019", status: "action_required", actionRequired: true },
      { userId: "STF-SO-007", status: "unread" },
    ],
    createdAt: "2026-05-13T05:30:00+03:00",
    status: "action_required",
    priority: "Important",
    category: "hr-support",
    context: {
      type:  "hr_case",
      id:    "hr:purity-fairness",
      label: "HR case · Purity Muthoni · Fairness review",
    },
    related: { activityType: "Staff support" },
    primaryAction: { key: "create-followup", label: "Create support case" },
    isSystemGenerated: true,
  }),

  // ─────────────── Demo fill — broaden inbox coverage ───────────────
  //
  // Earlier threads heavily favour partner/CCEO context.  These add
  // realistic message volume across every other internal role so the
  // /messages page and the bell drawer always have content for the
  // demo user, regardless of which role they log in as.

  // CCEO Paul — incoming approval ping from his PL
  msg({
    id: "M-D1",
    subject: "Plan approved · Visits week of May 19",
    body:
      "Hi Paul,\n\nYour plan for the week of May 19 is approved — 4 visits, 1 cluster meeting at Maryhill, 2 SSA follow-ups. The Maryhill site materials will be at your district office by Friday.\n\nNice tight plan. Keep it moving.\n\n— Daniel",
    sender: { userId: "STF-DM-001", role: "Program Lead" },
    recipients: [{ userId: "STF-PC-001", status: "unread" }],
    createdAt: "2026-05-14T08:42:00+03:00",
    status: "unread",
    priority: "Normal",
    category: "planning-assignment",
    context: { type: "planning_item", id: "plan:pc-may19", label: "Paul's weekly plan · May 19" },
    related: { activityType: "Weekly plan approval", dueDate: "Mon May 19" },
    primaryAction: { key: "view-activity", label: "Open my plan", href: "/my-plan" },
  }),

  // CCEO Paul — system-routed reschedule alert
  msg({
    id: "M-D2",
    subject: "Kireka cluster meeting rescheduled",
    body:
      "Kireka cluster meeting moved from Thursday May 14 to Tuesday May 19 (10:00).\n\nReason: 3 of 5 cluster heads flagged a conflict with the district training week.\n\nYour route has been updated automatically. Two affected schools (Sunrise, New Dawn) re-queued for the next route run.",
    sender: { userId: "STF-DM-001", role: "System" },
    recipients: [
      { userId: "STF-PC-001", status: "read" },
      { userId: "STF-DM-001", status: "read" },
    ],
    createdAt: "2026-05-13T16:55:00+03:00",
    status: "read",
    priority: "Normal",
    category: "cluster-update",
    context: { type: "cluster", id: "cluster:kireka", label: "Kireka cluster · Reschedule" },
    related: { clusterName: "Kireka cluster" },
    primaryAction: { key: "view-cluster", label: "Open cluster", href: "/clusters" },
    isSystemGenerated: true,
  }),

  // CD Sarah — fund approval queue building up (action required)
  msg({
    id: "M-D3",
    subject: "12 plans waiting on country sign-off",
    body:
      "12 PL-approved plans are sitting in your queue, total UGX 128.8M across Central + North.  Disbursement window closes Friday 17:00 — if Central isn't cleared by Wednesday, payment pushes to next week.\n\nNo blockers flagged.  Quick approve recommended.\n\n— Moses (Accountant)",
    sender: { userId: "STF-MT-006", role: "Accountant" },
    recipients: [{ userId: "STF-SO-007", status: "action_required", actionRequired: true }],
    createdAt: "2026-05-14T09:15:00+03:00",
    status: "action_required",
    priority: "Urgent",
    category: "finance",
    context: { type: "payment", id: "payment:may-batch-2", label: "May batch 2 · Country sign-off" },
    related: { paymentAmount: "UGX 128.8M", dueDate: "Fri May 16" },
    primaryAction: { key: "view-payment", label: "Open Queue", href: "/approvals" },
  }),

  // CD Sarah — recognition note from RVP
  msg({
    id: "M-D4",
    subject: "Uganda leading on monthly target this quarter",
    body:
      "Just looked at the Q2 mid-month snapshot.  Uganda is the only country tracking above 80% target across all three program areas.\n\nWell done — and thank you for the Central + North realignment last cycle.  It's clearly paying off.\n\n— Esther",
    sender: { userId: "STF-EW-003", role: "RVP" },
    recipients: [{ userId: "STF-SO-007", status: "unread" }],
    createdAt: "2026-05-13T17:48:00+03:00",
    status: "unread",
    priority: "Normal",
    category: "leadership-decision",
    context: { type: "leadership_decision", id: "ld:uganda-q2-recognition", label: "Q2 Recognition · Uganda" },
    primaryAction: { key: "acknowledge", label: "Acknowledge" },
  }),

  // RVP Esther — donor reporting evidence gap (action required)
  msg({
    id: "M-D5",
    subject: "Donor report — 4 evidence gaps need addressing",
    body:
      "Q2 partner donor report is due May 31. Current evidence completeness is 86% — four schools (Living Word, Hope, Victory, Light of Hope) are missing post-assessment forms for the Numeracy follow-up cohort.\n\nIA flagged these for closure this week. Please confirm the plan once IA's queue is clear.\n\n— Grace (IA)",
    sender: { userId: "STF-GA-042", role: "M&E" },
    recipients: [
      { userId: "STF-EW-003", status: "action_required", actionRequired: true },
      { userId: "STF-SO-007", status: "unread" },
    ],
    createdAt: "2026-05-14T07:02:00+03:00",
    status: "action_required",
    priority: "Important",
    category: "evidence-review",
    context: { type: "evidence", id: "evidence:q2-donor-numeracy", label: "Q2 Donor report · Numeracy evidence" },
    related: { evidenceStatus: "4 schools incomplete", dueDate: "Fri May 31" },
    primaryAction: { key: "view-evidence", label: "Open evidence", href: "/dashboards/impact" },
  }),

  // IA Grace — partner just submitted SSA
  msg({
    id: "M-D6",
    subject: "Living Word — Q1 SSA assessment uploaded",
    body:
      "Living Word School uploaded their Q1 SSA assessment this morning. Roster complete, materials present, post-assessment attached.\n\nReady for your verification review whenever you can take it.\n\n— Sarah Kanyi (Bright Future)",
    sender: { userId: "PSF-SK-001", role: "Partner" },
    recipients: [{ userId: "STF-GA-042", status: "unread" }],
    createdAt: "2026-05-14T06:18:00+03:00",
    status: "unread",
    priority: "Normal",
    category: "ssa-update",
    context: { type: "ssa", id: "ssa:livingword-q1", label: "Living Word · Q1 SSA" },
    related: { schoolName: "Living Word School", ssaArea: "Q1 baseline" },
    primaryAction: { key: "view-evidence", label: "Review SSA", href: "/ssa" },
  }),

  // IA Grace — quality drift alert from CD
  msg({
    id: "M-D7",
    subject: "Fees / Budget weakest area for 5 of 10 districts",
    body:
      "May SSA snapshot just landed — Fees / Budget / Accounts is the weakest intervention nationally (5 of 10 districts flagging it as their priority gap).\n\nCan you open the SSA comparison view and tag any districts where the weakness is data-quality vs delivery? Helps us split the Q3 intervention plan cleanly.\n\n— Sarah O (CD)",
    sender: { userId: "STF-SO-007", role: "Country Director" },
    recipients: [{ userId: "STF-GA-042", status: "action_required", actionRequired: true }],
    createdAt: "2026-05-13T15:22:00+03:00",
    status: "action_required",
    priority: "Important",
    category: "ssa-update",
    context: { type: "ssa", id: "ssa:fees-budget-q2", label: "Fees & Budget · Q2 weakness analysis" },
    related: { ssaArea: "Fees · Budget · Accounts" },
    primaryAction: { key: "view-evidence", label: "Open SSA comparison", href: "/fy/ssa-comparison" },
  }),

  // CPL Daniel — staff support flag from HR
  msg({
    id: "M-D8",
    subject: "Purity Muthoni — workload review recommended",
    body:
      "Purity is tracking at 70% monthly pace, but her portfolio is the largest in your team by school count + travel distance.  The fairness rule flagged her — recommend a support conversation rather than a coaching warning.\n\nCan we set up a 15-min sync this week? I'll prep a brief.\n\n— Anne (HR)",
    sender: { userId: "STF-AW-019", role: "HR" },
    recipients: [{ userId: "STF-DM-001", status: "action_required", actionRequired: true }],
    createdAt: "2026-05-13T11:48:00+03:00",
    status: "action_required",
    priority: "Important",
    category: "hr-support",
    context: { type: "hr_case", id: "hr:purity-support", label: "Purity Muthoni · Workload support" },
    related: { activityType: "Staff support" },
    primaryAction: { key: "create-followup", label: "Schedule sync", href: "/calendar" },
  }),

  // CPL Daniel — partner payment ready
  msg({
    id: "M-D9",
    subject: "3 partner payment batches ready for PL gate",
    body:
      "Bright Future Education Partners has three payment batches cleared by CCEO confirmation and ready for your gate:\n  • Mukono · Apr Numeracy block · UGX 11.4M\n  • Kayunga · Apr Literacy block · UGX  8.2M\n  • Mukono · Apr Coaching block · UGX  4.6M\n\nAll three have full evidence (roster + materials + post-assessment).\n\nApprove from here to release the Accountant disbursement.",
    sender: { userId: "STF-MT-006", role: "Accountant" },
    recipients: [{ userId: "STF-DM-001", status: "action_required", actionRequired: true }],
    createdAt: "2026-05-13T14:30:00+03:00",
    status: "action_required",
    priority: "Important",
    category: "payment-update",
    context: { type: "payment", id: "payment:bfep-apr", label: "BFEP · April blocks (3)" },
    related: { partnerName: "Bright Future Education Partners", paymentAmount: "UGX 24.2M" },
    primaryAction: { key: "view-payment", label: "Open payment gate", href: "/approvals" },
  }),

  // Accountant Moses — fund release readiness
  msg({
    id: "M-D10",
    subject: "Mukono CCEO weekly funds — ready to disburse",
    body:
      "All 6 Mukono CCEOs have submitted weekly plans, PL-approved, with route + activity counts confirmed.  Total weekly batch:  UGX 14.6M.\n\nDisbursement window opens Wednesday.  Confirm release whenever ready.\n\n— Moses",
    sender: { userId: "STF-MT-006", role: "Accountant" },
    recipients: [{ userId: "STF-MT-006", status: "action_required", actionRequired: true }],
    createdAt: "2026-05-14T08:00:00+03:00",
    status: "action_required",
    priority: "Normal",
    category: "finance",
    context: { type: "payment", id: "payment:mukono-week-may19", label: "Mukono weekly · May 19" },
    related: { paymentAmount: "UGX 14.6M", dueDate: "Wed May 21" },
    primaryAction: { key: "view-payment", label: "Open disbursement", href: "/dashboards/accountant" },
  }),

  // Accountant Moses — reimbursement request
  msg({
    id: "M-D11",
    subject: "Reimbursement request · Paul C (CCEO · Mukono)",
    body:
      "Paul submitted a reimbursement of UGX 425,000 for fuel + lodging covering the May 6 cluster route (Maryhill loop).  Receipts attached.\n\nWithin policy.  Ready for your sign-off.",
    sender: { userId: "STF-PC-001", role: "CCEO" },
    recipients: [{ userId: "STF-MT-006", status: "unread" }],
    createdAt: "2026-05-13T13:14:00+03:00",
    status: "unread",
    priority: "Normal",
    category: "finance",
    context: { type: "payment", id: "payment:reimb-pc-may06", label: "Reimbursement · PC · May 06" },
    related: { paymentAmount: "UGX 425,000" },
    attachments: [
      { id: "att-pc-1", name: "fuel-receipts-may06.pdf", meta: "PDF · 1.1 MB" },
      { id: "att-pc-2", name: "lodging-receipts.pdf",   meta: "PDF · 0.6 MB" },
    ],
    primaryAction: { key: "view-payment", label: "Open reimbursement", href: "/dashboards/accountant" },
  }),

  // HR Anne — leadership decision routed for her input
  msg({
    id: "M-D12",
    subject: "Q3 staff support cohort — fairness signal package",
    body:
      "Pulling together the Q3 support cohort across both regions.  5 staff above the fairness threshold this cycle, all CCEOs.\n\nBefore I route formally to the PLs, can you sense-check the cases?  Especially the two Central staff — their portfolios shifted mid-cycle and the fairness signal may already be in the recalibration window.",
    sender: { userId: "STF-EW-003", role: "RVP" },
    recipients: [{ userId: "STF-AW-019", status: "action_required", actionRequired: true }],
    createdAt: "2026-05-13T10:05:00+03:00",
    status: "action_required",
    priority: "Important",
    category: "hr-support",
    context: { type: "hr_case", id: "hr:q3-support-cohort", label: "Q3 Support cohort · Fairness review" },
    related: { activityType: "Staff support · Region" },
    primaryAction: { key: "create-followup", label: "Open cases", href: "/team-targets?view=hr-decisions" },
  }),

  // HR Anne — debrief routed by routing engine
  msg({
    id: "M-D13",
    subject: "Field debrief flagged for HR — Daniel M",
    body:
      "Daniel filed a Tuesday debrief mentioning back-to-back travel days for the second week running.  Routing engine tagged it for HR awareness — not yet an escalation, just visibility.\n\nNo immediate action required; flagged in case the pattern continues.",
    sender: { userId: "STF-DM-001", role: "System" },
    recipients: [{ userId: "STF-AW-019", status: "unread" }],
    createdAt: "2026-05-12T19:11:00+03:00",
    status: "unread",
    priority: "Normal",
    category: "field-debrief",
    context: { type: "field_debrief", id: "debrief:dm-tue-may12", label: "Daniel M · Field debrief · May 12" },
    related: { debriefCategory: "Workload signal" },
    primaryAction: { key: "view-debrief", label: "Open debrief", href: "/debriefs" },
    isSystemGenerated: true,
  }),
];

export function allMessages(): Message[] {
  return MESSAGES.filter((m) => !m.archived);
}

export function messageById(id: string): Message | undefined {
  return MESSAGES.find((m) => m.id === id);
}

// Returns every message in the same thread, in chronological order.
export function threadMessages(threadId: string): Message[] {
  return allMessages()
    .filter((m) => m.threadId === threadId)
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

// ───────────────────── Mutable-store façade ─────────────────────
//
// Composer + reply write through these so the inbox updates without a
// backing DB. Phase 3 swaps the bodies for real API calls; the call
// sites don't have to change.

/** Composer: append a brand-new top-level message. Returns the row.
 *  Caller passes either `context` (single) or `contexts` (bulk —
 *  multiple operational records under one grouped thread). The
 *  composer guards against missing context in the UI; the server
 *  action re-validates before calling this. */
export function appendMessage(input: {
  id?:       string;
  subject:   string;
  body:      string;
  sender:    { userId: string; role: MessageSenderRole };
  recipients: { userId: string; status?: MessageStatus; actionRequired?: boolean }[];
  category:  Message["category"];
  priority:  Message["priority"];
  context?:  MessageContext;
  contexts?: MessageContext[];
  related?:  Message["related"];
}): Message {
  const id = input.id ?? `M-${Date.now()}`;
  const row = msg({
    id,
    subject:   input.subject,
    body:      input.body,
    sender:    input.sender,
    recipients: input.recipients.map((r) => ({
      userId:         r.userId,
      status:         r.status ?? "unread",
      actionRequired: r.actionRequired ?? false,
    })),
    createdAt: new Date().toISOString(),
    status:    "unread",
    priority:  input.priority,
    category:  input.category,
    context:   input.context,
    contexts:  input.contexts,
    related:   input.related,
  });
  MESSAGES.unshift(row);
  return row;
}

/** Reply: append to an existing thread. Keeps the parent's threadId,
 *  stamps the parent's `updatedAt` so the inbox bubbles the thread. */
export function appendReply(input: {
  parentMessageId: string;
  body:            string;
  sender:          { userId: string; role: MessageSenderRole };
}): Message | null {
  const parent = messageById(input.parentMessageId);
  if (!parent) return null;
  const replyId = `${parent.id}-R${Date.now()}`;
  // Recipients of a reply: everyone on the parent thread except the
  // replying sender. Mirrors how email reply-to-all works.
  const replyRecipients = parent.recipients
    .map((r) => r.userId)
    .concat(parent.senderId)
    .filter((uid) => uid !== input.sender.userId)
    .map((userId) => ({ userId, status: "unread" as MessageStatus, actionRequired: false }));

  const row = msg({
    id:              replyId,
    threadId:        parent.threadId,
    parentMessageId: parent.id,
    subject:         parent.subject.startsWith("Re:") ? parent.subject : `Re: ${parent.subject}`,
    body:            input.body,
    sender:          input.sender,
    recipients:      replyRecipients,
    createdAt:       new Date().toISOString(),
    status:          "unread",
    priority:        "Normal",
    category:        parent.category,
    // Replies inherit the thread's full context list — never re-select.
    contexts:        parent.contexts,
    related:         parent.related,
  });
  MESSAGES.unshift(row);
  parent.updatedAt = row.createdAt;
  return row;
}

// ────────── Per-recipient status mutator (spec §8 actions) ──────────
//
// Each MessageRecipient carries its own status, so two recipients of
// the same message can be in different states (Sarah acknowledged,
// Daniel still hasn't read). `updateRecipientStatus` is the one
// mutator every read/ack/resolve/archive path calls — the server
// actions stay thin and just revalidate the affected route.
//
// The mutator is idempotent: setting `read` on a recipient that's
// already `read` is a no-op (no timestamp reshuffle). This matters
// for the auto-mark-read on detail-page open — we fire it every
// render and trust the mutator to skip when nothing's changed.

type RecipientStatusUpdate = "read" | "unread" | "acknowledged" | "resolved" | "archived";

export type UpdateResult =
  | { ok: true;  message: Message; threadId: string }
  | { ok: false; error: "message-not-found" | "recipient-not-found" };

export function updateRecipientStatus(
  messageId: string,
  userId:    string,
  newStatus: RecipientStatusUpdate,
): UpdateResult {
  const msg = MESSAGES.find((m) => m.id === messageId);
  if (!msg) return { ok: false, error: "message-not-found" };

  const recipient = msg.recipients.find((r) => r.userId === userId);
  if (!recipient) return { ok: false, error: "recipient-not-found" };

  const now = new Date().toISOString();
  // Map the requested transition to its canonical Status + stamp the
  // matching timestamp. Idempotent for repeated calls.
  switch (newStatus) {
    case "read":
      if (recipient.status === "unread" || recipient.status === "action_required") {
        // Don't clobber action_required → just stamp readAt. The
        // detail page distinguishes "seen but still owed action" from
        // "fully resolved".
        recipient.readAt = recipient.readAt ?? now;
        if (recipient.status === "unread") recipient.status = "read";
      }
      break;
    case "unread":
      recipient.status = "unread";
      recipient.readAt = undefined;
      break;
    case "acknowledged":
      recipient.status = "acknowledged";
      recipient.readAt = recipient.readAt ?? now;
      recipient.acknowledgedAt = recipient.acknowledgedAt ?? now;
      break;
    case "resolved":
      recipient.status = "resolved";
      recipient.readAt = recipient.readAt ?? now;
      recipient.resolvedAt = recipient.resolvedAt ?? now;
      break;
    case "archived":
      recipient.status = "archived";
      recipient.archivedAt = recipient.archivedAt ?? now;
      break;
  }

  // The aggregate `Message.status` reflects the most actionable state
  // across all recipients — used by the inbox list row's badge. If
  // ANY recipient still needs action, the aggregate stays action_required;
  // otherwise it falls back to the worst remaining state.
  msg.status = aggregateStatus(msg);
  msg.updatedAt = now;

  return { ok: true, message: msg, threadId: msg.threadId };
}

function aggregateStatus(msg: Message): Message["status"] {
  const statuses = msg.recipients.map((r) => r.status);
  if (statuses.includes("action_required")) return "action_required";
  if (statuses.includes("in_progress"))     return "in_progress";
  if (statuses.includes("unread"))          return "unread";
  if (statuses.every((s) => s === "resolved")) return "resolved";
  if (statuses.every((s) => s === "archived")) return "archived";
  if (statuses.every((s) => s === "acknowledged" || s === "resolved" || s === "archived")) return "acknowledged";
  return "read";
}
