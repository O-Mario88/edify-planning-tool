"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertOctagon,
  ArrowRight,
  CalendarCheck,
  CalendarClock,
  CalendarPlus,
  CheckCircle2,
  ChevronRight,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  ENGINE_TODAY,
  detectSchoolsNeedingAnnualSsa,
  filterSsaRefreshForUser,
  ssaRefreshSchools,
  ssaRefreshSummaryFor,
  type SchoolForSsaRefresh,
  type SsaRefreshStatus,
} from "@/lib/refresh-and-followup-mock";
import type { CurrentUser } from "@/lib/schools-mock";
import { useDemoStore } from "@/components/demo/DemoStore";
import { cn } from "@/lib/utils";

// Tile keys mirror the action-needing buckets. "Current" is shown as a
// stat tile but isn't a filter target — the row list only ever surfaces
// schools that need action.
type TileKey = "needed" | "scheduled" | "overdue";

const TILE_STATUS: Record<TileKey, SsaRefreshStatus> = {
  needed:    "SSA Needed",
  scheduled: "SSA Scheduled",
  overdue:   "SSA Overdue",
};

const ROW_ICON: Record<TileKey, LucideIcon> = {
  needed:    CalendarClock,
  scheduled: CalendarCheck,
  overdue:   AlertOctagon,
};

const ROW_ICON_COLOR: Record<TileKey, string> = {
  needed:    "text-amber-600",
  scheduled: "text-[var(--color-edify-primary)]",
  overdue:   "text-rose-600",
};

const ROW_EDGE: Record<TileKey, string> = {
  needed:    "border-l-amber-500",
  scheduled: "border-l-[var(--color-edify-primary)]",
  overdue:   "border-l-rose-500 bg-rose-50/30",
};

const ROW_TITLE: Record<TileKey, string> = {
  needed:    "SSA Needed — no current-FY SSA on file.",
  scheduled: "SSA Scheduled — visit booked, awaiting completion.",
  overdue:   "SSA Overdue — 60+ days past the Sept-30 cutoff.",
};

