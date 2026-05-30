// PartnerWorkflowTracker — horizontal pipeline showing the full 8-step
// flow with a count badge per step. Sits near the top of the Partner
// Delivery Command Center so the partner always knows where each
// activity stands and what their next move is.
//
// The bar reads left-to-right; partner-side steps are filled, downstream
// (CCEO / PL / Accountant) steps are muted so the partner can see the
// system at work without thinking the inactive steps are their job.

import {
  Handshake, Calendar, ClipboardCheck, Upload, ShieldCheck, CheckCircle,
  Send, Wallet, type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

export type WorkflowStepKey =
  | "assigned" | "scheduled" | "delivered" | "evidence"
  | "cceo" | "plApproval" | "accountant" | "paid";

export type WorkflowStepCount = { key: WorkflowStepKey; count: number };

const STEPS: { key: WorkflowStepKey; label: string; Icon: LucideIcon; owner: "partner" | "edify" }[] = [
  { key: "assigned",   label: "Assigned",        Icon: Handshake,      owner: "partner" },
  { key: "scheduled",  label: "Scheduled",       Icon: Calendar,       owner: "partner" },
  { key: "delivered",  label: "Delivered",       Icon: ClipboardCheck, owner: "partner" },
  { key: "evidence",   label: "Evidence",        Icon: Upload,         owner: "partner" },
  { key: "cceo",       label: "CCEO Confirmed",  Icon: ShieldCheck,    owner: "edify"   },
  { key: "plApproval", label: "PL Approved",     Icon: CheckCircle,    owner: "edify"   },
  { key: "accountant", label: "To Accountant",   Icon: Send,           owner: "edify"   },
  { key: "paid",       label: "Paid",            Icon: Wallet,         owner: "edify"   },
];

export function PartnerWorkflowTracker({
  counts,
}: {
  counts: WorkflowStepCount[];
}) {
  const byKey: Record<WorkflowStepKey, number> = Object.fromEntries(
    STEPS.map((s) => [s.key, 0]),
  ) as Record<WorkflowStepKey, number>;
  for (const c of counts) byKey[c.key] = c.count;

  return (
    <section className="card p-3.5">
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <h3 className="text-[13px] font-extrabold tracking-tight">Activity Workflow</h3>
          <p className="text-[11.5px] muted mt-0.5">
            Every assigned activity moves left to right. Steps you own are filled; downstream steps follow automatically.
          </p>
        </div>
        <span className="text-caption uppercase tracking-wide font-bold text-[var(--color-edify-muted)]">
          Total in flight · {Object.values(byKey).reduce((a, b) => a + b, 0)}
        </span>
      </div>

      {/* Steps */}
      <div className="overflow-x-auto scrollbar -mx-1 px-1">
        <ol className="flex items-stretch gap-0 min-w-[760px]">
          {STEPS.map((step, i) => {
            const isLast = i === STEPS.length - 1;
            const filled = byKey[step.key] > 0;
            const ownsIt = step.owner === "partner";
            return (
              <li key={step.key} className="flex-1 flex items-stretch min-w-0">
                {/* Node */}
                <div className="flex flex-col items-center text-center px-1.5 min-w-0 flex-1">
                  <span
                    className={cn(
                      "grid place-items-center h-9 w-9 rounded-full border-2 transition-colors",
                      filled
                        ? ownsIt
                          ? "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)] shadow-[0_0_12px_-2px_rgba(82,112,131,0.45)]"
                          : "bg-emerald-500 text-white border-emerald-500 shadow-[0_0_12px_-2px_rgba(16,185,129,0.45)]"
                        // Empty step — use surface-2 (visible against both
                        // the white light-mode card AND the dark/glass card
                        // surfaces). bg-white was invisible in dark/glass
                        // because it retargets to the same colour as the
                        // card behind it.
                        : "bg-[var(--surface-2)] text-[var(--color-edify-muted)] border-[var(--color-edify-border)]",
                    )}
                  >
                    <step.Icon size={14} />
                  </span>
                  {/* Label: small + medium-weight, NOT uppercase. The
                      previous extrabold-uppercase combo read as a
                      headline even at 11px, fighting the KPI strip
                      above. Title-case + medium weight calms it down
                      and makes the count the visual anchor. */}
                  <div className={cn(
                    "text-tiny font-semibold tracking-tight mt-1.5 leading-tight min-h-[20px] flex items-start justify-center",
                    filled ? "text-[var(--color-edify-text)]" : "text-[var(--color-edify-muted)]",
                  )}>
                    {step.label}
                  </div>
                  <div className={cn(
                    "text-body font-extrabold tabular num-hero mt-0.5 leading-none",
                    filled
                      ? ownsIt
                        ? "text-[var(--color-edify-primary)]"
                        : "text-emerald-700"
                      : "text-[var(--color-edify-muted)] opacity-70",
                  )}>
                    {byKey[step.key]}
                  </div>
                </div>
                {/* Connector — kept thin but bumped opacity so it reads
                    on every theme. The filled variant carries the brand
                    primary tint so the "active flow" reads across the
                    pipeline at a glance. */}
                {!isLast && (
                  <div className="flex items-center pt-[18px] shrink-0 w-4">
                    <div className={cn(
                      "h-[2px] w-full rounded-full",
                      filled
                        ? ownsIt
                          ? "bg-[var(--color-edify-primary)]/60"
                          : "bg-emerald-500/55"
                        : "bg-[var(--color-edify-border)]",
                    )} />
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}
