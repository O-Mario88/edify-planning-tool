"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  Calendar,
  ChevronRight,
  GraduationCap,
  Users,
  Building2,
  Footprints,
  Wallet,
  Receipt,
  Clock4,
  CheckCircle2,
  CircleAlert,
  Pencil,
  CalendarPlus,
  Upload,
  RotateCw,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  estimatedCostFor,
  costBreakdownFor,
  engineBreakdownFor,
  type PlanItem,
  type PlanItemType,
  type PlanItemStatus,
} from "@/lib/mobile-mock";
import { costApprovalStatus } from "@/lib/cost-engine/cost-engine";
import {
  RescheduleActivityDrawer,
  type ActivityRescheduleOutcome,
} from "@/components/planning/RescheduleActivityDrawer";
import { cn } from "@/lib/utils";

// Weekly activity schedule with fund-need rollups.
//
// One surface, three audiences. The data is identical; the framing
// changes via the `audience` prop:
//
//   owner       — "Your week-by-week plan. The total at each row is
//                  the disbursement you'll request from the accountant."
//   finance     — "Activity wave coming at you. Each week's total is
//                  the cash you need ready by the start of that week."
//   leadership  — "30-day plan horizon for review. Roll-ups give you
//                  approval cost and which weeks concentrate spending."
//
// Sorted chronologically by week. Each week collapses to a header
// (count + cost) and expands to the activity list. The component is
// stateless beyond expand/collapse — all roll-ups derive from props.

const TYPE_ICON: Record<PlanItemType, LucideIcon> = {
  "Cluster Training": GraduationCap,
  "Cluster Meeting":  Users,
  "Visit":            Building2,
  "Follow-Up Visit":  Footprints,
};

const TYPE_TONE: Record<PlanItemType, string> = {
  "Cluster Training": "bg-emerald-100 text-emerald-700",
  "Cluster Meeting":  "bg-violet-100  text-violet-700",
  "Visit":            "bg-sky-100     text-sky-700",
  "Follow-Up Visit":  "bg-orange-100  text-orange-700",
};

const STATUS_TONE: Record<PlanItemStatus, string> = {
  "Planned":        "bg-slate-100   text-slate-700",
  "In Progress":    "bg-amber-100   text-amber-700",
  "Verified":       "bg-emerald-100 text-emerald-700",
  "Awaiting SF ID": "bg-rose-100    text-rose-700",
};

type Audience = "owner" | "finance" | "leadership";

const AUDIENCE_SUBTITLE: Record<Audience, string> = {
  owner:      "Your activities week-by-week. Each row total is the disbursement you'll need released.",
  finance:    "Activity wave coming this period. Each week's total is the cash that needs to clear by Monday of that week.",
  leadership: "30-day plan horizon. Roll-ups show which weeks concentrate spending so reviews stay sequenced.",
};

function formatUgx(amount: number): string {
  if (amount >= 1_000_000) return `UGX ${(amount / 1_000_000).toFixed(1)}M`;
  if (amount >= 1_000)     return `UGX ${(amount / 1_000).toFixed(0)}K`;
  return `UGX ${amount}`;
}

