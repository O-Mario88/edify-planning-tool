"use client";

// MessageActionBar — role-aware action row.
//
// The primary action is whatever the message itself prescribes
// (`message.primaryAction`) — e.g. "Correct submission", "View
// evidence", "Acknowledge". Secondary actions are filtered to the
// recipient's role. Renders inline on desktop, sticks to the bottom of
// the viewport on mobile so the primary CTA is always thumb-reachable.
//
// Status mutators (Acknowledge / Archive / Mark Resolved) are real:
// each secondary button submits a tiny `<form action={serverAction}>`
// with the messageId, the server action calls
// `updateRecipientStatus`, and revalidatePath bubbles the change back
// into the inbox + detail page.

import Link from "next/link";
import {
  Archive,
  ArrowUpFromLine,
  CheckCheck,
  CheckCircle2,
  CornerUpLeft,
  Eye,
  MoreHorizontal,
  type LucideIcon,
} from "lucide-react";
import type { EdifyRole } from "@/lib/auth-public";
import type { Message, MessageActionKey } from "@/lib/messages-v2/types";
import {
  acknowledgeAction,
  archiveAction,
  markResolvedAction,
} from "@/app/(shell)/messages/[id]/status-actions";
import { cn } from "@/lib/utils";

type ActionDef = {
  key:    MessageActionKey;
  label:  string;
  Icon:   LucideIcon;
  href?:  string;
  /** Server action invoked when this secondary button is clicked.
   *  When omitted, the button renders as a plain (no-op) button —
   *  useful for actions that aren't wired yet (Escalate, Reply). */
  action?: (formData: FormData) => Promise<void>;
};

// Returns secondary action chips appropriate for the given role +
// message. The primary action is rendered separately from
// `message.primaryAction`.
function secondaryActionsFor(message: Message, role: EdifyRole): ActionDef[] {
  const out: ActionDef[] = [];
  const isInternal = role !== "PartnerAdmin" && role !== "PartnerFieldOfficer" && role !== "PartnerViewer";

  // Reply — everyone except System messages. (Reply is wired
  // through the inline MessageReplyBox lower on the detail page;
  // this button could scroll to it in a future polish pass.)
  if (message.senderRole !== "System") {
    out.push({ key: "reply", label: "Reply", Icon: CornerUpLeft });
  }

  // Acknowledge — surfaces when there's outstanding action. Wired to
  // the real server mutator.
  if (message.status === "action_required" && message.primaryAction?.key !== "acknowledge") {
    out.push({ key: "acknowledge", label: "Acknowledge", Icon: CheckCheck, action: acknowledgeAction });
  }

  // Mark Resolved — for action_required + already-acknowledged
  // messages, internal roles can close the loop.
  if (isInternal && (message.status === "action_required" || message.status === "acknowledged" || message.status === "in_progress")) {
    out.push({ key: "mark-done", label: "Mark Resolved", Icon: CheckCircle2, action: markResolvedAction });
  }

  // Escalate to leadership — internal roles only. Not yet wired —
  // when it lands it'll add a system message at priority=Urgent.
  if (isInternal && message.priority !== "Critical" && message.status !== "resolved") {
    out.push({ key: "escalate", label: "Escalate", Icon: ArrowUpFromLine });
  }

  // Archive — anyone can archive. Wired to the real server mutator.
  out.push({ key: "archive", label: "Archive", Icon: Archive, action: archiveAction });

  return out;
}

export function MessageActionBar({
  message,
  role,
  /** Set on mobile/tablet detail pages — sticky to viewport bottom so
   *  the primary CTA is always thumb-reachable. */
  sticky = false,
}: {
  message: Message;
  role:    EdifyRole;
  sticky?: boolean;
}) {
  const primary = message.primaryAction;
  const secondary = secondaryActionsFor(message, role);

  // On mobile/tablet the bottom of the viewport already hosts the
  // shell's RoleBottomNav (~72px). Stick the action bar ABOVE it so
  // both stay reachable — uses `bottom-[72px]` on mobile and resets to
  // `lg:bottom-auto lg:relative` on desktop.
  const wrapperClass = cn(
    "card rounded-2xl p-3 lg:p-4 flex items-center justify-between gap-3",
    sticky && "fixed bottom-[72px] inset-x-3 z-30 bg-[var(--color-card)] shadow-[0_-8px_24px_-12px_rgba(15,23,32,0.18)] lg:relative lg:bottom-auto lg:inset-auto lg:shadow-none",
  );

  const PrimaryIcon = primary?.key === "view-evidence" || primary?.key === "view-payment" || primary?.key === "view-school" || primary?.key === "view-cluster" || primary?.key === "view-activity" || primary?.key === "view-debrief"
    ? Eye
    : primary?.key === "reply" ? CornerUpLeft
    : primary?.key === "acknowledge" ? CheckCheck
    : ArrowUpFromLine;

  // Premium button class — shared by primary <Link>/<button>.
  const primaryClass = "inline-flex items-center justify-center gap-1.5 h-10 lg:h-9 px-4 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-body font-extrabold shadow-[0_1px_2px_rgba(15,23,32,0.06)] whitespace-nowrap";

  return (
    <footer className={wrapperClass}>
      {/* ─── Mobile layout: primary CTA fills, secondaries collapse to More ─── */}
      <div className="lg:hidden flex items-center gap-2 w-full">
        {primary && (
          primary.href ? (
            <Link href={primary.href} className={cn(primaryClass, "flex-1")}>
              <PrimaryIcon size={14} />
              {primary.label}
            </Link>
          ) : (
            <button type="button" className={cn(primaryClass, "flex-1")}>
              <PrimaryIcon size={14} />
              {primary.label}
            </button>
          )
        )}
        <button
          type="button"
          aria-label="More actions"
          className="inline-flex items-center justify-center h-10 w-10 shrink-0 rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/40"
        >
          <MoreHorizontal size={16} className="text-[var(--color-edify-muted)]" />
        </button>
      </div>

      {/* ─── Desktop layout: full secondary row + primary on the right ─── */}
      <div className="hidden lg:flex items-center justify-between gap-3 w-full">
        <div className="flex items-center gap-1.5">
          {secondary.slice(0, 4).map((a) => {
            const className = "inline-flex items-center gap-1.5 h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/40 text-[12px] font-semibold whitespace-nowrap";
            const inner = (
              <>
                <a.Icon size={12} className="text-[var(--color-edify-muted)]" />
                {a.label}
              </>
            );
            // Wired actions submit a tiny inline form so the server
            // mutator runs and revalidatePath bubbles the change.
            return a.action ? (
              <form key={a.key} action={a.action}>
                <input type="hidden" name="messageId" value={message.id} />
                <button type="submit" className={className}>{inner}</button>
              </form>
            ) : (
              <button key={a.key} type="button" className={className}>{inner}</button>
            );
          })}
        </div>
        {primary && (
          primary.href ? (
            <Link href={primary.href} className={primaryClass}>
              <PrimaryIcon size={13} />
              {primary.label}
            </Link>
          ) : (
            <button type="button" className={primaryClass}>
              <PrimaryIcon size={13} />
              {primary.label}
            </button>
          )
        )}
      </div>
    </footer>
  );
}
