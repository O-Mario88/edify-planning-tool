// Notification dispatcher.
//
// Every `emitNotification` call goes through here. The dispatcher
// decides which channels actually deliver based on:
//
//   • the explicit `channel` field set by the caller (Inbox/Email/SMS)
//   • a priority hint derived from the template
//   • the user's per-channel preferences (when we have them)
//
// Routing today (overridable via env DISPATCH_OVERRIDE_*):
//
//   priority=critical  → SMS + Email + Inbox
//   priority=important → Email + Inbox
//   priority=normal    → Inbox only
//
// Email + SMS sends are fire-and-forget — never block the caller. The
// dispatcher catches every error and reports it via observability so
// a flapping provider can't wedge a server action.

import "server-only";
import { email, sms, observability } from "./index";
import type { NotificationRecord } from "@/lib/actions/audit";
import { publish } from "./notification-bus";

export type Priority = "critical" | "important" | "normal";

/** Subset of templates that go SMS-first. Curated, not derived from
 *  the wire format — SMS spend matters. */
const CRITICAL_TEMPLATES = new Set<string>([
  "fundPlan.urgentReturned",
  "weeklyFund.disbursementBlocked",
  "incident.production",
]);

const IMPORTANT_PREFIXES = [
  "fundPlan.",
  "weeklyFund.",
  "reimbursement.",
  "balanceReturn.",
  "plan.approved",
  "plan.returned",
  "partnerActivity.paid",
  "leave.",
  "auth.",
];

function priorityFor(template: string): Priority {
  if (CRITICAL_TEMPLATES.has(template)) return "critical";
  if (IMPORTANT_PREFIXES.some((p) => template.startsWith(p))) return "important";
  return "normal";
}

export type ResolvedRecipient = {
  userId:   string;
  emailTo?: string;
  smsTo?:   string;
};

/** Resolve a userId to actual contact targets. Production wires this
 *  to the User table; mock-mode returns synthetic placeholders so
 *  console adapters can still log. */
export type RecipientResolver = (userId: string) => Promise<ResolvedRecipient | null>;

let resolver: RecipientResolver = async (userId) => ({ userId });

export function setRecipientResolver(r: RecipientResolver): void {
  resolver = r;
}

// ────────── Public API ────────────────────────────────────────────

/** Called by emitNotification with the freshly-written inbox row.
 *  Fans out to email + SMS based on priority + channel hints. */
export function dispatchAfterEmit(record: NotificationRecord): void {
  // Live in-app push (header bell).
  publish(record.userId, {
    id: record.id,
    type: "notification",
    data: {
      template: record.template,
      title:    record.title,
      body:     record.body,
      href:     record.href,
      channel:  record.channel,
    },
  });

  const priority = priorityFor(record.template);

  // Inbox-only short-circuit. We don't even need a recipient resolve
  // for these — they already live in the store.
  if (priority === "normal" && record.channel !== "Email" && record.channel !== "SMS") {
    return;
  }

  // Fire-and-forget — never await this from the caller's request.
  void deliver(record, priority);
}

async function deliver(record: NotificationRecord, priority: Priority): Promise<void> {
  try {
    const recipient = await resolver(record.userId);
    if (!recipient) {
      observability.captureMessage(`dispatch: no recipient for ${record.userId}`, "warning", {
        tags: { template: record.template },
      });
      return;
    }

    observability.addBreadcrumb({
      category: "dispatch",
      message: `${record.template} (${priority}) → ${record.userId}`,
      data: { recipientHasEmail: !!recipient.emailTo, recipientHasSms: !!recipient.smsTo },
    });

    // SMS — only on critical, only if we have a phone number.
    if (priority === "critical" && recipient.smsTo) {
      const r = await sms.send({
        to: recipient.smsTo,
        body: `${record.title}\n${record.body}`,
        template: record.template,
      });
      if (!r.ok) {
        observability.captureMessage(`dispatch.sms failed: ${r.error}`, "error", {
          tags: { template: record.template, recipient: record.userId },
        });
      }
    }

    // Email — on critical + important, if we have an address.
    if ((priority === "critical" || priority === "important") && recipient.emailTo) {
      const r = await email.send({
        to: recipient.emailTo,
        subject: record.title,
        text: record.body + (record.href ? `\n\n${record.href}` : ""),
        template: record.template,
        idempotencyKey: `notif-${record.id}`,
      });
      if (!r.ok) {
        observability.captureMessage(`dispatch.email failed: ${r.error}`, "error", {
          tags: { template: record.template, recipient: record.userId },
        });
      }
    }
  } catch (err) {
    observability.captureError(err, {
      tags: { surface: "dispatch", template: record.template },
      extra: { record },
    });
  }
}
