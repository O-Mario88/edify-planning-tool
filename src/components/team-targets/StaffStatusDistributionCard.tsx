"use client";

import { PieChart } from "lucide-react";
import { DonutChart, SectionCard } from "@/components/ui/primitives";
import { staffStatusDistribution, totalStaffCount } from "@/lib/team-targets-mock";

export function StaffStatusDistributionCard() {
  return (
    <SectionCard icon={<PieChart size={13} />} title="Staff Target Status Distribution">
      <div className="flex items-center gap-4">
        <DonutChart
          slices={staffStatusDistribution.map((s) => ({
            label: s.label,
            value: s.count,
            pct: s.pct,
            color: s.color,
          }))}
          size={140}
          thickness={16}
        />
        <div className="flex-1 space-y-1.5 text-[11.5px]">
          {staffStatusDistribution.map((s) => (
            <div key={s.label} className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: s.color }} />
              <span className="font-semibold flex-1">{s.label}</span>
              <span className="muted tabular">{s.count} ({s.pct}%)</span>
            </div>
          ))}
        </div>
      </div>
      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[12px] flex items-center justify-between">
        <span className="muted">Total Staff:</span>
        <span className="font-extrabold tabular">{totalStaffCount}</span>
      </div>
    </SectionCard>
  );
}
