// Cluster operations card for role dashboards (PL / CD / RVP). Server component
// reading the cluster lifecycle engine: meetings completed / awaiting IA /
// scheduled, attendance reached, partner payments ready, and a staff-vs-partner
// snapshot. Links into the analytics, IA queue, and payments surfaces.

import Link from "next/link";
import {
  Network, CalendarCheck, ShieldCheck, Users2, GraduationCap, Wallet, ArrowRight,
} from "lucide-react";
import { clusterMeetingMetrics, staffVsPartnerClusterComparison } from "@/lib/cluster/cluster-core";

export function ClusterOperationsCard({ scope = "team" }: { scope?: "team" | "country" | "region" }) {
  const m = clusterMeetingMetrics();
  const cmp = staffVsPartnerClusterComparison();
  const scopeLabel = scope === "country" ? "Country" : scope === "region" ? "Region" : "Team";

  const tiles = [
    { label: "Meetings confirmed", value: m.confirmed, Icon: CalendarCheck, tone: "text-emerald-500" },
    { label: "Awaiting IA", value: m.awaitingIa, Icon: ShieldCheck, tone: "text-amber-500" },
    { label: "Scheduled", value: m.scheduled, Icon: Network, tone: "text-sky-500" },
    { label: "Attendance", value: m.attendanceTotal, Icon: Users2, tone: "text-violet-500" },
    { label: "Teachers reached", value: m.teachersReached, Icon: GraduationCap, tone: "text-[var(--color-edify-primary)]" },
    { label: "Partner payments ready", value: m.partnerPaymentsReady, Icon: Wallet, tone: "text-rose-500" },
  ];

  return (
    <section className="card rounded-2xl p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[15px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <Network size={15} className="text-[var(--color-edify-primary)]" /> Cluster operations
          <span className="muted font-semibold text-[11px]">· {scopeLabel}</span>
        </h3>
        <Link href="/clusters/analytics" className="text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline inline-flex items-center gap-1">
          Analytics <ArrowRight size={12} />
        </Link>
      </div>

      <div className="mt-3 grid grid-cols-2 md:grid-cols-3 gap-2">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-xl border border-[var(--color-edify-border)] px-3 py-2.5">
            <t.Icon size={13} className={t.tone} />
            <div className="text-[18px] font-extrabold tabular tracking-tight mt-1">{t.value}</div>
            <div className="text-[10.5px] muted leading-tight">{t.label}</div>
          </div>
        ))}
      </div>

      {/* Staff vs partner snapshot */}
      <div className="mt-3 rounded-xl border border-[var(--color-edify-divider)] p-3">
        <div className="text-[11px] font-bold muted uppercase tracking-wide mb-1.5">Staff vs partner (meetings confirmed)</div>
        <div className="grid grid-cols-2 gap-2 text-[12px]">
          <div className="inline-flex items-center justify-between rounded-lg bg-sky-50 px-2.5 py-1.5">
            <span className="text-sky-700 font-semibold">Staff</span>
            <span className="font-extrabold tabular">{cmp.staff.meetingsConfirmed}</span>
          </div>
          <div className="inline-flex items-center justify-between rounded-lg bg-violet-50 px-2.5 py-1.5">
            <span className="text-violet-700 font-semibold">Partner</span>
            <span className="font-extrabold tabular">{cmp.partner.meetingsConfirmed}</span>
          </div>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-3 text-[11.5px]">
        <Link href="/data-intake/clusters" className="font-semibold text-[var(--color-edify-primary)] hover:underline inline-flex items-center gap-1">
          <ShieldCheck size={12} /> IA confirmation queue
        </Link>
        <Link href="/disbursements/cluster-payments" className="font-semibold text-[var(--color-edify-primary)] hover:underline inline-flex items-center gap-1">
          <Wallet size={12} /> Partner payments
        </Link>
      </div>
    </section>
  );
}