export function PlanScheduleByWeek({
  items,
  audience = "owner",
  title = "Activity Schedule",
  initialExpanded = "all",
}: {
  items: PlanItem[];
  audience?: Audience;
  title?: string;
  /** "all" expands every week on first paint; "first" expands only the earliest week. */
  initialExpanded?: "all" | "first";
}) {
  // Group by weekLabel, then sort each week's rows chronologically.
  // Date strings are "Mon DD, YYYY" — Date.parse handles them and
  // returns NaN for malformed input; we sort NaN-last so dirty rows
  // never blow up the table. Outer week order follows insertion,
  // which matches the mock data's natural week sequence.
  const byWeek = useMemo(() => {
    const map = new Map<string, PlanItem[]>();
    for (const item of items) {
      const list = map.get(item.weekLabel) ?? [];
      list.push(item);
      map.set(item.weekLabel, list);
    }
    return Array.from(map.entries()).map(([weekLabel, rows]) => {
      const sorted = [...rows].sort((a, b) => {
        const ta = Date.parse(a.date);
        const tb = Date.parse(b.date);
        if (Number.isNaN(ta)) return 1;
        if (Number.isNaN(tb)) return -1;
        return ta - tb;
      });
      return {
        weekLabel,
        rows: sorted,
        count: sorted.length,
        cost: sorted.reduce((sum, r) => sum + estimatedCostFor(r), 0),
      };
    });
  }, [items]);

  const monthTotal = byWeek.reduce((sum, w) => sum + w.cost, 0);
  const monthCount = byWeek.reduce((sum, w) => sum + w.count, 0);

  const initialOpen = new Set<string>(
    initialExpanded === "all"
      ? byWeek.map((w) => w.weekLabel)
      : byWeek[0] ? [byWeek[0].weekLabel] : [],
  );
  const [open, setOpen] = useState<Set<string>>(initialOpen);
  const [openRows, setOpenRows] = useState<Set<string>>(new Set());
  // Activity-level reschedule modal — single instance, all rows share it.
  const [rescheduleItem, setRescheduleItem] = useState<PlanItem | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  function handleRescheduleSubmit(outcome: ActivityRescheduleOutcome) {
    setToast(
      `Rescheduled to ${outcome.newDate} — school contact + assigned staff notified. (${outcome.reason})`,
    );
    setRescheduleItem(null);
    setTimeout(() => setToast(null), 4500);
  }

  function toggle(week: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(week)) next.delete(week);
      else next.add(week);
      return next;
    });
  }

  function toggleRow(id: string) {
    setOpenRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  if (byWeek.length === 0) {
    return (
      <SectionCard
        icon={<Calendar size={13} />}
        title={title}
        subtitle={AUDIENCE_SUBTITLE[audience]}
      >
        <div className="text-center py-6">
          <div className="text-[13px] font-semibold">No activities scheduled this period</div>
          <p className="text-[11.5px] muted mt-1">Plans submitted by the field team will land here once approved.</p>
        </div>
      </SectionCard>
    );
  }

  return (
    <SectionCard
      icon={<Calendar size={13} />}
      title={title}
      subtitle={AUDIENCE_SUBTITLE[audience]}
      actions={
        <span className="inline-flex items-center gap-1.5 text-[11.5px] font-extrabold text-[var(--color-edify-primary)]">
          <Wallet size={12} />
          Month total · {formatUgx(monthTotal)}
        </span>
      }
    >
      <ul className="divide-y divide-[var(--color-edify-divider)] -mt-1">
        {byWeek.map((week) => {
          const isOpen = open.has(week.weekLabel);
          return (
            <li key={week.weekLabel} className="py-1">
              <button
                type="button"
                onClick={() => toggle(week.weekLabel)}
                aria-expanded={isOpen}
                className="w-full flex items-center gap-3 py-2 px-1 rounded-md hover:bg-[var(--color-edify-soft)]/40 text-left"
              >
                <ChevronRight
                  size={14}
                  className={cn(
                    "text-[var(--color-edify-muted)] transition-transform shrink-0",
                    isOpen && "rotate-90",
                  )}
                />
                <span className="text-[13px] font-extrabold tracking-tight">{week.weekLabel}</span>
                <span className="text-[11px] muted">
                  · {week.count} {week.count === 1 ? "activity" : "activities"}
                </span>
                <span className="ml-auto inline-flex items-center gap-1.5 text-body font-extrabold tabular text-[var(--color-edify-text)]">
                  <Wallet size={12} className="text-[var(--color-edify-muted)]" />
                  {formatUgx(week.cost)}
                </span>
              </button>

              {isOpen && (
                <ul className="pl-7 pr-1 pb-2 space-y-1.5">
                  {week.rows.map((r) => {
                    const Icon = TYPE_ICON[r.type];
                    const cost = estimatedCostFor(r);
                    const rowOpen = openRows.has(r.id);
                    const moveCount = r.reschedules?.length ?? 0;
                    return (
                      <li key={r.id}>
                        <button
                          type="button"
                          onClick={() => toggleRow(r.id)}
                          aria-expanded={rowOpen}
                          className={cn(
                            "w-full flex items-center gap-3 py-1.5 px-2 rounded-md text-left transition-colors",
                            rowOpen
                              ? "bg-[var(--color-edify-soft)]/40"
                              : "hover:bg-[var(--color-edify-soft)]/30",
                          )}
                        >
                          <ChevronRight
                            size={11}
                            className={cn(
                              "text-[var(--color-edify-muted)] transition-transform shrink-0",
                              rowOpen && "rotate-90",
                            )}
                          />
                          <span className={cn("h-7 w-7 rounded-md grid place-items-center shrink-0", TYPE_TONE[r.type])}>
                            <Icon size={13} />
                          </span>
                          {/* Title + meta block.  On mobile/tablet the row
                              stacks: title+date take the full width on top,
                              status+amount drop to a second row underneath
                              so the title never collides with the badge.
                              On sm+ everything sits on a single line with
                              proper truncation on the title. */}
                          <div className="flex-1 min-w-0 flex flex-col sm:flex-row sm:items-center gap-y-1 sm:gap-x-3">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5 min-w-0">
                                <span className="text-body font-semibold truncate block flex-1 min-w-0">
                                  {r.title} — {r.context}
                                </span>
                                {moveCount > 0 && (
                                  <span
                                    title={`Moved ${moveCount} time${moveCount === 1 ? "" : "s"} — expand for history`}
                                    className="inline-flex items-center gap-0.5 px-1 py-[1px] rounded-md text-[9px] font-extrabold tabular bg-amber-50 text-amber-700 ring-1 ring-amber-200 shrink-0"
                                  >
                                    <RotateCw size={8} />
                                    ×{moveCount}
                                  </span>
                                )}
                              </div>
                              <div className="text-caption muted truncate">{r.date}</div>
                            </div>
                            {/* Status + amount.  Right-aligned on sm+;
                                left-aligned + tighter gap on mobile so the
                                stacked block reads as a status row. */}
                            <div className="flex items-center gap-2 sm:gap-3 shrink-0">
                              <span
                                className={cn(
                                  "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap shrink-0",
                                  STATUS_TONE[r.status],
                                )}
                              >
                                {r.status}
                              </span>
                              <span className="text-[11.5px] font-extrabold tabular tabular-nums w-[68px] sm:w-[78px] text-right shrink-0">
                                {formatUgx(cost)}
                              </span>
                            </div>
                          </div>
                        </button>

                        {rowOpen && (
                          <ActivityDetail
                            item={r}
                            audience={audience}
                            onReschedule={() => setRescheduleItem(r)}
                          />
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </li>
          );
        })}
      </ul>

      <footer className="mt-2 pt-2.5 border-t border-[var(--color-edify-divider)] flex items-baseline justify-between">
        <span className="text-[11.5px] muted">
          {monthCount} {monthCount === 1 ? "activity" : "activities"} across {byWeek.length} {byWeek.length === 1 ? "week" : "weeks"}
        </span>
        <span className="text-body-lg font-extrabold tabular text-[var(--color-edify-primary)]">
          {formatUgx(monthTotal)}
        </span>
      </footer>

      {/* Single reschedule modal — shared across every row in the schedule. */}
      <RescheduleActivityDrawer
        open={!!rescheduleItem}
        item={rescheduleItem}
        onClose={() => setRescheduleItem(null)}
        onSubmit={handleRescheduleSubmit}
      />

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl shadow-lg bg-emerald-600 text-white text-[12px] font-semibold px-4 py-3 max-w-[420px]">
          {toast}
        </div>
      )}
    </SectionCard>
  );
}

// ─────────── ActivityDetail ───────────
//
// Inline detail panel that appears when a schedule row is expanded.
// Three blocks: cost breakdown (the line items that sum to the
// disbursement), status note (one-liner describing where the activity
// sits in its lifecycle), and quick action links. The action set is
// audience-aware — the owner edits and uploads evidence, finance and
// leadership only open the deep detail.

const STATUS_NOTE: Record<PlanItemStatus, { icon: LucideIcon; tone: string; line: string }> = {
  "Planned": {
    icon: Clock4,
    tone: "text-slate-700",
    line: "Scheduled. Disburses on Monday of the week before delivery.",
  },
  "In Progress": {
    icon: Clock4,
    tone: "text-amber-700",
    line: "Delivery underway. Evidence due within 48 hours of completion.",
  },
  "Verified": {
    icon: CheckCircle2,
    tone: "text-emerald-700",
    line: "Closed. Evidence accepted, fund use accounted for.",
  },
  "Awaiting SF ID": {
    icon: CircleAlert,
    tone: "text-rose-700",
    line: "Salesforce ID missing — counts pending until the ID lands.",
  },
};

function ActivityDetail({
  item,
  audience,
  onReschedule,
}: {
  item: PlanItem;
  audience: Audience;
  onReschedule: () => void;
}) {
  const lines = costBreakdownFor(item);
  const total = lines.reduce((s, l) => s + l.amount, 0);
  const note  = STATUS_NOTE[item.status];
  const NoteIcon = note.icon;
  const moveCount = item.reschedules?.length ?? 0;

  // Engine-derived metadata — present only for items with activityContext.
  // Drives the district badge + approval-status verdict + "Set by CD" note.
  const engineBreakdown = engineBreakdownFor(item);
  const approval = engineBreakdown
    ? costApprovalStatus({
        activityType: item.type,
        participants: engineBreakdown.kind === "training" || engineBreakdown.kind === "cluster-meeting"
          ? engineBreakdown.participants
          : undefined,
        nights: engineBreakdown.kind === "visit" ? engineBreakdown.nights : undefined,
        totalUgx: engineBreakdown.total,
        // missingRates from the engine is string[]; the helper expects
        // RateKey[]. Casting is safe — the helper only iterates + checks
        // emptiness; it never indexes into a typed map.
        missingRates: engineBreakdown.missingRates as never,
      })
    : null;
  const districtType = engineBreakdown?.kind === "visit" ? engineBreakdown.districtType : null;

  return (
    <div className="ml-[58px] mr-1 mt-1 mb-2 grid grid-cols-1 md:grid-cols-2 gap-3">
      {/* Cost breakdown — engine-driven when activityContext is set on
          the item; otherwise renders the flat type-based fallback. The
          line items match the CD-configured rates so transport, lunch,
          accommodation, etc. all appear exactly as priced by the
          Country Director. Staff/partners read this number; they
          never edit it. */}
      <div className="rounded-lg border border-[var(--color-edify-border)] bg-white p-3">
        <header className="flex items-center justify-between gap-1.5 mb-1.5">
          <span className="inline-flex items-center gap-1.5">
            <Receipt size={12} className="text-[var(--color-edify-primary)]" />
            <span className="text-[11.5px] font-extrabold tracking-tight uppercase">Cost breakdown</span>
          </span>
          {districtType && (
            <span
              className={cn(
                "inline-flex items-center px-1.5 py-[1px] rounded-md text-[10px] font-extrabold whitespace-nowrap",
                districtType === "secondary"
                  ? "bg-amber-50 text-amber-700 ring-1 ring-amber-200"
                  : "bg-sky-50 text-sky-700 ring-1 ring-sky-200",
              )}
              title={districtType === "secondary"
                ? "School is outside staff's home district — accommodation + breakfast + dinner auto-included"
                : "School is in staff's home district — no accommodation, no breakfast, no dinner"}
            >
              {districtType === "secondary" ? "Secondary district" : "Primary district"}
            </span>
          )}
        </header>
        <ul className="divide-y divide-[var(--color-edify-divider)] -my-1">
          {lines.map((l) => (
            <li key={l.label} className="flex items-baseline justify-between py-1">
              <span className="text-[11.5px]">{l.label}</span>
              <span className="text-[11.5px] font-semibold tabular">{formatUgx(l.amount)}</span>
            </li>
          ))}
        </ul>
        <div className="mt-2 pt-2 border-t border-[var(--color-edify-divider)] flex items-baseline justify-between">
          <span className="text-[11px] muted font-semibold uppercase tracking-wide">Total</span>
          <span className="text-[13px] font-extrabold tabular text-[var(--color-edify-primary)]">
            {formatUgx(total)}
          </span>
        </div>
        {approval && (
          <div
            className={cn(
              "mt-2 -mb-1 rounded-md px-2 py-1.5 text-[11px] leading-snug flex items-start gap-1.5",
              approval.state === "safe"         && "bg-emerald-50 text-emerald-800 ring-1 ring-emerald-100",
              approval.state === "needs_review" && "bg-amber-50   text-amber-800   ring-1 ring-amber-100",
              approval.state === "blocked"      && "bg-rose-50    text-rose-800    ring-1 ring-rose-100",
            )}
          >
            <span className="font-extrabold uppercase tracking-wider text-[10px] shrink-0">
              {approval.state === "safe" ? "Safe to approve" : approval.state === "needs_review" ? "Needs review" : "Blocked"}
            </span>
            <span className="opacity-90">· {approval.reason}</span>
          </div>
        )}
        {engineBreakdown && (
          <div className="mt-2 text-caption muted leading-snug">
            Rates set by the Country Director · Staff and partners cannot edit
          </div>
        )}
      </div>

      {/* Status + actions */}
      <div className="rounded-lg border border-[var(--color-edify-border)] bg-white p-3 flex flex-col">
        <header className="flex items-center gap-1.5 mb-1.5">
          <NoteIcon size={12} className={note.tone} />
          <span className="text-[11.5px] font-extrabold tracking-tight uppercase">{item.status}</span>
          {moveCount > 0 && (
            <span className="ml-auto inline-flex items-center gap-0.5 px-1.5 py-[1px] rounded-md text-[10px] font-extrabold bg-amber-50 text-amber-700 ring-1 ring-amber-200">
              <RotateCw size={9} />
              Moved {moveCount}×
            </span>
          )}
        </header>
        <p className={cn("text-[11.5px] leading-snug", note.tone)}>{note.line}</p>

        {/* Compact reschedule history — surfaces the audit trail right
            where the planner sees the activity, not buried behind a
            click into the modal. The modal still owns the full form
            + "describe other reason" path. */}
        {moveCount > 0 && (
          <ul className="mt-2 pt-2 border-t border-[var(--color-edify-divider)] space-y-1">
            {item.reschedules!.slice(-2).map((h, i) => (
              <li key={i} className="text-[11px] muted leading-snug">
                <span className="opacity-70 line-through">{h.from}</span>
                {" → "}
                <span className="font-semibold text-[var(--color-edify-text)]">{h.to}</span>
                <span className="opacity-70"> · {h.reason}</span>
              </li>
            ))}
          </ul>
        )}

        {audience === "owner" && (
          <div className="mt-auto pt-3 flex flex-wrap gap-1.5">
            <ActionLink href={`/plans/${item.id}`} Icon={Pencil} label="Open / Edit" />
            <button
              type="button"
              onClick={onReschedule}
              className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[11px] font-semibold bg-[var(--color-edify-soft)]/60 text-[var(--color-edify-dark)] hover:bg-[var(--color-edify-soft)] transition-colors border border-[var(--color-edify-border)]"
            >
              <CalendarPlus size={11} />
              Reschedule
            </button>
            {(item.status === "In Progress" || item.status === "Awaiting SF ID") && (
              <ActionLink href={`/partner/evidence?activity=${item.id}`} Icon={Upload} label="Submit Evidence" />
            )}
          </div>
        )}

        {audience !== "owner" && (
          <div className="mt-auto pt-3 flex flex-wrap gap-1.5">
            <ActionLink href={`/plans/${item.id}`} Icon={Pencil} label="Open Activity Detail" />
            <button
              type="button"
              onClick={onReschedule}
              className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[11px] font-semibold bg-[var(--color-edify-soft)]/60 text-[var(--color-edify-dark)] hover:bg-[var(--color-edify-soft)] transition-colors border border-[var(--color-edify-border)]"
            >
              <CalendarPlus size={11} />
              Reschedule
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function ActionLink({
  href, Icon, label,
}: {
  href: string;
  Icon: LucideIcon;
  label: string;
}) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[11px] font-semibold bg-[var(--color-edify-soft)]/60 text-[var(--color-edify-dark)] hover:bg-[var(--color-edify-soft)] transition-colors border border-[var(--color-edify-border)]"
    >
      <Icon size={11} />
      {label}
    </Link>
  );
}
