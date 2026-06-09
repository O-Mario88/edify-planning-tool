"use client";

// MessageReplyBox — compact reply composer at the bottom of a thread.
//
// Subject is locked to the parent's subject (prefixed "Re: " if it
// isn't already). Recipients are the original sender + any other
// thread participants minus the current user. Mock submit today —
// logs and reloads the thread view.

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, CornerUpLeft, Lock, Send } from "lucide-react";
import { cn } from "@/lib/utils";
import type { MessageContext } from "@/lib/messages-v2/types";

export function MessageReplyBox({
  threadSubject,
  threadId,
  recipientLabel,
  /** Parent message id — needed by the server action to thread the
   *  reply correctly. */
  parentMessageId,
  /** The thread's inherited context — rendered read-only above the
   *  textarea so the user sees that the reply will be filed against
   *  the same operational record as the parent. */
  inheritedContext,
  /** Where to return to (revalidation). */
  backHref,
  /** When false, reply UI is hidden (e.g. system messages can't be replied to). */
  enabled = true,
  /** Server action that persists the reply. */
  replyAction,
}: {
  threadSubject:    string;
  threadId:         string;
  parentMessageId:  string;
  inheritedContext: MessageContext;
  backHref:         string;
  recipientLabel:   string;
  enabled?:         boolean;
  replyAction:      (formData: FormData) => Promise<void> | void;
}) {
  void threadId; // kept for future thread-status updates
  void threadSubject;
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!enabled) {
    return (
      <section className="card p-3.5 text-center text-[12px] text-[var(--color-edify-muted)]">
        This message is system-generated. Replies aren&apos;t available.
      </section>
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (body.trim().length === 0) return;
    setSubmitting(true);
    const fd = new FormData();
    fd.append("parentMessageId", parentMessageId);
    fd.append("body", body);
    fd.append("backHref", backHref);
    try {
      await replyAction(fd);
      // Server action redirects back to the thread page; control
      // typically doesn't return. If it does (e.g. validation error),
      // reset state so the user can retry.
      setBody("");
      setSubmitting(false);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("[message] reply failed", err);
      setSubmitting(false);
    }
  }

  return (
    <form id="message-reply" onSubmit={handleSubmit} className="card p-3.5 lg:p-5 scroll-mt-20">
      <header className="flex items-center gap-2 mb-3">
        <CornerUpLeft size={14} className="text-[var(--color-edify-muted)]" />
        <h3 className="text-body font-extrabold tracking-tight">
          Reply to <span className="text-[var(--color-edify-text)]">{recipientLabel}</span>
        </h3>
      </header>

      {/* Inherited context — read-only. Spec section 3 + 5: replies
          stay under the original message's context. Switching topic
          requires starting a new thread. */}
      <div className="mb-2 flex items-start gap-2.5 rounded-lg border border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/40 px-3 py-2.5">
        <Lock size={11} className="text-[var(--color-edify-muted)] mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="text-[10px] uppercase tracking-[0.06em] font-extrabold text-[var(--color-edify-muted)]">
            Thread context · inherited
          </div>
          <div className="text-[12px] font-semibold text-[var(--color-edify-text)] truncate mt-0.5">
            {inheritedContext.label}
          </div>
        </div>
      </div>

      {/* Context-change guardrail (spec section 5). If the reply is
          actually about a different topic, send the user to a fresh
          composer instead of muddling this thread's context. We pass
          the original recipient as a hint so they don't have to
          re-search. The link is intentionally quiet — most replies
          stay in-thread, this is the escape hatch. */}
      <div className="mb-3 -mt-1 text-right">
        <Link
          href="/messages/new"
          className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-edify-muted)] hover:text-[var(--color-edify-primary)]"
        >
          Different topic? Start a new message
          <ArrowUpRight size={11} />
        </Link>
      </div>
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value.slice(0, 4000))}
        placeholder="Write a reply…"
        rows={4}
        className="w-full px-3 py-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[13.5px] leading-[1.7] placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30 resize-y"
      />
      <div className="mt-3 flex items-center justify-between gap-3">
        <span className="text-caption text-[var(--color-edify-muted)] tabular">{body.length}/4000</span>
        <button
          type="submit"
          disabled={body.trim().length === 0 || submitting}
          className={cn(
            "h-9 px-4 rounded-lg text-white text-body font-extrabold inline-flex items-center gap-1.5 transition-colors",
            body.trim().length === 0 || submitting
              ? "bg-[var(--color-edify-muted)] cursor-not-allowed"
              : "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)]",
          )}
        >
          <Send size={13} />
          {submitting ? "Sending…" : "Send reply"}
        </button>
      </div>
    </form>
  );
}
