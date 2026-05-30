"use client";

import { motion, useReducedMotion } from "motion/react";
import { Users, Database, AlertTriangle, ArrowRight, Bell } from "lucide-react";
import { cplLeadershipAlerts, type CplAlert } from "@/lib/cpl-mock";
import { cn } from "@/lib/utils";
import { fadeUp, spring, stagger, staggerContainer } from "@/lib/motion";

const iconMap = {
  users: Users,
  database: Database,
  alertTriangle: AlertTriangle,
} as const;

// 4-tone discipline: decorative `blue` collapses into `edify`
// (informational brand-neutral). `red` paints as rose-critical and
// `amber` stays as the pending warning tone.
const toneFrame: Record<CplAlert["tone"], string> = {
  amber: "bg-[#fff7ed] border-[#fed7aa]",
  red:   "bg-[#fef2f2] border-[#fecaca]",
  blue:  "bg-[var(--color-edify-soft)] border-[var(--color-edify-border)]",
};
const toneIcon: Record<CplAlert["tone"], string> = {
  amber: "bg-orange-100 text-[#9a3412]",
  red:   "bg-red-100 text-red-700",
  blue:  "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
};

export function CplLeadershipAttentionRow() {
  const reduce = useReducedMotion();
  return (
    <section className="card p-3">
      <div className="flex items-center gap-2 mb-2 pl-1">
        <span className="w-6 h-6 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center">
          <Bell size={13} />
        </span>
        <h3 className="text-body font-bold">Where your attention earns the most</h3>
        <a className="ml-auto text-[11.5px] font-semibold text-[var(--color-edify-primary)]" href="#alerts">
          View All →
        </a>
      </div>
      <motion.div
        className="grid grid-cols-1 sm:grid-cols-3 gap-2.5"
        variants={staggerContainer(0.08, stagger.row)}
        initial="hidden"
        animate="visible"
      >
        {cplLeadershipAlerts.map((a) => {
          const Icon = iconMap[a.icon];
          return (
            <motion.div
              key={a.id}
              variants={fadeUp}
              transition={reduce ? { duration: 0 } : spring.soft}
              whileHover={reduce ? undefined : { y: -2, transition: spring.hover }}
              className={cn("rounded-xl border px-3 py-2.5 flex items-start gap-2.5", toneFrame[a.tone])}
            >
              <span
                className={cn("w-7 h-7 rounded-md grid place-items-center mt-0.5 shrink-0", toneIcon[a.tone])}
              >
                <Icon size={13} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-[12px] font-bold leading-tight line-clamp-1">{a.title}</div>
                <div className="text-[11px] muted mt-0.5 line-clamp-2 leading-snug">{a.body}</div>
                <a
                  href={a.href}
                  className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-edify-primary)] mt-1"
                >
                  {a.cta}
                  <ArrowRight size={10} />
                </a>
              </div>
            </motion.div>
          );
        })}
      </motion.div>
    </section>
  );
}
