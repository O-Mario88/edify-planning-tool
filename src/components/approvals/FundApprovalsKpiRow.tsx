"use client";

import {
  Building2,
  CheckCircle2,
  Clock,
  Folder,
  RotateCcw,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { fundApprovalKpis, type FundApprovalKpi } from "@/lib/fund-approvals-mock";
import { Tile } from "@/components/ui/Tile";

// Program-Lead fund-approval KPI row — built on the shared `Tile`
// primitive (the /approvals design is the source of truth that `Tile`
// codifies), so tones, glow, stagger and dark/glass behaviour all come
// from one place.

const ICON_MAP: Record<FundApprovalKpi["icon"], LucideIcon> = {
  wallet:      Wallet,
  clock:       Clock,
  checkCircle: CheckCircle2,
  rotateCcw:   RotateCcw,
  folder:      Folder,
  building:    Building2,
};

export function FundApprovalsKpiRow() {
  return (
    <section className="px-3 sm:px-4 lg:px-6 pb-3">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
        {fundApprovalKpis.map((k, i) => {
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
