"use client";

// MessageReaderPane — desktop-only inline reader. Shares typography and
// layout decisions with MessageDetailPage (the full-page mobile/tablet
// surface) so the read experience is identical regardless of viewport.
// The "Open full view" link routes to the detail page so the user can
// always escalate to the full surface (useful when copy-pasting,
// reading long bodies, or sharing the URL).

import Link from "next/link";
import { ArrowUpRight, Paperclip } from "lucide-react";
import type { EdifyRole } from "@/lib/auth-public";
import { formatMessageFullTimestamp } from "@/lib/messages-v2/access";
import { categoryMeta } from "@/lib/messages-v2/categories";
import type { Message } from "@/lib/messages-v2/types";
import { cn } from "@/lib/utils";
import { MessageActionBar } from "./MessageActionBar";
import { MessageCategoryBadge, MessagePriorityBadge } from "./MessageBadges";
import { MessageContextCard } from "./MessageContextCard";
import { MessageRoleBadge } from "./MessageRoleBadge";

export function MessageReaderPane({
  message,
  role,
  detailHref,
}: {
  message:    Message;
  role:       EdifyRole;
  detailHref: string;
}) {
  const cat = categoryMeta(message.category);

  return (
    <article className="card rounded-2xl overflow-hidden flex flex-col max-h-[calc(100vh-160px)]">
      <div className={cn("h-1 w-full", cat.dot)} aria-hidden />
      <header className="px-5 lg:px-6 pt-5 pb-4 border-b border-[var(--color-edify-divider)]">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2 flex-wrap">
            <MessageCategoryBadge category={message.category} />
            <MessagePriorityBadge priority={message.priority} />
          </div>
          <Link
            href={detailHref}
            className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]"
          >
            Open full view
            <ArrowUpRight size={11} />
          </Link>
        </div>
        <h2 className="text-[18px] lg:text-[20px] font-extrabold tracking-tight leading-snug text-balance mt-3">
          {message.subject}
        </h2>
        <div className="mt-3 flex items-start gap-3">
          <span className="h-9 w-9 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center font-extrabold text-[11.5px] shrink-0">
            {message.senderInitials ?? message.senderName.split(" ").map((s) => s[0]).slice(0, 2).join("")}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-body font-extrabold tracking-tight text-[var(--color-edify-text)]">
                {message.senderName}
              </span>
              <MessageRoleBadge role={message.senderRole} size="xs" />
            </div>
            <div className="text-[11px] text-[var(--color-edify-muted)] tabular mt-0.5">
              {formatMessageFullTimestamp(message.createdAt)}
            </div>
          </div>
        </div>
      </header>

      <div className="px-5 lg:px-6 py-5 overflow-y-auto flex-1 space-y-4">
        <div className="text-body-lg leading-[1.7] text-[var(--color-edify-text)] whitespace-pre-wrap">
          {message.body}
        </div>

        {message.attachments && message.attachments.length > 0 && (
          <div className="pt-4 border-t border-[var(--color-edify-divider)]">
            <h3 className="text-caption font-extrabold tracking-[0.08em] uppercase text-[var(--color-edify-muted)] mb-2">
              Attachments
            </h3>
            <ul className="space-y-1.5">
              {message.attachments.map((a) => (
                <li key={a.id}>
                  <a
                    href={a.href ?? "#"}
                    className="flex items-center gap-2.5 rounded-lg border border-[var(--color-edify-divider)] px-2.5 py-2 hover:bg-[var(--color-edify-soft)]/30 transition-colors"
                  >
                    <span className="grid place-items-center h-8 w-8 rounded-md bg-[var(--color-edify-soft)]/60 text-[var(--color-edify-primary)] shrink-0">
                      <Paperclip size={12} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[12px] font-semibold text-[var(--color-edify-text)] truncate">{a.name}</div>
                      {a.meta && <div className="text-caption text-[var(--color-edify-muted)]">{a.meta}</div>}
                    </div>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}

        <MessageContextCard message={message} />
      </div>

      <div className="px-5 lg:px-6 py-3 border-t border-[var(--color-edify-divider)]">
        <MessageActionBar message={message} role={role} />
      </div>
    </article>
  );
}
