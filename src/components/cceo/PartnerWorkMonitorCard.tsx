// PartnerWorkMonitorCard — CCEO partner-work monitoring (spec §15).
//
// Server component, standalone — the dashboard owner mounts it. Shows,
// scoped to the CCEO's schools/clusters, the six monitor buckets from
// the partner-work engine (src/lib/cceo/partner-work.ts) as a compact
// count strip, plus the 3 most urgent rows with one action link each.
//
// Action links land on the LIVE review surfaces:
//   • evidence review → /my-targets (StaffPartnerMonitoring's
//     Confirm / Return / Reject row actions — the real CCEO flow)
//   • Salesforce ID   → /queue (Salesforce completion queue)
//   • View all        → /partners (CCEO monitor section)

import Link from "next/link";
import { ArrowUpRight, Handshake } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { SectionCard } from "@/components/ui/primitives";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import { buildPartnerWork, fmtUgx } from "@/lib/cceo/partner-work";

export async function PartnerWorkMonitorCard() {
  const user = await getCurrentUser();
  const work = buildPartnerWork(user);

  // Six buckets → one dense strip. Each cell deep-links into the
  // matching filtered list on /partners.
  const cells: MetricCell[] = work.buckets.map((b) => ({
    key: b.key,
    label: b.label,
    value: b.count,
    caption:
      b.key === "paymentPipeline" && work.payment.totalUgx > 0
        ? fmtUgx(work.payment.totalUgx)
        : b.actionLabel,
    tone: b.tone,
    href: `/partners?bucket=${b.key}`,
  }));

  return (
    <SectionCard
      icon={<Handshake size={13} />}
      title="Partner Work Monitor"
      subtitle={`${work.totalOpen} open partner activities you assigned — schedule → evidence → payment`}
      actions={
        <Link
          href="/partners"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View All
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      <MetricStrip
        metrics={cells}
        columns="grid-cols-2 sm:grid-cols-3 xl:grid-cols-6"
        className="shadow-none border border-[var(--color-edify-border)]"
      />

      {/* The 3 most urgent rows — delayed work first, then the review
          queue that gates partner payment. */}
      {work.urgent.length > 0 && (
        <div className="mt-3 rounded-xl border border-[var(--color-edify-border)] bg-white overflow-hidden divide-y divide-[var(--color-edify-divider)]">
          {work.urgent.map((u) => (
            <div key={u.id} className="flex items-center gap-3 px-3 py-2.5">
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2 min-w-0">
                  <span className="text-[12px] font-extrabold tracking-tight truncate">
                    {u.school}
                  </span>
                  <span className="text-[10.5px] muted truncate shrink-0">{u.partner}</span>
                </div>
                <div className="text-[11px] muted leading-snug truncate mt-0.5">{u.reason}</div>
              </div>
              <div className="text-[10.5px] font-semibold tabular muted whitespace-nowrap shrink-0">
                {u.due}
              </div>
              <Link
                href={u.actionHref}
                className="inline-flex items-center justify-center h-7 px-2.5 rounded-md text-[11px] font-extrabold whitespace-nowrap shrink-0 bg-[var(--color-edify-primary)] text-white hover:opacity-95"
              >
                {u.actionLabel}
              </Link>
            </div>
          ))}
        </div>
      )}

      <div className="mt-3 pt-2.5 border-t border-[var(--color-edify-divider)] text-[11px] muted">
        Your Confirm / Return decision gates partner payment — review evidence on{" "}
        <Link href="/my-targets" className="font-semibold text-[var(--color-edify-primary)]">
          My Targets
        </Link>
        .
      </div>
    </SectionCard>
  );
}
