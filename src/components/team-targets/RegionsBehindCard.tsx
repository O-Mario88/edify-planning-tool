"use client";

import Link from "next/link";
import { MapPin } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { regionsBehind } from "@/lib/team-targets-mock";
import { cn } from "@/lib/utils";

const TONE: Record<"rose" | "amber" | "emerald", string> = {
  rose:    "bg-rose-500",
  amber:   "bg-amber-500",
  emerald: "bg-emerald-500",
};

export function RegionsBehindCard() {
  return (
    <SectionCard
      icon={<MapPin size={13} />}
      title="Top Regions Most Behind"
      subtitle="(Achievement %)"
    >
      <div className="space-y-2.5">
        {regionsBehind.map((r) => (
          <div key={r.region} className="grid grid-cols-[140px_1fr_44px] items-center gap-2 text-body">
            <div className="font-semibold">{r.region}</div>
            <div className="h-2 rounded-full bg-[#eef2f4] overflow-hidden">
              <div className={cn("h-full rounded-full", TONE[r.tone])} style={{ width: `${r.achievementPercent}%` }} />
            </div>
            <div className="text-right tabular font-bold">{r.achievementPercent}%</div>
          </div>
        ))}
      </div>
      <div className="mt-3 text-right">
        <Link href="/reports" className="text-[12px] font-semibold text-[var(--color-edify-primary)]">
          View region performance →
        </Link>
      </div>
    </SectionCard>
  );
}
