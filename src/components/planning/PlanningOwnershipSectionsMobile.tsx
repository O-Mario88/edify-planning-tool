"use client";

// Mobile-shaped version of PlanningOwnershipSections. Compact list rows
// + "View All" link → dedicated dashboards.

import Link from "next/link";
import {
  User, Handshake, Clock, Calendar, ArrowRight, Footprints, GraduationCap,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { CoreOwnership, CoreOwnershipRow } from "@/lib/core/core-board";
import {
  PLANNING_STATUS_LABEL,
  PLANNING_STATUS_TONE,
} from "@/lib/planning/status-tokens";
import { PlanningEmptyState } from "@/components/planning/PlanningEmptyState";

const ROW_LIMIT = 4;

const EMPTY_OWNERSHIP: CoreOwnership = { assignedToMe: [], assignedToPartner: [], awaitingPartner: [], plannedThisMonth: [] };

export type OwnershipSectionKey = keyof CoreOwnership;

type CompactDef = { title: string; Icon: LucideIcon; tone: "info" | "warn" | "good"; href: string };

const SECTION_DEFS: Record<OwnershipSectionKey, CompactDef> = {
  assignedToMe:      { title: "Assigned to Me",            Icon: User,      tone: "info", href: "/plans" },
  assignedToPartner: { title: "Assigned to Partner",       Icon: Handshake, tone: "info", href: "/partner/assignments" },
  awaitingPartner:   { title: "Awaiting Partner Schedule", Icon: Clock,     tone: "warn", href: "/partner/schedule" },
  plannedThisMonth:  { title: "Planned This Month",        Icon: Calendar,  tone: "good", href: "/plans" },
};

const ALL_SECTIONS: OwnershipSectionKey[] = ["assignedToMe", "assignedToPartner", "awaitingPartner", "plannedThisMonth"];

export function PlanningOwnershipSectionsMobile({
  ownership = EMPTY_OWNERSHIP,
  show = ALL_SECTIONS,
}: {
  ownership?: CoreOwnership;
  show?: OwnershipSectionKey[];
} = {}) {
  return (
    <>
      {show.map((key) => (
        <CompactSection key={key} {...SECTION_DEFS[key]} rows={ownership[key]} />
      ))}
    </>
  );
}

const TONE: Record<"info" | "warn" | "good", { bg: string; text: string }> = {
  info: { bg: "bg-blue-50",    text: "text-blue-700"    },
  warn: { bg: "bg-amber-50",   text: "text-amber-700"   },
  good: { bg: "bg-emerald-50", text: "text-emerald-700" },
};

function CompactSection({
  title, Icon, tone, rows, href,
}: {
  title: string;
  Icon:  LucideIcon;
  tone:  keyof typeof TONE;
  rows:  CoreOwnershipRow[];
  href:  string;
}) {
  const t = TONE[tone];
  const visible = rows.slice(0, ROW_LIMIT);
  const overflow = Math.max(0, rows.length - visible.length);

  return (
    <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm">
      <header className="px-3 pt-3 pb-2 flex items-center gap-2">
        <span className={cn("grid place-items-center h-7 w-7 rounded-md shrink-0", t.bg, t.text)}>
          <Icon size={12} />
        </span>
        <h2 className="text-[12px] font-extrabold tracking-tight flex-1">
          {title}
          <span className="ml-1 inline-flex items-center px-1.5 py-[1px] rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] text-[10px] font-extrabold tabular align-middle">
            {rows.length}
          </span>
        </h2>
        <Link
          href={href}
          className="inline-flex items-center gap-0.5 text-[11px] font-extrabold text-[var(--color-edify-primary)] shrink-0"
        >
          View All <ArrowRight size={10} />
        </Link>
      </header>

      {rows.length === 0 ? (
        <div className="px-3 pb-3">
          <PlanningEmptyState
            variant="calm"
            size="sm"
            title="Nothing here yet."
            body="Activities will land in this section as you assign them in the Core Schools section above."
          />
        </div>
      ) : (
        <>
          <ul className="border-t border-[#eef2f4] divide-y divide-[var(--color-edify-divider)]">
            {visible.map((row) => <ActivityRow key={`${row.schoolId}-${row.kind}-${row.number}`} row={row} />)}
          </ul>
          {overflow > 0 && (
            <div className="text-[11px] muted italic text-center py-1.5 border-t border-[#eef2f4]">
              + {overflow} more in the dedicated dashboard
            </div>
          )}
        </>
      )}
    </section>
  );
}

function ActivityRow({ row }: { row: CoreOwnershipRow }) {
  const KindIcon = row.kind === "visit" ? Footprints : GraduationCap;
  const canonical = row.planningStatus;
  const tone      = PLANNING_STATUS_TONE[canonical];
  return (
    <li className="relative px-3 py-2 flex items-start gap-2">
      {/* Status-tied left edge — same heatmap signal as desktop. */}
      <span className={cn("absolute left-0 top-0 bottom-0 w-[3px]", tone.edge)} aria-hidden />
      <span className="grid place-items-center h-6 w-6 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0 mt-0.5 ml-0.5">
        <KindIcon size={11} />
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-[12px] font-extrabold tracking-tight truncate">{row.schoolName}</div>
        <div className="text-[11px] muted truncate">
          {row.kind === "visit" ? "Visit" : "Training"} {row.number} · {row.intervention}
        </div>
        {row.scheduledFor && (
          <div className="text-[11px] muted truncate">{row.scheduledFor}</div>
        )}
      </div>
      <span className={cn(
        "inline-flex items-center px-1.5 py-[1px] rounded-md text-[10px] font-extrabold uppercase tracking-wide whitespace-nowrap shrink-0",
        tone.bg, tone.text,
      )}>
        {PLANNING_STATUS_LABEL[canonical]}
      </span>
    </li>
  );
}
