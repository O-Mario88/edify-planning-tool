// Compact "clusters I manage" card for the partner dashboard. Renders nothing
// when the partner has no delegated clusters, so it never adds noise.

import Link from "next/link";
import { Network, ArrowRight, CalendarDays } from "lucide-react";
import { getCurrentPartner } from "@/lib/partner/partner-identity";
import { clustersManagedByPartner, meetingsForCluster } from "@/lib/cluster/cluster-core";

export async function PartnerClustersSummaryCard() {
  const partner = await getCurrentPartner();
  if (!partner) return null;
  const clusters = clustersManagedByPartner(partner.id);
  if (clusters.length === 0) return null;

  const meetingTotal = clusters.reduce((n, c) => n + meetingsForCluster(c.id).length, 0);

  return (
    <Link
      href="/partner/clusters"
      className="group flex items-center gap-3 rounded-2xl border border-[var(--color-edify-border)] bg-white px-4 py-3 hover:bg-[var(--color-edify-soft)]/40 transition-colors"
    >
      <span className="grid place-items-center h-10 w-10 rounded-xl bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
        <Network size={18} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-extrabold tracking-tight">
          {clusters.length} cluster{clusters.length === 1 ? "" : "s"} delegated to you
        </div>
        <p className="text-[12px] muted inline-flex items-center gap-1 mt-0.5">
          <CalendarDays size={11} className="text-[var(--color-edify-primary)]" />
          {meetingTotal} meeting{meetingTotal === 1 ? "" : "s"} scheduled — manage &amp; schedule cluster meetings
        </p>
      </div>
      <span className="shrink-0 inline-flex items-center gap-1.5 text-[12px] font-extrabold text-[var(--color-edify-primary)] group-hover:gap-2 transition-all">
        Manage <ArrowRight size={13} />
      </span>
    </Link>
  );
}
