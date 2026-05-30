"use client";

// DoneForTodayChecklist — the panel that tells the user "you're done."
//
// Small, end-of-page card. Each row is a check item with a satisfied
// flag from the engine. When all are green, the panel switches its
// header to "✓ Done for Today — you've cleared the bar."
//
// Why this matters: knowledge workers don't always know when to stop.
// This card replaces the vague "is there more I should do?" anxiety
// with a definitive answer.

import { CheckCircle2, Circle, ListChecks } from "lucide-react";
import { motion } from "motion/react";
import type { DoneCheckItem } from "@/lib/actions/action-types";
import { cn } from "@/lib/utils";
import { fadeUp, stagger, staggerContainer } from "@/lib/motion";

export function DoneForTodayChecklist({
  items,
  embedded = false,
}: {
  items: DoneCheckItem[];
  /** When rendered inside the consolidated Today rail, drop the own
   * card chrome + larger title so it reads as a sub-block of one
   * surface, not a third stacked card. */
  embedded?: boolean;
}) {
  const total = items.length;
  const done = items.filter((i) => i.done).length;
  const allDone = total > 0 && done === total;

  const Wrapper = embedded ? "div" : "section";
  return (
    <Wrapper
      className={cn(
        !embedded && "rounded-2xl border p-4 transition-colors",
        !embedded && (allDone
          ? "border-emerald-200 bg-emerald-50"
          : "border-[var(--color-edify-divider)] bg-white"),
      )}
    >
      <header className="flex items-center gap-2">
        {!embedded ? (
          <span
            className={cn(
              "w-6 h-6 rounded-md grid place-items-center",
              allDone
                ? "bg-emerald-100 text-emerald-700"
                : "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
            )}
          >
            <ListChecks size={13} />
          </span>
        ) : null}
        <h3 className={cn(
          embedded ? "section-h-micro" : "text-[13px] font-extrabold tracking-tight",
          embedded && allDone && "text-emerald-700",
        )}>
          {allDone ? "Done for Today — you've cleared the bar." : "Done for Today"}
        </h3>
        <span className={cn(
          "ml-auto text-[11px] font-bold tabular",
          embedded ? "text-muted" : "text-[var(--color-edify-muted)]",
        )}>
          {done} / {total}
        </span>
      </header>
      <motion.ul
        className="mt-3 space-y-2"
        variants={staggerContainer(0.04, stagger.row)}
        initial="hidden"
        animate="visible"
      >
        {items.map((item) => (
          <motion.li
            key={item.id}
            variants={fadeUp}
            className="flex items-start gap-2.5"
          >
            {item.done ? (
              <CheckCircle2 size={14} className="text-emerald-600 mt-[2px] shrink-0" />
            ) : (
              <Circle size={14} className="text-[var(--color-edify-muted)] mt-[2px] shrink-0" />
            )}
            <div className="flex-1 min-w-0">
              <p className={cn(
                "text-body font-semibold leading-snug",
                item.done ? "text-emerald-800 line-through decoration-emerald-300" : "text-[var(--color-edify-text)]",
              )}>
                {item.label}
              </p>
              {item.detail ? (
                <p className="text-[11px] text-[var(--color-edify-muted)] mt-0.5">
                  {item.detail}
                </p>
              ) : null}
            </div>
          </motion.li>
        ))}
      </motion.ul>
    </Wrapper>
  );
}
