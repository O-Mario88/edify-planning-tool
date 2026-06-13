"use client";

import { ClipboardList } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { type PlanningSignal } from "@/lib/schools-mock";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

const TONE: Record<PlanningSignal["tone"], MetricCell["tone"]> = {
  edify:  "default",
  amber:  "default",
  violet: "default",
  rose:   "alert",
  red:    "alert",
  blue:   "default",
};

export function PlanningReviewSignals({ signals }: { signals: PlanningSignal[] }) {
  return (
    <SectionCard
      icon={<ClipboardList size={13} />}
      title="Planning & Review Signals"
    >
      <MetricStrip
        bare
        columns="grid-cols-6"
        metrics={signals.map((s) => ({
          key: s.key,
          label: s.label,
          value: s.value,
          tone: TONE[s.tone],
        }))}
      />
    </SectionCard>
  );
}