export function SchoolsNeedingSsaCard({ user }: { user: CurrentUser }) {
  const summary = ssaRefreshSummaryFor(user);
  const visible = filterSsaRefreshForUser(ssaRefreshSchools, user);

  // All action-needing schools tagged with their status, sorted overdue
  // → needed → scheduled (most-urgent first within each bucket).
  const tagged = useMemo(
    () => detectSchoolsNeedingAnnualSsa(visible),
    [visible],
  );

  // Local scheduling overlay so tapping "Schedule" reflects immediately
  // and persists across re-renders within the session. Real backend
  // writes ssaScheduledDate; demo overlays it client-side.
  const [scheduledLocally, setScheduledLocally] = useState<Record<string, string>>({});
  const { pushToast } = useDemoStore();

  // Default to whichever bucket has the most work — overdue wins ties.
  const initialTile: TileKey =
    summary.overdue   > 0 ? "overdue"   :
    summary.needed    > 0 ? "needed"    :
    "scheduled";
  const [activeTile, setActiveTile] = useState<TileKey>(initialTile);

  const activeStatus = TILE_STATUS[activeTile];
  const rows = tagged.filter((s) => {
    const status = scheduledLocally[s.schoolId] ? "SSA Scheduled" : s.ssaRefreshStatus;
    return status === activeStatus;
  }).slice(0, 6);

  // Headline framing — one-line read of *why this card matters today*.
  // Picks the most-urgent active bucket so the CCEO sees the action
  // they should take in the next tap, not the rule that put them here.
  const headline =
    summary.overdue > 0
      ? `${summary.overdue} ${summary.overdue === 1 ? "school is" : "schools are"} overdue — schedule this week.`
      : summary.needed > 0
        ? `${summary.needed} ${summary.needed === 1 ? "school needs" : "schools need"} an SSA for the new FY.`
        : summary.scheduled > 0
          ? `${summary.scheduled} scheduled — visit on or before the booked date.`
          : "All your schools have a current SSA. Nothing to do.";

  function handleSchedule(s: SchoolForSsaRefresh) {
    // Suggest a date 7 days out. Real backend opens the visit picker.
    const next = new Date(ENGINE_TODAY);
    next.setDate(next.getDate() + 7);
    const iso = next.toISOString().slice(0, 10);
    setScheduledLocally((prev) => ({ ...prev, [s.schoolId]: iso }));
    pushToast({
      tone: "success",
      title: "SSA scheduled",
      body: `${s.schoolName} booked for ${iso}. CCEO todo created.`,
    });
  }

  return (
    <SectionCard
      icon={<CalendarClock size={13} />}
      title="Schools Needing SSA"
      subtitle={headline}
      actions={
        <Link
          href="/ssa#schools-needing-ssa"
          className="inline-flex items-center gap-1 text-[var(--text-body)] font-semibold text-[var(--color-edify-primary)]"
        >
          View All
          <ArrowRight size={11} />
        </Link>
      }
    >
      {/* Filter chips — same pattern as TrainingFollowUpCard. The
          Current tile is informational; it doesn't filter the list
          below because there's nothing to act on there. */}
      <div
        role="group"
        aria-label="Filter SSA refresh buckets"
        className="grid grid-cols-4 gap-2 mb-3"
      >
        <TileTab
          tileKey="overdue"
          label="Overdue"
          fullLabel="SSA Overdue (60+ days past Sept 30)"
          value={summary.overdue}
          tone="bg-rose-50 text-rose-700"
          activeRing="ring-rose-500"
          isActive={activeTile === "overdue"}
          onClick={() => setActiveTile("overdue")}
        />
        <TileTab
          tileKey="needed"
          label="Needed"
          fullLabel="SSA Needed for the new FY"
          value={summary.needed}
          tone="bg-amber-50 text-amber-700"
          activeRing="ring-amber-500"
          isActive={activeTile === "needed"}
          onClick={() => setActiveTile("needed")}
        />
        <TileTab
          tileKey="scheduled"
          label="Scheduled"
          fullLabel="SSA Scheduled — visit booked"
          value={summary.scheduled}
          tone="bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]"
          activeRing="ring-[var(--color-edify-primary)]"
          isActive={activeTile === "scheduled"}
          onClick={() => setActiveTile("scheduled")}
        />
        <CurrentTile value={summary.current} total={summary.total} />
      </div>

      {tagged.length === 0 ? (
        <div className="text-[var(--text-body)] muted text-center py-4 flex items-center justify-center gap-1.5">
          <CheckCircle2 size={13} className="text-[var(--color-success)]" />
          All your assigned schools have a current SSA.
        </div>
      ) : rows.length === 0 ? (
        <div
          id="ssa-refresh-row-list"
          aria-live="polite"
          className="text-[var(--text-body)] muted text-center py-4 flex items-center justify-center gap-1.5"
        >
          <CheckCircle2 size={13} className="text-[var(--color-success)]" />
          {activeTile === "overdue"   && "No overdue SSAs. Good."}
          {activeTile === "needed"    && "Nothing waiting on you to schedule."}
          {activeTile === "scheduled" && "No SSAs currently scheduled."}
        </div>
      ) : (
        <div id="ssa-refresh-row-list" aria-live="polite" className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {rows.map((s) => {
            const scheduledHere = scheduledLocally[s.schoolId];
            const effectiveStatus: SsaRefreshStatus =
              scheduledHere ? "SSA Scheduled" : s.ssaRefreshStatus;
            const tone: TileKey =
              effectiveStatus === "SSA Overdue" ? "overdue"
              : effectiveStatus === "SSA Scheduled" ? "scheduled"
              : "needed";
            const RowIcon = ROW_ICON[tone];
            const daysPast = daysSinceCutoff(s, ENGINE_TODAY);
            const scheduledDate = scheduledHere ?? s.ssaScheduledDate;
            return (
              <div
                key={s.schoolId}
                className={cn(
                  "rounded-lg border p-2.5 space-y-1.5 transition-colors border-l-[3px]",
                  "border-[var(--color-edify-border)]",
                  ROW_EDGE[tone],
                )}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <RowIcon
                    size={16}
                    className={cn("shrink-0", ROW_ICON_COLOR[tone])}
                    aria-label={ROW_TITLE[tone]}
                  >
                    <title>{ROW_TITLE[tone]}</title>
                  </RowIcon>
                  <div className="text-[var(--text-body-lg)] font-semibold leading-tight truncate flex-1 min-w-0">
                    {s.schoolName}
                  </div>
                  {tone === "overdue" ? (
                    <span className="text-[var(--text-tiny)] font-bold text-rose-700 whitespace-nowrap tabular shrink-0">
                      {daysPast}d past
                    </span>
                  ) : tone === "scheduled" && scheduledDate ? (
                    <span className="text-[var(--text-tiny)] font-bold text-[var(--color-edify-primary)] whitespace-nowrap tabular shrink-0">
                      {formatShort(scheduledDate)}
                    </span>
                  ) : (
                    <span className="text-[var(--text-tiny)] muted whitespace-nowrap tabular shrink-0">
                      {daysPast > 0 ? `${daysPast}d past` : "due now"}
                    </span>
                  )}
                </div>
                <div className="text-[var(--text-caption)] muted leading-snug">
                  {s.district}
                  {" · "}
                  Latest SSA: {s.latestSsaDate ? formatShort(s.latestSsaDate) : "Never"}
                </div>
                {tone === "overdue" && (
                  <div className="text-[var(--text-caption)] leading-snug text-rose-700 font-bold inline-flex items-start gap-1.5">
                    <AlertOctagon size={12} className="shrink-0 mt-[1px] text-rose-600" />
                    <span>Block of work — book this visit before next cluster meeting.</span>
                  </div>
                )}
                <div className="flex items-center gap-2 pt-1 flex-wrap">
                  {tone === "scheduled" ? (
                    <span className="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[var(--text-tiny)] font-bold bg-emerald-100 text-emerald-700 whitespace-nowrap">
                      <CheckCircle2 size={11} />
                      Scheduled{scheduledDate ? ` · ${formatShort(scheduledDate)}` : ""}
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handleSchedule(s)}
                      className="btn btn-sm btn-primary inline-flex items-center gap-1.5"
                    >
                      <CalendarPlus size={11} />
                      Schedule SSA
                    </button>
                  )}
                  <Link
                    href={`/schools/${s.schoolId}`}
                    className="btn btn-sm inline-flex items-center gap-1"
                  >
                    School
                    <ChevronRight size={11} />
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-2 pt-2 border-t border-[#eef2f4] text-[var(--text-caption)] muted">
        Engine rule: latest SSA on or before Sept 30 of last FY → schedule for the new FY. Tapping <span className="font-semibold">Schedule SSA</span> creates the CCEO todo.
      </div>
    </SectionCard>
  );
}

// ───────────── Helpers ─────────────

function daysSinceCutoff(s: SchoolForSsaRefresh, today: Date): number {
  // Days past the Sept-30 cutoff of the previous FY. Negative becomes
  // 0 (not yet past due). Used only as a urgency proxy in the UI.
  const y = today.getFullYear();
  const cutoffYear = today.getMonth() >= 9 ? y : y - 1;
  const cutoff = new Date(`${cutoffYear}-09-30T00:00:00`).getTime();
  // If the school's latest SSA is *after* cutoff, it's not past due.
  if (s.latestSsaDate && s.latestSsaDate > `${cutoffYear}-09-30`) return 0;
  return Math.max(0, Math.floor((today.getTime() - cutoff) / 86_400_000));
}

function formatShort(iso: string): string {
  // "2025-09-14" → "Sep 14, 2025". Locale-stable so SSR/CSR match.
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  if (Number.isNaN(d.getTime())) return iso;
  const month = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][d.getMonth()];
  return `${month} ${d.getDate()}, ${d.getFullYear()}`;
}

// ───────────── TileTab + CurrentTile ─────────────

function TileTab({
  tileKey,
  label,
  fullLabel,
  value,
  tone,
  activeRing,
  isActive,
  onClick,
}: {
  tileKey: TileKey;
  label: string;
  fullLabel: string;
  value: number;
  tone: string;
  activeRing: string;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      id={`ssa-tile-${tileKey}`}
      {...(isActive ? { "aria-pressed": "true" as const } : { "aria-pressed": "false" as const })}
      aria-controls="ssa-refresh-row-list"
      title={fullLabel}
      onClick={onClick}
      className={cn(
        "rounded-lg px-2.5 py-2 flex flex-col items-start overflow-hidden text-left transition-shadow",
        tone,
        isActive
          ? cn("ring-2 ring-offset-1 ring-offset-white shadow-sm", activeRing)
          : "ring-2 ring-transparent hover:ring-1 hover:ring-current/20",
      )}
    >
      <span className="text-[var(--text-tiny)] font-semibold uppercase tracking-wide truncate w-full">
        {label}
      </span>
      <span className="text-[var(--text-h-sm)] font-extrabold tabular leading-none mt-1 truncate w-full">
        {value}
      </span>
    </button>
  );
}

// Current is the "all good" stat — read-only, not a filter.
function CurrentTile({ value, total }: { value: number; total: number }) {
  return (
    <div
      title={`${value} of ${total} schools have a current SSA`}
      className="rounded-lg px-2.5 py-2 flex flex-col items-start overflow-hidden bg-emerald-50 text-emerald-700 ring-2 ring-transparent"
    >
      <span className="text-[var(--text-tiny)] font-semibold uppercase tracking-wide truncate w-full">
        Current
      </span>
      <span className="text-[var(--text-h-sm)] font-extrabold tabular leading-none mt-1 truncate w-full">
        {value}
      </span>
    </div>
  );
}
