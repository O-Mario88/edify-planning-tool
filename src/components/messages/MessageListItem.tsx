"use client";

// MessageListItem — premium inbox row.
//
// Read/unread is the dominant visual axis: unread gets a 3px coloured
// accent stripe on the leading edge (colour follows the message
// category) plus a stronger sender + subject. Read rows are calm,
// lighter weights, no stripe. Hover lifts the row tint.

import { cn } from "@/lib/utils";
import { categoryMeta } from "@/lib/messages-v2/categories";
import { formatMessageTime } from "@/lib/messages-v2/access";
import type { Message } from "@/lib/messages-v2/types";
import { MessageCategoryDot } from "./MessageBadges";
import { MessageRoleBadge } from "./MessageRoleBadge";

export function MessageListItem({
  message,
  selected = false,
  onClick,
  /** When provided, the row renders as an anchor with this href —
   *  used by mobile/tablet to navigate to the detail page instead of
   *  selecting in-place. */
  href,
}: {
  message:  Message;
  selected?: boolean;
  onClick?:  () => void;
  href?:     string;
}) {
  const cat = categoryMeta(message.category);
  const unread = message.status === "unread" || message.status === "action_required";

  const content = (
    <>
      <div className="flex items-start justify-between gap-3">
        <div
          className={cn(
            "text-[13px] tracking-tight truncate",
            unread
              ? "font-extrabold text-[var(--color-edify-text)]"
              : "font-semibold text-[var(--color-edify-text)]/85",
          )}
        >
          {message.senderName}
        </div>
        <span className="text-caption text-[var(--color-edify-muted)] tabular whitespace-nowrap pt-0.5">
          {formatMessageTime(message.createdAt)}
        </span>
      </div>
      <div
        className={cn(
          "text-body mt-1 leading-snug line-clamp-1",
          unread ? "font-bold text-[var(--color-edify-text)]" : "text-[var(--color-edify-text)]/75",
        )}
      >
        {message.subject}
      </div>
      <div className="text-[11.5px] text-[var(--color-edify-muted)] leading-snug mt-1 line-clamp-1">
        {message.preview}
      </div>
      <div className="flex items-center gap-2 mt-2 flex-wrap">
        <MessageRoleBadge role={message.senderRole} size="xs" />
        <MessageCategoryDot category={message.category} />
        {message.related?.schoolName && (
          <span className="text-caption text-[var(--color-edify-muted)] truncate max-w-[180px]">
            · {message.related.schoolName}
          </span>
        )}
      </div>
    </>
  );

  const rowClassName = cn(
    "relative block w-full text-left px-4 py-3.5 transition-colors",
    "before:absolute before:left-0 before:top-0 before:bottom-0 before:w-[3px] before:transition-opacity",
    unread ? cn("before:opacity-100", cat.stripe) : "before:opacity-0",
    selected
      ? "bg-[var(--color-edify-soft)]/55"
      : "hover:bg-[var(--color-edify-soft)]/30",
  );

  if (href) {
    return (
      <li>
        <a href={href} className={rowClassName}>
          {content}
        </a>
      </li>
    );
  }
  return (
    <li>
      <button type="button" onClick={onClick} className={rowClassName}>
        {content}
      </button>
    </li>
  );
}
