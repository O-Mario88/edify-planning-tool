// PartnerPlannedSections — the "Planned by Partner" card on /my-plan.
//
// Replaces the per-section ownership cards that used to live on Planning.
// Shows partner-owned core activities the staff member is monitoring,
// organized into two compact sub-lanes:
//
//   • By Week  — partner work scheduled in the current calendar month and
//                the current week-of-month.
//   • By Month — partner work scheduled in the current calendar month but
//                a later week (or with no week pinned yet).
//
// Far-future partner work (next month and beyond) is intentionally NOT shown
// here — that planning belongs on the Planning page; My Plan is the personal
// monitoring cockpit and stays focused on the near term.

import { Handshake, Calendar, CalendarDays, ArrowRight, Footprints, GraduationCap, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import type { CoreOwnershipRow } from "@/lib/core/core-board";
import { PLANNING_STATUS_LABEL, PLANNING_STATUS_TONE } from "@/lib/planning/status-tokens";

const ROW_LIMIT = 5;

type Props = {
  rows: CoreOwnershipRow[];
  /** Defaults to the JS clock — pass an override in tests for deterministic windows. */
  now?: Date;
};

// "May 2026" (the value the core slot writes into `scheduledMonth`) → JS month
// label for the CURRENT calendar month, used to decide which rows are "near".
function currentMonthLabel(now: Date): string {
  return now.toLocaleDateString("en-UG", { month: "long", year: "numeric", timeZone: "UTC" });
}

function currentWeekOfMonth(now: Date): number {
  return Math.min(4, Math.ceil(now.getUTCDate() / 7));
}

export function PartnerPlannedSections({ rows, now = new Date() }: Props) {
  const monthLabel = currentMonthLabel(now);
  const weekNo = currentWeekOfMonth(now);

  // Only rows scheduled THIS month belong here — anything beyond is too far
  // out to be actionable on the staff member's personal plan view.
  const thisMonth = rows.filter((r) => !!r.scheduledMonth && r.scheduledMonth === monthLabel);

  const byWeek = thisMonth.filter((r) => r.scheduledWeek === weekNo);
  // "By Month" = the rest of this month (later weeks OR a row that has no
  // week pinned yet). Mutually exclusive with `byWeek` so a row never double-
  // counts in two lanes.
  const byMonth = thisMonth.filter((r) => r.scheduledWeek !== weekNo);

  const total = byWeek.length + byMonth.length;

  return (
    <section className="rounded-2xl border border-slate-200/70 bg-white dark:border-slate-800 dark:bg-slate-900/30">
      <header className="flex items-start gap-3 px-4 pt-3.5 pb-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-indigo-50 text-indigo-700 ring-1 ring-indigo-100">
          <Handshake size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="text-[13px] font-extrabold text-slate-800 dark:text-slate-100">Planned by Partner</h2>
            <span className="inline-flex items-center justify-center rounded-full bg-indigo-100 text-indigo-700 px-1.5 py-px text-[10px] font-bold tabular">
              {total}
            </span>
          </div>
          <p className="text-[11px] text-slate-500 leading-snug">
            Partner-owned core activities scheduled this month, split by delivery week.
          </p>
        </div>
        <Link
          href="/partner/assignments"
          className="inline-flex shrink-0 items-center gap-1 rounded-lg text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline"
        >
          View All <ArrowRight size={11} />
        </Link>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 px-3 pb-3">
        <SubLane
          title="By Week"
          subtitle={`Week ${weekNo} of ${monthLabel}.`}
          Icon={CalendarDays}
          tone="info"
          rows={byWeek}
          emptyHeadline="No partner work this week."
          emptyBody="When a partner schedules a visit or training for this week, it surfaces here."
        />
        <SubLane
          title="By Month"
          subtitle={`Rest of ${monthLabel}.`}
          Icon={Calendar}
          tone="good"
          rows={byMonth}
          emptyHeadline="No more partner work this month."
          emptyBody="Later-week partner work lands here as schedules firm up."
        />
      </div>
    </section>
  );
}

// ─── Sub-lane ────────────────────────────────────────────────────────

const TONE: Record<"info" | "good", { bg: string; text: string }> = {
  info: { bg: "bg-sky-100",     text: "text-sky-700"     },
  good: { bg: "bg-emerald-100", text: "text-emerald-700" },
};

function SubLane({
  title, subtitle, Icon, tone, rows, emptyHeadline, emptyBody,
}: {
  title: string;
  subtitle: string;
  Icon: LucideIcon;
  tone: keyof typeof TONE;
  rows: CoreOwnershipRow[];
  emptyHeadline: string;
  emptyBody: string;
}) {
  const t = TONE[tone];
  const visible = rows.slice(0, ROW_LIMIT);
  const overflow = Math.max(0, rows.length - visible.length);

  return (
    <div className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900/40">
      <div className="flex items-center gap-2 px-3 pt-2.5 pb-2">
        <span className={cn("grid h-6 w-6 place-items-center rounded-md", t.bg, t.text)}>
          <Icon size={11} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[12px] font-extrabold text-slate-800 dark:text-slate-100">
            {title}
            <span className="ml-1 inline-flex items-center rounded-md bg-slate-100 px-1.5 py-px text-[10px] font-bold tabular text-slate-600 align-middle">
              {rows.length}
            </span>
          </h3>
          <p className="text-[10.5px] text-slate-500">{subtitle}</p>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="px-3 pb-3">
          <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50/60 px-3 py-3 text-center dark:bg-slate-900/40 dark:border-slate-800">
            <p className="text-[11.5px] font-semibold text-slate-700 dark:text-slate-200">{emptyHeadline}</p>
            <p className="mt-0.5 text-[11px] text-slate-500">{emptyBody}</p>
          </div>
        </div>
      ) : (
        <>
          <ul className="border-t border-slate-100 divide-y divide-[var(--color-edify-divider)] dark:border-slate-800">
            {visible.map((row) => (
              <PartnerRow key={`${row.schoolId}-${row.kind}-${row.number}`} row={row} />
            ))}
          </ul>
          {overflow > 0 && (
            <div className="border-t border-slate-100 px-3 py-1.5 text-center text-[11px] italic text-slate-500 dark:border-slate-800">
              + {overflow} more — open Partner Assignments for the full list.
            </div>
          )}
        </>
      )}
    </div>
  );
}

function PartnerRow({ row }: { row: CoreOwnershipRow }) {
  const KindIcon = row.kind === "visit" ? Footprints : GraduationCap;
  const tone = PLANNING_STATUS_TONE[row.planningStatus];
  return (
    <li className="relative flex items-center gap-2 px-3 py-2">
      <span className={cn("absolute left-0 top-0 bottom-0 w-[3px]", tone.edge)} aria-hidden />
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">
        <KindIcon size={11} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[12px] font-extrabold tracking-tight text-slate-800 truncate dark:text-slate-100">
          {row.schoolName}
        </div>
        <div className="text-[11px] text-slate-500 truncate">
          {row.kind === "visit" ? "Visit" : "Training"} {row.number} · {row.intervention}
          {row.ownerName ? ` · ${row.ownerName}` : ""}
        </div>
      </div>
      <span
        className={cn(
          "inline-flex shrink-0 items-center rounded-md px-1.5 py-[2px] text-[10px] font-extrabold uppercase tracking-wide",
          tone.bg, tone.text,
        )}
      >
        {PLANNING_STATUS_LABEL[row.planningStatus]}
      </span>
    </li>
  );
}
