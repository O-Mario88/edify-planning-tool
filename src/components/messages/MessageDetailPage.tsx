"use client";

// MessageDetailPage — Spark-Mail-inspired thread reading surface.
//
// One column, generous spacing. Top bar with back + category +
// more-actions. Header card with category accent + subject + sender
// identity for the THREAD PARENT. Each subsequent message renders as
// a calmer reply card with its own sender + timestamp. Context card
// adapts from the parent's `related`. Inline reply composer at the
// bottom. Action bar at the bottom for the most recent message.

import Link from "next/link";
import { ArrowLeft, MoreHorizontal, Paperclip } from "lucide-react";
import type { EdifyRole } from "@/lib/auth-public";
import { formatMessageFullTimestamp, formatMessageTime } from "@/lib/messages-v2/access";
import { categoryMeta } from "@/lib/messages-v2/categories";
import type { Message } from "@/lib/messages-v2/types";
import { cn } from "@/lib/utils";
import { MessageActionBar } from "./MessageActionBar";
import { MessageCategoryBadge, MessagePriorityBadge } from "./MessageBadges";
import { MessageContextCard } from "./MessageContextCard";
import { MessageReplyBox } from "./MessageReplyBox";
import { MessageRoleBadge } from "./MessageRoleBadge";

export function MessageDetailPage({
  thread,
  role,
  /** Where the "back" arrow returns to — typically the inbox URL the
   *  user came from. */
  backHref,
  backLabel = "Inbox",
  /** Server action that persists a reply. Passed through to the
   *  inline `<MessageReplyBox>` so the write goes through the spec's
   *  permission re-check. */
  replyAction,
}: {
  thread:      Message[];        // chronological — parent first
  role:        EdifyRole;
  backHref:    string;
  backLabel?:  string;
  replyAction: (formData: FormData) => Promise<void> | void;
}) {
  if (thread.length === 0) return null;
  const parent = thread[0];
  const latest = thread[thread.length - 1];
  const cat = categoryMeta(parent.category);
  const isSystemThread = thread.every((m) => m.isSystemGenerated);

  // The reply box defaults to replying to whoever sent the latest
  // message in the thread (other than the current user — but the
  // demo doesn't know "current user" here, so we just label by
  // sender name).
  const replyRecipientLabel = latest.senderId === parent.senderId
    ? parent.senderName
    : `${parent.senderName} + ${thread.length - 1} other${thread.length - 1 === 1 ? "" : "s"}`;

  return (
    <div className="min-h-screen bg-[var(--color-page)] pb-24 lg:pb-10">
      {/* ─────────────── Sticky top bar ─────────────── */}
      <header className="sticky top-0 z-20 bg-[var(--color-page)]/85 backdrop-blur border-b border-[var(--color-edify-divider)]/60">
        <div className="max-w-[820px] mx-auto px-4 lg:px-6 py-3 flex items-center justify-between gap-3">
          <Link
            href={backHref}
            className="inline-flex items-center gap-1.5 h-9 px-2.5 rounded-lg text-body font-semibold text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/40"
          >
            <ArrowLeft size={14} />
            {backLabel}
          </Link>
          <div className="flex items-center gap-2">
            <MessageCategoryBadge category={parent.category} size="sm" />
            <button
              type="button"
              aria-label="More actions"
              className="inline-flex items-center justify-center h-9 w-9 rounded-lg hover:bg-[var(--color-edify-soft)]/40"
            >
              <MoreHorizontal size={16} className="text-[var(--color-edify-muted)]" />
            </button>
          </div>
        </div>
      </header>

      {/* ─────────────── Reading column ─────────────── */}
      <main className="max-w-[820px] mx-auto px-4 lg:px-6 pt-6 lg:pt-8 space-y-4">
        {/* Parent header card */}
        <article className="card rounded-2xl overflow-hidden">
          <div className={cn("h-1 w-full", cat.dot)} aria-hidden />
          <div className="px-5 lg:px-6 py-5 lg:py-6">
            <div className="flex items-center gap-2 flex-wrap">
              <MessagePriorityBadge priority={parent.priority} />
              {parent.status === "action_required" && (
                <span className="inline-flex items-center px-2 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-[0.06em] bg-amber-50 text-amber-800 border border-amber-200">
                  Action required
                </span>
              )}
              {parent.status === "acknowledged" && (
                <span className="inline-flex items-center px-2 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-[0.06em] bg-emerald-50 text-emerald-700 border border-emerald-200">
                  Acknowledged
                </span>
              )}
              {parent.status === "resolved" && (
                <span className="inline-flex items-center px-2 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-[0.06em] bg-slate-100 text-slate-600 border border-slate-200">
                  Resolved
                </span>
              )}
              {thread.length > 1 && (
                <span className="inline-flex items-center px-2 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-[0.06em] bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] border border-[var(--color-edify-border)]">
                  {thread.length} messages
                </span>
              )}
            </div>
            <h1 className="text-[22px] lg:text-[28px] font-extrabold tracking-tight leading-snug text-balance mt-3">
              {parent.subject}
            </h1>
            {/* Thread context — the operational record(s) this whole
                thread is about. Inherited by every reply. When the
                thread is bulk (multi-context) we render a compact
                summary chip + expandable list of records. */}
            <ThreadContextSummary parent={parent} />

            <SenderRow message={parent} prominent />
          </div>
        </article>

        {/* Parent body */}
        <MessageBodyCard message={parent} />

        {/* Replies — calmer cards, smaller sender row */}
        {thread.slice(1).map((m) => (
          <article key={m.id} className="card rounded-2xl px-5 lg:px-6 py-5">
            <SenderRow message={m} />
            <div className="mt-4 text-body-lg lg:text-[14.5px] leading-[1.75] text-[var(--color-edify-text)] whitespace-pre-wrap">
              {m.body}
            </div>
            {m.attachments && m.attachments.length > 0 && (
              <AttachmentList attachments={m.attachments} />
            )}
          </article>
        ))}

        {/* Adaptive context card — derived from the parent message */}
        <MessageContextCard message={parent} />

        {/* Reply composer — inherits the thread's context. */}
        <MessageReplyBox
          threadSubject={parent.subject}
          threadId={parent.threadId}
          parentMessageId={latest.id}
          inheritedContext={parent.context}
          backHref={backHref}
          recipientLabel={replyRecipientLabel}
          enabled={!isSystemThread}
          replyAction={replyAction}
        />

        {/* Action bar — sticky on mobile so the primary CTA stays
            thumb-reachable while reading. Acts on the latest message. */}
        <MessageActionBar message={latest} role={role} sticky />
      </main>
    </div>
  );
}

