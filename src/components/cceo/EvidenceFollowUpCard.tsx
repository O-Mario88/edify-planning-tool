// EvidenceFollowUpCard — CCEO dashboard summary of the four /evidence
// guided queues (spec §16): Evidence Required, Salesforce ID Required,
// IA Returned, Accountability Pending.
//
// Server component (no "use client") — it reads the shared derivation in
// src/lib/cceo/evidence-queues.ts directly. Standalone and unmounted by
// design: the dashboard owner mounts <EvidenceFollowUpCard /> on
// /dashboards/cceo when ready. Scoped to the signed-in user, so it only
// renders meaningfully for a CCEO session.

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { buildEvidenceQueues } from "@/lib/cceo/evidence-queues";
import { cn } from "@/lib/utils";

type CardUser = { staffId: string };

const ROWS = [
  { key: "evidence" as const,       label: "Evidence required",      hint: "completed, no evidence",       hash: "#evidence-required" },
  { key: "salesforce" as const,     label: "Salesforce ID required", hint: "evidence done, no SVE-/TS-",   hash: "#salesforce-id-required" },
  { key: "returned" as const,       label: "IA returned",            hint: "fix & resubmit",               hash: "#ia-returned" },
  { key: "accountability" as const, label: "Accountability pending", hint: "disbursed, not closed",        hash: "#accountability-pending" },
];

export async function EvidenceFollowUpCard({ user }: { user?: CardUser } = {}) {
  // The dashboard can pass its already-resolved user to skip a second
  // cookie read; standalone mounts resolve the session themselves.
  const resolved = user ?? (await getCurrentUser());
  const { counts } = buildEvidenceQueues(resolved);

  return (
    <section className="card p-3.5 rounded-2xl">
      <header className="flex items-start justify-between gap-3 mb-2.5">
        <div className="min-w-0">
          <h2 className="text-[13px] font-extrabold tracking-tight">Evidence &amp; Accountability</h2>
          <p className="text-[11.5px] muted mt-0.5 leading-snug">
            {counts.total === 0
              ? "All your completed work is clean — nothing blocked."
              : `${counts.total} item${counts.total === 1 ? "" : "s"} blocked before they can count.`}
          </p>
        </div>
        <Link
          href="/evidence"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline whitespace-nowrap shrink-0"
        >
          Open queues <ArrowRight size={12} />
        </Link>
      </header>

      <ul className="divide-y divide-[var(--color-edify-divider)]">
        {ROWS.map((row) => {
          const count = counts[row.key];
          return (
            <li key={row.key}>
              <Link
                href={`/evidence${row.hash}`}
                className="flex items-center gap-2 py-2 first:pt-0 last:pb-0 group"
              >
                <span className="flex-1 min-w-0">
                  <span className="block text-[12.5px] font-semibold group-hover:text-[var(--color-edify-primary)] transition-colors">
                    {row.label}
                  </span>
                  <span className="block text-[10.5px] muted">{row.hint}</span>
                </span>
                <span
                  className={cn(
                    "px-2 py-0.5 rounded-full text-[11px] font-extrabold tabular",
                    count > 0 ? "bg-amber-100 text-amber-700" : "bg-emerald-100 text-emerald-700",
                  )}
                >
                  {count}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export default EvidenceFollowUpCard;
