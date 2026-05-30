"use client";

import {
  Users,
  Building,
  Briefcase,
  Shield,
  CheckCircle2,
  XCircle,
  UserPlus,
  Handshake,
  type LucideIcon,
} from "lucide-react";
import { SectionCard, ProgressRing } from "@/components/ui/primitives";
import {
  type StatusSnapshotTile,
} from "@/lib/schools-mock";

const iconMap: Record<StatusSnapshotTile["icon"], LucideIcon> = {
  users:       Users,
  schoolOff:   Building,
  briefcase:   Briefcase,
  shield:      Shield,
  checkCircle: CheckCircle2,
  xCircle:     XCircle,
  userPlus:    UserPlus,
  handshake:   Handshake,
};

const ringColor: Record<StatusSnapshotTile["tone"], string> = {
  green:   "var(--color-success)",
  rose:    "#e11d48",
  blue:    "#2563eb",
  violet:  "#7c3aed",
  emerald: "#10b981",
  red:     "var(--color-danger)",
  amber:   "var(--color-edify-orange)",
  edify:   "var(--color-edify-primary)",
};

const valueColor: Record<StatusSnapshotTile["tone"], string> = {
  green:   "text-[#15803d]",
  rose:    "text-rose-700",
  blue:    "text-[#1d4ed8]",
  violet:  "text-violet-700",
  emerald: "text-[#047857]",
  red:     "text-red-700",
  amber:   "text-amber-800",
  edify:   "text-[var(--color-edify-primary)]",
};

export function SchoolStatusSnapshot({ tiles }: { tiles: StatusSnapshotTile[] }) {
  return (
    <SectionCard icon={<Building className="text-[var(--color-edify-primary)]" size={13} />} title="School Status Snapshot">
      <div className="grid grid-cols-4 gap-3">
        {tiles.map((t) => {
          const Icon = iconMap[t.icon];
          return (
            <div key={t.key} className="flex items-center gap-2 overflow-hidden">
              <ProgressRing
                pct={t.pct}
                size={56}
                stroke={5}
                color={ringColor[t.tone]}
                label={`${t.pct}%`}
              />
              <div className="leading-tight min-w-0 flex-1">
                <div className="flex items-center gap-1 text-[10px] muted font-semibold">
                  <Icon size={10} className="shrink-0" />
                  <span className="truncate">{t.label}</span>
                </div>
                <div className={`text-[16px] font-extrabold tabular leading-none mt-0.5 truncate ${valueColor[t.tone]}`}>
                  {t.value.toLocaleString()}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </SectionCard>
  );
}
