"use client";

// Rebalance Recommendations — the leadership *intervention* surface.
//
// Measurement systems that only score people are punitive. This card
// turns the FWI math into action: "Daniel carries 2.4× the median
// load; here are 2 schools we'd suggest moving to Sarah, and here's
// what both staff would look like after."
//
// Each card has a single "Accept" CTA that (in production) opens a
// confirmation flow + writes the move to the audit log. In the demo
// it just toasts so the visual demonstrates the loop.

import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";
import { ArrowRight, Scale, Check, Loader2 } from "lucide-react";
import { fadeUp, spring, staggerContainer } from "@/lib/motion";
import { useDemoStore } from "@/components/demo/DemoStore";
import type { RebalanceRecommendation } from "@/lib/performance/fwi-types";

export function RebalanceRecommendationsCard({
  recs,
}: {
  recs: RebalanceRecommendation[];
}) {
  const { pushToast } = useDemoStore();
  const reduce = useReducedMotion();
  const [acting, setActing] = useState<string | null>(null);
  const [acted, setActed] = useState<Set<string>>(new Set());

  function recKey(r: RebalanceRecommendation): string {
    return `${r.fromStaffId}->${r.toStaffId}`;
  }

  function handleAccept(r: RebalanceRecommendation) {
    const k = recKey(r);
    setActing(k);
    window.setTimeout(() => {
      setActing(null);
      setActed((prev) => new Set(prev).add(k));
      pushToast({
        tone: "success",
        title: `Reassignment queued`,
        body: `${r.schoolNames.length} school${r.schoolNames.length === 1 ? "" : "s"} moving from ${r.fromStaffName} to ${r.toStaffName}. Both staff notified.`,
      });
    }, 500);
  }

  return (
    <section className="card p-3.5 sm:p-5">
      <header className="flex items-start gap-3 mb-3">
        <div className="w-9 h-9 rounded-xl bg-amber-50 grid place-items-center text-amber-600 shrink-0">
          <Scale size={16} />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-[15px] font-extrabold tracking-tight">Portfolio rebalance suggestions</h3>
          <p className="text-[12px] muted leading-snug mt-0.5">
            When portfolios drift out of balance, fairness suffers. These are the moves we&apos;d make to bring loads back in line — your call on each.
          </p>
        </div>
      </header>

      {recs.length === 0 ? (
        <div className="rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/30 p-4 text-center">
          <p className="text-[13px] font-semibold text-[var(--color-edify-text)]">Portfolios are balanced. No moves recommended.</p>
          <p className="text-[11.5px] muted mt-1">The team&apos;s load distribution is within tolerance. We&apos;ll re-check next period.</p>
        </div>
      ) : (
        <motion.ul
          className="space-y-2.5"
          variants={staggerContainer(0.04, 0.05)}
          initial="hidden"
          animate="visible"
        >
          {recs.map((r) => {
            const k = recKey(r);
            const isActing = acting === k;
            const isActed = acted.has(k);
            return (
              <motion.li
                key={k}
                variants={fadeUp}
                transition={reduce ? { duration: 0 } : spring.soft}
                className="rounded-xl border border-[var(--color-edify-border)] bg-white px-3 py-3"
              >
                {/* From → To with load deltas */}
                <div className="flex items-center gap-2 flex-wrap">
                  <LoadPill
                    name={r.fromStaffName}
                    before={r.fromLoadBefore}
                    after={r.fromLoadAfter}
                    direction="down"
                  />
                  <ArrowRight size={14} className="text-[var(--color-edify-muted)]" />
                  <LoadPill
                    name={r.toStaffName}
                    before={r.toLoadBefore}
                    after={r.toLoadAfter}
                    direction="up"
                  />
                </div>

                {/* Schools to move */}
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {r.schoolNames.map((name) => (
                    <span
                      key={name}
                      className="inline-flex items-center px-2 py-[2px] rounded-md text-caption font-semibold bg-sky-50 text-sky-800 border border-sky-200"
                    >
                      {name}
                    </span>
                  ))}
                </div>

                {/* Reason */}
                <p className="text-[11.5px] muted mt-2 leading-snug">{r.reason}</p>

                {/* Actions */}
                <div className="mt-2.5 flex items-center justify-end gap-1.5">
                  <button
                    type="button"
                    className="h-7 px-2.5 rounded-md text-[11px] font-semibold border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/60 disabled:opacity-55"
                    disabled={isActed || isActing}
                  >
                    Dismiss
                  </button>
                  {isActed ? (
                    <motion.span
                      initial={reduce ? false : { scale: 0.7, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      transition={reduce ? { duration: 0 } : spring.pop}
                      className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md text-[11px] font-bold bg-emerald-100 text-emerald-700"
                    >
                      <Check size={11} />
                      Reassignment queued
                    </motion.span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handleAccept(r)}
                      disabled={isActing}
                      className="inline-flex items-center justify-center gap-1 h-7 px-2.5 rounded-md text-[11px] font-semibold bg-[var(--color-edify-primary)] text-white hover:opacity-90 disabled:opacity-55"
                    >
                      {isActing ? <Loader2 size={11} className="animate-spin" /> : null}
                      Accept move
                    </button>
                  )}
                </div>
              </motion.li>
            );
          })}
        </motion.ul>
      )}
    </section>
  );
}

function LoadPill({
  name,
  before,
  after,
  direction,
}: {
  name: string;
  before: number;
  after: number;
  direction: "up" | "down";
}) {
  const dirIcon = direction === "down" ? "↓" : "↑";
  const toneCls = direction === "down"
    ? "bg-amber-50 text-amber-800 border-amber-200"
    : "bg-sky-50 text-sky-800 border-sky-200";
  return (
    <span className={`inline-flex items-baseline gap-1.5 px-2.5 py-1 rounded-lg border ${toneCls}`}>
      <span className="text-[12px] font-extrabold tracking-tight">{name}</span>
      <span className="text-caption font-semibold tabular">{before.toFixed(1)}</span>
      <span className="text-caption">{dirIcon}</span>
      <span className="text-caption font-extrabold tabular">{after.toFixed(1)}</span>
    </span>
  );
}
