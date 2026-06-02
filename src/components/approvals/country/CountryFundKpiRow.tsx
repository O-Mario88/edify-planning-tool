"use client";

import {
  Building2,
  Calendar,
  CheckCircle2,
  Clock,
  RotateCcw,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { countryFundKpis, type CountryFundKpi } from "@/lib/country-fund-approvals-mock";
import { Tile } from "@/components/ui/Tile";

// Country-Director fund-approval KPI row — shares the `Tile` primitive
// with every other approvals surface (one tone/glow/stagger source).

const ICON_MAP: Record<CountryFundKpi["icon"], LucideIcon> = {
  wallet:      Wallet,
  clock:       Clock,
  checkCircle: CheckCircle2,
  rotateCcw:   RotateCcw,
  calendar:    Calendar,
  building:    Building2,
};

export function CountryFundKpiRow() {
  return (
    <section className="px-3 sm:px-4 lg:px-6 pb-3">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
        {countryFundKpis.map((k, i) => {
          const Icon = ICON_MAP[k.icon];
          return (
            <Tile
              key={k.key}
              index={i}
              tone={k.iconTone}
              icon={<Icon size={15} />}
              label={k.label}
              value={k.value}
              delta={k.delta ? { dir: k.deltaTone === "up" ? "up" : "down", text: k.delta, caption: k.caption } : undefined}
              trend={!k.delta && k.caption ? <span className="muted font-semibold truncate">{k.caption}</span> : undefined}
            />
          );
        })}
      </div>
    </section>
  );
}
