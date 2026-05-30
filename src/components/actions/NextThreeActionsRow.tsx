"use client";

// NextThreeActionsRow — the headline 10-second decision surface.
//
// Three big cards, side-by-side at desktop, stacked on mobile. Each
// card is a full ActionCard in "hero" variant — full title, full
// reason, primary + secondary CTA. The whole point of this section:
// a CCEO logging in at 7:30am sees exactly three things to act on.
//
// Motion stagger so the row reveals with the same rhythm as the rest
// of the CPL dashboard (Leadership Attention uses the same).

import { motion } from "motion/react";
import { Target } from "lucide-react";
import type { ActionItem } from "@/lib/actions/action-types";
import { ActionCard } from "./ActionCard";
import { fadeUp, spring, stagger, staggerContainer } from "@/lib/motion";

export function NextThreeActionsRow({ items }: { items: ActionItem[] }) {
  if (items.length === 0) {
    return (
      <section className="rounded-2xl border border-[var(--color-edify-divider)] bg-white p-5 text-center">
        <p className="text-[13px] font-bold text-[var(--color-edify-text)]">Nothing urgent on your queue.</p>
        <p className="text-[12px] text-[var(--color-edify-muted)] mt-1">
          Quiet days are real. The inbox below has follow-ups when you&apos;re ready.
        </p>
      </section>
    );
  }
  return (
    <section>
      <div className="flex items-center gap-2 mb-3 px-1">
        <span className="w-6 h-6 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center">
          <Target size={13} />
        </span>
        <h2 className="text-[13px] font-extrabold tracking-tight uppercase letter-spacing-wide text-[var(--color-edify-text)]">
          Next 3 Actions
        </h2>
        <span className="text-[11px] text-[var(--color-edify-muted)] ml-1">
          · Ranked by what unlocks the most downstream
        </span>
      </div>
      <motion.div
        className="grid grid-cols-1 md:grid-cols-3 gap-3 md:gap-4 items-stretch"
        variants={staggerContainer(0.06, stagger.row)}
        initial="hidden"
        animate="visible"
      >
        {items.map((item) => (
          <motion.div key={item.id} variants={fadeUp} transition={spring.soft}>
            <ActionCard item={item} variant="hero" />
          </motion.div>
        ))}
      </motion.div>
    </section>
  );
}
