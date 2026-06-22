import Link from "next/link";
import { ArrowUpRight, Handshake } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import { getCurrentUser } from "@/lib/auth";
import { fetchPartners } from "@/lib/api/surfaces";
import { isMockAllowed } from "@/lib/mock-policy";
import { PartnerPerformanceSummary } from "./PartnerPerformanceSummary";
import { cn } from "@/lib/utils";

export async function PartnerPerformanceLive() {
  if (isMockAllowed()) return <PartnerPerformanceSummary />;

  const user = await getCurrentUser();
  const r = await fetchPartners(user);
  if (!r.live) {
    return (
      <SectionCard icon={<Handshake size={13} />} title="Partner Performance">
        <p className="text-[12px] muted">Partner data unavailable — check backend connection.</p>
      </SectionCard>
    );
  }

  const rows = r.data;
  const certified = rows.filter((p) => p.isCertified || p.certificationStatus === "Certified").length;
  const metrics: MetricCell[] = [
    { key: "active", label: "Active partners", value: rows.length },
    { key: "cert", label: "Certified", value: certified, tone: certified ? "good" : "default" },
    { key: "pending", label: "Pending cert", value: rows.length - certified, tone: rows.length - certified ? "alert" : "default" },
  ];

  return (
    <SectionCard
      icon={<Handshake size={13} />}
      title="Partner Performance"
      actions={
        <Link href="/partners" className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline">
          Manage partners <ArrowUpRight size={12} />
        </Link>
      }
    >
      <MetricStrip metrics={metrics} columns="grid-cols-3" />
      <ul className="mt-2.5 divide-y divide-[var(--color-edify-divider)]">
        {rows.slice(0, 5).map((p) => (
          <li key={p.id} className="flex items-center gap-3 py-2">
            <div className="min-w-0 flex-1">
              <div className="text-[12.5px] font-bold tracking-tight truncate">{p.name}</div>
              <div className="text-[11px] muted truncate">{p.regionName ?? "—"}</div>
            </div>
            <span className={cn(
              "shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-extrabold",
              p.isCertified ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-amber-50 text-amber-700 border-amber-200",
            )}>
              {p.isCertified ? "Certified" : "Pending"}
            </span>
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}
