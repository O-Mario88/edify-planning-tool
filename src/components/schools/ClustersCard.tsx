"use client";

import Link from "next/link";
import { Layers, MapPin, ArrowRight } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { type Cluster } from "@/lib/schools-mock";

// Saved clusters for the current CCEO. Created from the School Directory's
// Cluster Filters / Create Cluster flow. The Planning Tool reads from this
// list when scheduling visits or trainings — it never creates clusters.
export function ClustersCard({ clusters }: { clusters: Cluster[] }) {
  return (
    <SectionCard
      icon={<Layers size={13} />}
      title="My Clusters"
      subtitle="Saved cluster groups · used by the Planning Tool when scheduling visits / trainings."
      actions={
        <Link
          href="/clusters"
          className="text-[12px] font-semibold text-[var(--color-edify-primary)]"
        >
          Manage clusters →
        </Link>
      }
    >
      {clusters.length === 0 ? (
        <div className="text-[12px] muted text-center py-6">
          No clusters yet. Filter the directory above and click{" "}
          <span className="font-semibold text-[var(--color-edify-text)]">Create Cluster</span>.
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-3">
          {clusters.map((c) => (
            <div
              key={c.id}
              className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3 hover:bg-[var(--color-edify-soft)]/40 transition-colors"
            >
              <div className="flex items-start gap-2">
                <span className="w-7 h-7 rounded-md grid place-items-center bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
                  <Layers size={13} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-body font-bold leading-tight truncate">{c.name}</div>
                  <div className="text-caption muted truncate mt-0.5">
                    {c.schoolIds.length} schools · created {c.createdAt}
                  </div>
                </div>
              </div>

              <div className="mt-2 flex flex-wrap gap-1.5 text-caption">
                {c.shippingAddress && (
                  <span className="inline-flex items-center gap-1 px-2 py-[2px] rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-dark)] font-semibold">
                    <MapPin size={9} />
                    {c.shippingAddress}
                  </span>
                )}
                {c.district && (
                  <span className="inline-flex items-center px-2 py-[2px] rounded-md bg-blue-100 text-[#1e40af] font-semibold">
                    {c.district} District
                  </span>
                )}
                {c.region && (
                  <span className="inline-flex items-center px-2 py-[2px] rounded-md bg-violet-100 text-violet-700 font-semibold">
                    {c.region}
                  </span>
                )}
              </div>

              {c.description && (
                <div className="text-[11px] muted mt-2 leading-snug line-clamp-2">
                  {c.description}
                </div>
              )}

              <Link
                href={`/planning?cluster=${c.id}`}
                className="inline-flex items-center gap-1 mt-2 text-[11.5px] font-semibold text-[var(--color-edify-primary)]"
              >
                Schedule in Planning Tool
                <ArrowRight size={11} />
              </Link>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}
