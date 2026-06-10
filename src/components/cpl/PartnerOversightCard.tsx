import Link from "next/link";
import { ArrowUpRight, Handshake } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import { plQueue, fmtUgx } from "@/lib/partner/partner-payment-requests-mock";
import { partnerTargetPerformance } from "@/lib/team-targets-mock";
import { cn } from "@/lib/utils";

// Partner Oversight — partner work as it affects the PL's team. The PL
// monitors and intervenes (and escalates performance issues to the CD);
// onboarding/activation stays with the CD. Payments awaiting the PL are
// the urgent slice; delivery risk is the coaching slice.

export function PartnerOversightCard() {
  const payments = plQueue();
  const paymentsTotal = payments.reduce((a, p) => a + p.totalUgx, 0);
  const partners = partnerTargetPerformance;
  const atRisk = partners.filter((p) => p.risk === "High" || p.risk === "Critical");
  const assigned = partners.reduce((a, p) => a + p.assignedActivities, 0);
  const completed = partners.reduce((a, p) => a + p.completedActivities, 0);
  const evidenceIncomplete = payments.filter((p) => !p.evidenceComplete).length;

  const metrics: MetricCell[] = [
    { key: "pay",     label: "Payments awaiting you", value: payments.length, tone: payments.length ? "alert" : "default", caption: fmtUgx(paymentsTotal) },
    { key: "evid",    label: "Evidence incomplete",   value: evidenceIncomplete, tone: evidenceIncomplete ? "alert" : "default" },
    { key: "assigned", label: "Activities assigned",  value: assigned.toLocaleString() },
    { key: "done",    label: "Completed",             value: completed.toLocaleString(), caption: assigned ? `${Math.round((completed / assigned) * 100)}%` : undefined },
    { key: "risk",    label: "Partners at risk",      value: atRisk.length, tone: atRisk.length ? "alert" : "default" },
  ];

  return (
    <SectionCard
      icon={<Handshake size={13} />}
      title="Partner Work Needing Attention"
      actions={
        <Link href="/partners" className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline">
          All partners <ArrowUpRight size={12} />
        </Link>
      }
    >
      <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-3 xl:grid-cols-5" />

      {payments.length > 0 && (
        <ul className="mt-2.5 divide-y divide-[var(--color-edify-divider)]">
          {payments.map((p) => (
            <li key={p.id} className="flex items-center gap-3 py-2">
              <span className="grid place-items-center h-7 w-7 rounded-full bg-[var(--color-edify-soft)] text-[10px] font-extrabold shrink-0">
                {p.partnerOrgInitials}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[12.5px] font-bold tracking-tight truncate">{p.partner}</div>
                <div className="text-[11px] muted truncate">
                  {p.activitiesCount} activities · {p.schools.length} schools · confirmed by {p.confirmedBy}
                </div>
              </div>
              <span
                className={cn(
                  "shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-extrabold",
                  p.evidenceComplete
                    ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                    : "bg-amber-50 text-amber-700 border-amber-200",
                )}
              >
                {p.evidenceComplete ? "Evidence complete" : "Evidence incomplete"}
              </span>
              <span className="shrink-0 text-[12px] font-extrabold tabular">{fmtUgx(p.totalUgx)}</span>
            </li>
          ))}
        </ul>
      )}

      {atRisk.length > 0 && (
        <p className="mt-2 text-[11.5px] leading-snug">
          <span className="font-bold">Delivery risk:</span>{" "}
          {atRisk.map((p) => `${p.partner} (${p.achievementPercent}%)`).join(", ")} —{" "}
          intervene on overdue work first;{" "}
          <Link href="/messages" className="underline font-semibold">
            escalate to the CD
          </Link>{" "}
          if quality does not recover. Partner onboarding stays with the CD.
        </p>
      )}
    </SectionCard>
  );
}
