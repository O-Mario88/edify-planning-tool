"use client";

import Link from "next/link";
import { AlertTriangle, Info } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { EmptyState } from "@/components/ui/DataStates";

// Schools requiring urgent attention — a flat, cross-district list of the
// lowest-scoring schools with a recommended action. The backend does not yet
// expose this surface (only per-group SSA averages and a per-group school
// drilldown without a recommended-action field), so this shows an honest empty
// state rather than mock data. The drillable per-district school list lives in
// the live "SSA Performance · 8 interventions" grid above.
export function UrgentInterventionSchoolsCard() {
  return (
    <SectionCard
      icon={<AlertTriangle size={13} className="text-[var(--color-danger)]" />}
      title="Schools Requiring Urgent Attention"
      actions={
        <div className="flex items-center gap-2">
          <Info size={13} className="text-[var(--color-edify-muted)]" />
          <Link className="text-[12px] font-semibold text-[var(--color-edify-primary)]" href="/schools">
            View All
          </Link>
        </div>
      }
    >
      <EmptyState
        title="No urgent-attention list yet"
        message="A cross-district list of the lowest-scoring schools will appear here once the backend exposes it. For now, drill into any district in the SSA Performance grid above to see its weakest schools."
      />
    </SectionCard>
  );
}
