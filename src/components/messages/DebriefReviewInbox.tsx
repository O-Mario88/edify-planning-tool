// DebriefReviewInbox — server-component panel that surfaces debrief
// messages routed to the signed-in role.
//
// Drops into HR / CD / PL / CCEO dashboards as the "your review
// queue" card. Reads through messages-v2 (so debriefs submitted
// through `submitDebriefAction` show up here automatically), filters
// to the debrief categories, and renders rows that link to the full
// message detail page.

import Link from "next/link";
import { ArrowRight, ClipboardList, Inbox } from "lucide-react";
import type { DemoUser } from "@/lib/auth";
import { messagesForUser, formatMessageTime } from "@/lib/messages-v2/access";
import {
  MessageCategoryDot,
  MessagePriorityBadge,
} from "./MessageBadges";

const DEBRIEF_CATEGORIES = new Set([
  "field-debrief",
  "partner-debrief",
  "hr-support",
]);

export function DebriefReviewInbox({
  user,
  /** "HR view" / "Country Director view" / "Program Lead view" — sets
   *  the title + helper copy. */
  audience,
  /** How many rows to show inline. Default 5. */
  limit = 5,
}: {
  user:     DemoUser;
  audience: "hr" | "cd" | "pl" | "cceo";
  limit?:   number;
}) {
  const inbox = messagesForUser(user, "inbox").filter((m) => DEBRIEF_CATEGORIES.has(m.category));
  const actionable = inbox.filter((m) => m.status === "action_required");
  const top = inbox.slice(0, limit);

  const { title, sub, empty } = COPY[audience];

  return (
    <section className="card rounded-2xl overflow-hidden">
      <header className="px-4 lg:px-5 pt-4 pb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
            <ClipboardList size={14} className="text-[var(--color-edify-muted)]" />
            {title}
          </h3>
          <p className="text-[11.5px] text-[var(--color-edify-muted)] mt-0.5 leading-snug max-w-[480px]">
            {sub}
          </p>
        </div>
        {actionable.length > 0 && (
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-amber-50 border border-amber-200 text-amber-800 text-caption font-extrabold uppercase tracking-[0.06em] whitespace-nowrap">
            {actionable.length} need action
          </span>
        )}
      </header>

      {top.length === 0 ? (
        <div className="px-5 lg:px-6 pb-6 pt-2 text-center text-[12px] text-[var(--color-edify-muted)]">
          <div className="mx-auto h-10 w-10 rounded-full bg-emerald-50 grid place-items-center text-emerald-700 mb-2">
            <Inbox size={16} />
          </div>
          {empty}
        </div>
      ) : (
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {top.map((m) => (
            <li key={m.id}>
              <Link
                href={`/messages/${m.id}`}
                className="flex items-start gap-3 px-4 lg:px-5 py-3 hover:bg-[var(--color-edify-soft)]/30 transition-colors"
              >
                <span className="h-9 w-9 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center text-[11px] font-extrabold shrink-0">
                  {m.senderInitials ?? m.senderName.split(" ").map((s) => s[0]).slice(0, 2).join("")}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline justify-between gap-3">
                    <div className="text-body font-extrabold tracking-tight text-[var(--color-edify-text)] truncate">
                      {m.senderName}
                    </div>
                    <div className="text-caption text-[var(--color-edify-muted)] tabular shrink-0">
                      {formatMessageTime(m.createdAt)}
                    </div>
                  </div>
                  <div className="text-[12px] font-semibold text-[var(--color-edify-text)] truncate mt-0.5">
                    {m.subject}
                  </div>
                  <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                    <MessageCategoryDot category={m.category} />
                    <MessagePriorityBadge priority={m.priority} size="xs" />
                    {m.status === "action_required" && (
                      <span className="inline-flex items-center px-1.5 py-[1px] rounded-md text-[9.5px] font-extrabold uppercase tracking-[0.06em] bg-amber-50 text-amber-800 border border-amber-200">
                        Action required
                      </span>
                    )}
                  </div>
                </div>
                <ArrowRight size={13} className="text-[var(--color-edify-muted)] shrink-0 mt-1" />
              </Link>
            </li>
          ))}
        </ul>
      )}

      {inbox.length > limit && (
        <footer className="px-4 lg:px-5 py-3 border-t border-[var(--color-edify-divider)] text-right">
          <Link
            href="/messages"
            className="text-[11.5px] font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-1"
          >
            View All {inbox.length}
            <ArrowRight size={11} />
          </Link>
        </footer>
      )}
    </section>
  );
}

const COPY: Record<"hr" | "cd" | "pl" | "cceo", { title: string; sub: string; empty: string }> = {
  hr: {
    title: "Debriefs routed to HR",
    sub:   "CCEO + PL field debriefs flagged for HR — workload, wellbeing, support requests, urgent escalations.",
    empty: "No debriefs need HR review right now.",
  },
  cd: {
    title: "Field reality from your team",
    sub:   "CCEO + PL debriefs routed to country leadership — program risks, decisions needed, escalations.",
    empty: "No debriefs in your queue. Quiet field day.",
  },
  pl: {
    title: "Partner + team debriefs",
    sub:   "Partner activity debriefs and team field signals routed to you for review.",
    empty: "No debriefs need your review.",
  },
  cceo: {
    title: "Partner feedback on my schools",
    sub:   "Partner debriefs flagged against schools you monitor — follow-ups, evidence, coordination.",
    empty: "No partner debriefs about your schools yet.",
  },
};
