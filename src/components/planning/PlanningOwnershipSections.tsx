"use client";

// PlanningOwnershipSections — the four follow-on cards that complete
// the planning page flow defined by CCEO/PL:
//   • Assigned to Me              (owner = myself)
//   • Assigned to Partner         (owner ∈ {partner, partner_facilitator})
//   • Awaiting Partner Schedule   (partner-owned, status = not_started)
//   • Planned This Month          (scheduledFor lies in current month)
//
// Each section is a compact list — 5 rows visible, "View All" links
// out to the dedicated dashboards. Activities are sourced from the
// existing core-school plans so the data lines up with the gap section
// above; the same plumbing can be extended to non-core activities once
// that mock lands.

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
import { BumpPartnerButton } from "@/components/planning/BumpPartnerButton";

const ACTIVITY_LIMIT = 5;

const EMPTY_OWNERSHIP: CoreOwnership = { assignedToMe: [], assignedToPartner: [], awaitingPartner: [], plannedThisMonth: [] };

export function PlanningOwnershipSections({ ownership = EMPTY_OWNERSHIP }: { ownership?: CoreOwnership } = {}) {
  const assignedToMe   = ownership.assignedToMe;
  const assignedToPart = ownership.assignedToPartner;
  const awaitingPart   = ownership.awaitingPartner;
  const plannedMonth   = ownership.plannedThisMonth;

  return (
    <>
      <OwnershipSection
        title="Assigned to Me"
        subtitle="Core activities you personally own. Complete date, route, cost, and evidence before delivery."
        Icon={User}
        tone="info"
        rows={assignedToMe}
        emptyTitle="Nothing on your queue."
        emptyBody="When a core activity is assigned to you, it lands here. Tap Assign to Myself from any gap card to populate this view."
        emptyVariant="calm"
        viewAllHref="/plans"
      />
      <OwnershipSection
        title="Assigned to Partner"
        subtitle="Core activities a partner is either owning or facilitating. Status tracks back through your monitoring queue."
        Icon={Handshake}
        tone="info"
        rows={assignedToPart}
        emptyTitle="No partner-assigned activities yet."
        emptyBody="Assign a visit or training to a partner from the Core Schools section and it will appear here with its delivery status."
        emptyVariant="calm"
        viewAllHref="/partner/assignments"
      />
      <OwnershipSection
        title="Awaiting Partner Schedule"
        subtitle="Activities sent to partners that still need a delivery date. Bump if the schedule is overdue."
        Icon={Clock}
        tone="warn"
        rows={awaitingPart}
        showBump
        emptyTitle="Every partner activity has a date."
        emptyBody="When a partner-owned activity is overdue for scheduling it will surface here so you can bump them."
        emptyVariant="good"
        viewAllHref="/partner/schedule"
      />
      <OwnershipSection
        title="Planned This Month"
        subtitle="Every core activity with a delivery date inside this calendar month — yours, staff, or partner."
        Icon={Calendar}
        tone="good"
        rows={plannedMonth}
        emptyTitle="No core activities this month."
        emptyBody="As visits and trainings get scheduled, they appear here grouped by their delivery week."
        emptyVariant="calm"
        viewAllHref="/plans"
      />
    </>
  );
}

// ────────── Section card ──────────

const TONE: Record<"info" | "warn" | "good", { bg: string; text: string; ring: string }> = {
  info: { bg: "bg-blue-50",    text: "text-blue-700",    ring: "ring-blue-100"    },
  warn: { bg: "bg-amber-50",   text: "text-amber-700",   ring: "ring-amber-100"   },
  good: { bg: "bg-emerald-50", text: "text-emerald-700", ring: "ring-emerald-100" },
};

