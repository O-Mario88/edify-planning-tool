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
import { buildPartnerWorkContext } from "@/lib/cceo/partner-work-context";

export async function PartnerWorkMonitorCard() {
  const user = await getCurrentUser();
  const work = buildPartnerWork(user);
  const ctx  = buildPartnerWorkContext(user);

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

      {ctx.capacity && (ctx.capacity.atLimit || ctx.capacity.nearLimit) && (
        <div className="mt-3 rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-[11px] leading-snug">
          <span className="font-extrabold text-amber-900">
            You support {ctx.capacity.used} of {ctx.capacity.max} schools directly.
          </span>{" "}
          <span className="text-amber-900/80">
            {ctx.capacity.atLimit
              ? "You're at your direct-support limit — partner delegation is the route for any NEW school until a slot frees up."
              : "You're near your direct-support limit — consider partner delegation for the next new school."}
          </span>
        </div>
      )}

      {ctx.clusterGate && (ctx.clusterGate.unclustered > 0 || ctx.clusterGate.needsReview > 0) && (
        <div className="mt-2 rounded-md bg-sky-50 border border-sky-200 px-3 py-2 text-[11px] leading-snug flex items-start justify-between gap-2">
          <span>
            <span className="font-extrabold text-sky-900">
              {ctx.clusterGate.unclustered + ctx.clusterGate.needsReview} school
              {ctx.clusterGate.unclustered + ctx.clusterGate.needsReview === 1 ? "" : "s"} blocked at the cluster gate.
            </span>{" "}
            <span className="text-sky-900/80">
              Planning is locked until they're assigned to a cluster — neither you nor a partner can pick them up.
            </span>
          </span>
          <Link
            href="/clusters/assign"
            className="shrink-0 inline-flex items-center gap-1 text-[11px] font-extrabold text-sky-900 hover:underline whitespace-nowrap"
          >
            Assign clusters
            <ArrowUpRight size={11} />
          </Link>
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
