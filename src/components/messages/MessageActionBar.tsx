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
import { useState } from "react";
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

  // Reply — everyone except System messages. Scrolls to the inline
  // MessageReplyBox (id="message-reply") rendered lower on the detail page.
  if (message.senderRole !== "System") {
    out.push({ key: "reply", label: "Reply", Icon: CornerUpLeft, href: "#message-reply" });
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

  // (Escalate-to-leadership removed: it had no backend. When a real
  // escalation flow lands — a system message at priority=Urgent — it can be
  // re-added here wired to a server action, not a no-op button.)

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
  const [moreOpen, setMoreOpen] = useState(false);
  // A primary "reply" with no explicit destination targets the inline reply box.
  const primaryHref = primary?.href ?? (primary?.key === "reply" ? "#message-reply" : undefined);

  // Render one secondary action as the correct element: a link (href), a
  // server-action form (action), or — only if neither — a plain button.
  const renderSecondary = (a: ActionDef, className: string) => {
    const inner = (
      <>
        <a.Icon size={12} className="text-[var(--color-edify-muted)]" />
        {a.label}
      </>
    );
    if (a.href) return <a key={a.key} href={a.href} className={className} onClick={() => setMoreOpen(false)}>{inner}</a>;
    if (a.action)
      return (
        <form key={a.key} action={a.action} className="contents">
          <input type="hidden" name="messageId" value={message.id} />
          <button type="submit" className={className} onClick={() => setMoreOpen(false)}>{inner}</button>
        </form>
      );
    return <button key={a.key} type="button" className={className}>{inner}</button>;
  };

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
      <div className="lg:hidden w-full">
        <div className="flex items-center gap-2 w-full">
          {primary && (
            primaryHref ? (
              <Link href={primaryHref} className={cn(primaryClass, "flex-1")}>
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
          {secondary.length > 0 && (
            <button
              type="button"
              aria-label="More actions"
              aria-expanded={moreOpen}
              onClick={() => setMoreOpen((v) => !v)}
              className="inline-flex items-center justify-center h-10 w-10 shrink-0 rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/40"
            >
              <MoreHorizontal size={16} className="text-[var(--color-edify-muted)]" />
            </button>
          )}
        </div>
        {/* The secondary actions (Reply, Acknowledge, Mark Resolved, Archive)
            were previously unreachable on mobile — More is now a real
            disclosure that lists them, each wired to its link/server action. */}
        {moreOpen && secondary.length > 0 && (
          <div className="mt-2 grid grid-cols-2 gap-1.5">
            {secondary.map((a) =>
              renderSecondary(
                a,
                "inline-flex items-center justify-center gap-1.5 h-10 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/40 text-[12px] font-semibold w-full",
              ),
            )}
          </div>
        )}
      </div>

      {/* ─── Desktop layout: full secondary row + primary on the right ─── */}
      <div className="hidden lg:flex items-center justify-between gap-3 w-full">
        <div className="flex items-center gap-1.5">
          {secondary.slice(0, 4).map((a) =>
            renderSecondary(
              a,
              "inline-flex items-center gap-1.5 h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/40 text-[12px] font-semibold whitespace-nowrap",
            ),
          )}
        </div>
        {primary && (
          primaryHref ? (
            <Link href={primaryHref} className={primaryClass}>
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