function OwnershipSection({
  title, subtitle, Icon, tone, rows, emptyTitle, emptyBody, emptyVariant, viewAllHref, showBump = false,
}: {
  title:        string;
  subtitle:     string;
  Icon:         LucideIcon;
  tone:         keyof typeof TONE;
  rows:         CoreOwnershipRow[];
  emptyTitle:   string;
  emptyBody:    string;
  emptyVariant: "calm" | "good";
  viewAllHref:  string;
  showBump?:    boolean;
}) {
  const t = TONE[tone];
  const visible = rows.slice(0, ACTIVITY_LIMIT);
  const overflow = Math.max(0, rows.length - visible.length);

  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-start gap-2.5 min-w-0">
          <span className={cn("grid place-items-center h-9 w-9 rounded-lg ring-1 shrink-0", t.bg, t.text, t.ring)}>
            <Icon size={15} />
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="text-body-lg font-extrabold tracking-tight">{title}</h2>
              <span className="inline-flex items-center px-1.5 py-[2px] rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] text-[10px] font-extrabold tabular">
                {rows.length}
              </span>
            </div>
            <p className="text-[11px] muted mt-0.5 leading-snug max-w-[80ch]">{subtitle}</p>
          </div>
        </div>
        <Link
          href={viewAllHref}
          className="inline-flex items-center gap-1 text-[11px] font-extrabold text-[var(--color-edify-primary)] hover:text-[var(--color-edify-dark)] shrink-0 mt-1"
        >
          View All <ArrowRight size={11} />
        </Link>
      </header>

      {rows.length === 0 ? (
        <PlanningEmptyState
          variant={emptyVariant}
          size="sm"
          title={emptyTitle}
          body={emptyBody}
        />
      ) : (
        <>
          <ul className="divide-y divide-[var(--color-edify-divider)] rounded-xl border border-[var(--color-edify-divider)] overflow-hidden">
            {visible.map((row) => <ActivityRow key={`${row.schoolId}-${row.kind}-${row.number}`} row={row} showBump={showBump} />)}
          </ul>
          {overflow > 0 && (
            <div className="text-[11px] muted italic mt-2 text-center">
              + {overflow} more — open the dedicated dashboard for the full list.
            </div>
          )}
        </>
      )}
    </section>
  );
}

function ActivityRow({ row, showBump = false }: { row: CoreOwnershipRow; showBump?: boolean }) {
  const KindIcon = row.kind === "visit" ? Footprints : GraduationCap;
  const canonical = row.planningStatus;
  const tone      = PLANNING_STATUS_TONE[canonical];
  return (
    <li
      className="relative px-3 py-2.5 grid grid-cols-12 gap-3 items-center bg-white hover:bg-[var(--color-edify-soft)]/40 transition-colors"
    >
      {/* Status-tied 3px left edge — turns the list into a heatmap.
          Absolute so it hugs the row regardless of grid wrapping. */}
      <span className={cn("absolute left-0 top-0 bottom-0 w-[3px]", tone.edge)} aria-hidden />

      <div className="col-span-12 sm:col-span-6 min-w-0 flex items-center gap-2 pl-1">
        <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
          <KindIcon size={12} />
        </span>
        <div className="min-w-0">
          <div className="text-[12px] font-extrabold tracking-tight truncate">{row.schoolName}</div>
          <div className="text-[11px] muted truncate">
            {row.kind === "visit" ? "Visit" : "Training"} {row.number} · {row.intervention}
          </div>
        </div>
      </div>
      <div className="col-span-6 sm:col-span-3 text-[11px] muted truncate">
        {row.ownerName ?? "—"}
      </div>
      <div className="col-span-6 sm:col-span-2 text-[11px] muted flex items-center gap-2 min-w-0">
        <span className="truncate">{row.scheduledFor ?? "Unscheduled"}</span>
        {showBump && (
          <BumpPartnerButton
            schoolId={row.schoolId}
            schoolName={row.schoolName}
            kind={row.kind}
            activityNumber={row.number}
            partnerName={row.ownerName}
          />
        )}
      </div>
      <div className="col-span-12 sm:col-span-1 flex sm:justify-end">
        <span className={cn(
          "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-wide whitespace-nowrap",
          tone.bg, tone.text,
        )}>
          {PLANNING_STATUS_LABEL[canonical]}
        </span>
      </div>
    </li>
  );
}