// ─────────────────────────── sub-components ────────────────────────────

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

function ThreadContextSummary({ parent }: { parent: Message }) {
  const [expanded, setExpanded] = useState(false);
  const isBulk = parent.contextMode === "bulk" && parent.contexts.length > 1;

  if (!isBulk) {
    return (
      <div className="mt-3 inline-flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-[var(--color-edify-soft)]/60 border border-[var(--color-edify-border)] text-[11.5px] max-w-full">
        <span className="text-[10px] uppercase tracking-[0.06em] font-extrabold text-[var(--color-edify-muted)] shrink-0">
          Context
        </span>
        <span className="font-semibold text-[var(--color-edify-text)] truncate">
          {parent.context.label}
        </span>
      </div>
    );
  }

  // Bulk: summary chip with the count + expand toggle.
  return (
    <div className="mt-3 max-w-full">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="inline-flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-[var(--color-edify-soft)]/60 border border-[var(--color-edify-border)] text-[11.5px] hover:bg-[var(--color-edify-soft)] transition-colors"
      >
        <span className="text-[10px] uppercase tracking-[0.06em] font-extrabold text-[var(--color-edify-muted)] shrink-0">
          Context
        </span>
        <span className="font-semibold text-[var(--color-edify-text)]">
          {parent.contexts.length} records
        </span>
        {expanded ? <ChevronUp size={12} className="text-[var(--color-edify-muted)]" /> : <ChevronDown size={12} className="text-[var(--color-edify-muted)]" />}
      </button>
      {expanded && (
        <ul className="mt-2 rounded-lg border border-[var(--color-edify-divider)] divide-y divide-[var(--color-edify-divider)] overflow-hidden">
          {parent.contexts.map((c) => (
            <li key={c.id} className="px-3 py-2 flex items-center justify-between gap-3 bg-[var(--color-card)]">
              <span className="text-[12px] font-semibold text-[var(--color-edify-text)] truncate">{c.label}</span>
              <span className="text-[9.5px] uppercase tracking-[0.06em] font-extrabold text-[var(--color-edify-muted)] whitespace-nowrap">
                {c.type.replace(/_/g, " ")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SenderRow({ message, prominent = false }: { message: Message; prominent?: boolean }) {
  return (
    <div className={cn("flex items-start gap-3", prominent ? "mt-5" : "")}>
      <span
        className={cn(
          "rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center font-extrabold shrink-0",
          prominent ? "h-10 w-10 text-[12px]" : "h-8 w-8 text-[11px]",
        )}
      >
        {message.senderInitials ?? message.senderName.split(" ").map((s) => s[0]).slice(0, 2).join("")}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={cn(
            "font-extrabold tracking-tight text-[var(--color-edify-text)]",
            prominent ? "text-[13.5px]" : "text-body",
          )}>
            {message.senderName}
          </span>
          <MessageRoleBadge role={message.senderRole} size="xs" />
          <span className="text-caption text-[var(--color-edify-muted)] truncate">{message.senderEmail}</span>
        </div>
        <div className={cn(
          "text-[var(--color-edify-muted)] tabular mt-1",
          prominent ? "text-[11.5px]" : "text-caption",
        )}>
          {prominent
            ? formatMessageFullTimestamp(message.createdAt)
            : formatMessageTime(message.createdAt)}
        </div>
      </div>
    </div>
  );
}

function MessageBodyCard({ message }: { message: Message }) {
  return (
    <article className="card rounded-2xl px-5 lg:px-6 py-6 lg:py-7">
      <div className="text-[14.5px] lg:text-[15px] leading-[1.75] text-[var(--color-edify-text)] whitespace-pre-wrap">
        {message.body}
      </div>
      {message.attachments && message.attachments.length > 0 && (
        <AttachmentList attachments={message.attachments} />
      )}
    </article>
  );
}

function AttachmentList({ attachments }: { attachments: NonNullable<Message["attachments"]> }) {
  return (
    <div className="mt-6 pt-5 border-t border-[var(--color-edify-divider)]">
      <h3 className="text-[11px] font-extrabold tracking-[0.08em] uppercase text-[var(--color-edify-muted)] mb-3">
        Attachments
      </h3>
      <ul className="space-y-2">
        {attachments.map((a) => (
          <li key={a.id}>
            <a
              href={a.href ?? "#"}
              className="flex items-center gap-3 rounded-lg border border-[var(--color-edify-divider)] px-3 py-2.5 hover:bg-[var(--color-edify-soft)]/30 transition-colors"
            >
              <span className="grid place-items-center h-9 w-9 rounded-md bg-[var(--color-edify-soft)]/60 text-[var(--color-edify-primary)] shrink-0">
                <Paperclip size={14} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-semibold text-[var(--color-edify-text)] truncate">{a.name}</div>
                {a.meta && <div className="text-[11px] text-[var(--color-edify-muted)] truncate">{a.meta}</div>}
              </div>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
