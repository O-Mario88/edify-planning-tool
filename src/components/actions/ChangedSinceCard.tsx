"use client";

// ChangedSinceCard — the "What changed since you last looked" digest.
//
// Compact list. Each row is one change: kind + subject + context +
// when. Tone-tinted dot. Click → goes to the relevant detail page.
//
// Important UX rule: this is read-mostly. We do NOT show approve/reject
// buttons inline — that's the Inbox's job. The digest just answers
// "what happened while I was gone" so the user can mentally re-orient
// in under 10 seconds.

import Link from "next/link";
import { motion } from "motion/react";
import { History } from "lucide-react";
import type { ChangedSinceEntry } from "@/lib/actions/action-types";
import { relativeFromNow } from "@/lib/actions/last-login";
import { cn } from "@/lib/utils";
import { fadeUp, stagger, staggerContainer } from "@/lib/motion";

const TONE_DOT: Record<ChangedSinceEntry["tone"], string> = {
  info:    "bg-sky-500",
  success: "bg-emerald-500",
  warn:    "bg-amber-500",
  danger:  "bg-rose-500",
};

export function ChangedSinceCard({
  entries,
  embedded = false,
}: {
  entries: ChangedSinceEntry[];
  /** When rendered inside a parent rail (e.g. CommandStack's Today
   * card), strip the own card chrome + heavier title so the children
   * read as ONE surface instead of nested cards. */
  embedded?: boolean;
}) {
  const Wrapper = embedded ? "div" : "section";
  return (
    <Wrapper className={embedded ? "" : "card p-3.5"}>
      <header className="flex items-center gap-2 mb-3">
        {!embedded ? (
          <span className="w-6 h-6 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center">
            <History size={13} />
          </span>
        ) : null}
        <h3 className={embedded ? "section-h-micro" : "text-[13px] font-extrabold tracking-tight"}>
          {embedded ? "Since You Last Looked" : "Since You Last Looked"}
        </h3>
        {entries.length > 0 ? (
          <span className={cn(
            "ml-auto text-[11px] font-semibold",
            embedded ? "text-muted" : "text-[var(--color-edify-muted)]",
          )}>
            {entries.length} change{entries.length === 1 ? "" : "s"}
          </span>
        ) : null}
      </header>

      {entries.length === 0 ? (
        <p className="text-body text-[var(--color-edify-muted)] py-2">
          Nothing new since your last visit. Quiet is good.
        </p>
      ) : (
        <motion.ul
          className="divide-y divide-[var(--color-edify-divider)]"
          variants={staggerContainer(0.04, stagger.row)}
          initial="hidden"
          animate="visible"
        >
          {entries.map((e) => (
            <motion.li key={e.id} variants={fadeUp} className="py-2 first:pt-0 last:pb-0">
              <Link href={e.href} className="group flex items-start gap-2.5">
                <span className={cn("mt-1.5 inline-block h-2 w-2 rounded-full shrink-0", TONE_DOT[e.tone])} />
                <div className="flex-1 min-w-0">
                  <p className="text-body leading-snug">
                    <span className="font-extrabold text-[var(--color-edify-text)]">{e.kind}</span>
                    <span className="text-[var(--color-edify-muted)]"> · </span>
                    <span className="font-semibold text-[var(--color-edify-text)]">{e.subject}</span>
                    {e.context ? (
                      <>
                        <span className="text-[var(--color-edify-muted)]"> — </span>
                        <span className="text-[var(--color-edify-muted)]">{e.context}</span>
                      </>
                    ) : null}
                  </p>
                  <p className="text-caption text-[var(--color-edify-muted)] mt-0.5">
                    {relativeFromNow(e.at)}
                  </p>
                </div>
              </Link>
            </motion.li>
          ))}
        </motion.ul>
      )}
    </Wrapper>
  );
}
