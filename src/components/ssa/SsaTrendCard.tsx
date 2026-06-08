"use client";

import { TrendingUp } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { EmptyState } from "@/components/ui/DataStates";

// SSA performance trend by quarter. The backend exposes no quarterly SSA
// time-series yet (only current-FY grouped averages and prev-vs-current
// improvement), so this surface shows an honest empty state rather than mock
// data. It will light up when a quarterly trend endpoint exists.
export function SsaTrendCard() {
  return (
    <SectionCard
      icon={<TrendingUp size={13} />}
      title="SSA Performance Trend by Quarter"
      subtitle="Quarterly SSA average — track progress across recent quarters"
    >
      <EmptyState
        compact
        icon={TrendingUp}
        title="No quarterly trend yet"
        message="A quarterly SSA time-series will appear here once enough assessments are recorded across quarters."
      />
    </SectionCard>
  );
}
