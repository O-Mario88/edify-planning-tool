"use client";

// PlCommandLanes — the PL's dual command strip. PLs are player-coaches:
// they carry their own field-implementation target AND manage a CCEO
// team. One unified action list hides that split, so we surface two
// lanes side by side — "My Field Work" (what I must deliver myself) and
// "My Team Work" (what my team needs from me) — each a short, clickable
// action list.

import Link from "next/link";
import { ArrowRight, Footprints, Users, type LucideIcon } from "lucide-react";
import { cplFieldLane, cplTeamLane, type PlLaneItem } from "@/lib/cpl-mock";
import { cn } from "@/lib/utils";

const DOT_TONE: Record<NonNullable<PlLaneItem["tone"]>, string> = {
  edify: "bg-[var(--color-edify-primary)]",
  amber: "bg-amber-500",
  rose: "bg-rose-500",
};

function Lane({
  title,
  icon: Icon,
  iconClass,
  items,
}: {
  title: string;
  icon: LucideIcon;
  iconClass: string;
  items: PlLaneItem[];
}) {
  return (
    <div className="card rounded-2xl p-4 flex flex-col">
      <div className="flex items-center gap-2 mb-2.5">
        <span className={cn("grid place-items-center h-7 w-7 rounded-lg shrink-0", iconClass)}>
          <Icon size={14} />
        </span>
        <h3 className="text-body-lg font-semibold tracking-tight">{title}</h3>
      </div>
      <ul className="space-y-0.5 flex-1">
        {items.map((it) => (
          <li key={it.label}>
            <Link
              href={it.href}
              className="group flex items-center gap-2.5 rounded-lg px-2.5 py-2 hover:bg-[var(--color-edify-soft)]/50 transition-colors"
            >
              <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", DOT_TONE[it.tone ?? "edify"])} />
              <span className="flex-1 min-w-0 text-[12.5px] text-[var(--text-primary)] leading-snug">
                {it.label}
              </span>
              <ArrowRight
                size={13}
                className="shrink-0 text-[var(--color-edify-primary)] opacity-0 -translate-x-1 group-hover:opacity-100 group-hover:translate-x-0 transition-all"
              />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function PlCommandLanes() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 md:gap-4">
      <Lane
        title="My Field Work"
        icon={Footprints}
        iconClass="bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]"
        items={cplFieldLane}
      />
      <Lane
        title="My Team Work"
        icon={Users}
        iconClass="bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300"
        items={cplTeamLane}
      />
    </div>
  );
}

export default PlCommandLanes;
