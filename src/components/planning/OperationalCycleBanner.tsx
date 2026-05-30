import { CalendarRange, Sparkles, History, ChevronRight } from "lucide-react";
import {
  activeFinancialYear,
  cycleRangeLabel,
  daysSinceCycleStart,
} from "@/lib/fy-engine";
import { ENGINE_TODAY } from "@/lib/refresh-and-followup-mock";

// Operational cycle banner — sits at the top of /planning to tell the
// CCEO/PL exactly which cycle their counters are tracking. The
// operational year runs Oct 1 → Sep 30. On Oct 1, every visit /
// training / cluster / SSA / SIT counter resets for the new cycle.
// Historical records stay archived on prior FY rows — never deleted.
//
// Three states the banner can render:
//
//   1. Mid-cycle (default)     — calm summary line + "tracked by last
//                                date of entry" reminder.
//   2. Fresh cycle (first 60d) — green "New operational cycle started"
//                                notice with the reset explanation, so
//                                planners aren't confused when a school
//                                that completed SSA last cycle shows
//                                up as "missing" again.
//   3. Cycle closing (last 30d)— amber heads-up that the cycle ends
//                                on Sep 30 and counters will reset.

const FRESH_CYCLE_WINDOW_DAYS  = 60;
const CYCLE_CLOSING_WINDOW_DAYS = 30;

export function OperationalCycleBanner() {
  const active     = activeFinancialYear();
  const todayIso   = ymd(ENGINE_TODAY);
  const daysIn     = daysSinceCycleStart(todayIso, active);
  const totalDays  = daysBetween(active.startDate, active.endDate);
  const daysLeft   = Math.max(0, totalDays - daysIn);
  const inFresh    = daysIn >= 0 && daysIn <= FRESH_CYCLE_WINDOW_DAYS;
  const inClosing  = daysLeft <= CYCLE_CLOSING_WINDOW_DAYS;

  return (
    <section className="card p-3.5 sm:p-5 flex items-start gap-3.5">
      <span className="h-10 w-10 rounded-xl bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center shrink-0">
        <CalendarRange size={18} />
      </span>

      <div className="flex-1 min-w-0">
        <div className="flex items-baseline flex-wrap gap-x-2">
          <span className="text-[10px] uppercase tracking-[0.12em] font-extrabold text-[var(--color-edify-muted)]">
            Operational Cycle · {active.label}
          </span>
          <span className="text-caption muted">
            Day {daysIn + 1} of {totalDays + 1}
          </span>
        </div>
        <h2 className="text-[15.5px] font-extrabold tracking-tight mt-0.5">
          {cycleRangeLabel(active)}
        </h2>
        <p className="text-[11.5px] muted leading-snug mt-1 max-w-[80ch]">
          Every visit, training, SSA, cluster meeting and SIT is tracked by its{" "}
          <span className="font-extrabold text-[var(--color-edify-text)]">last date of entry</span>.
          On <span className="font-extrabold text-[var(--color-edify-text)]">October 1</span> these
          counters reset for the new cycle. Historical records stay on each school&apos;s profile —
          they just stop counting toward &quot;what&apos;s outstanding this cycle.&quot;
        </p>

        {inFresh && (
          <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-[11.5px] text-emerald-800 inline-flex items-start gap-1.5">
            <Sparkles size={11} className="mt-0.5 shrink-0" />
            <span>
              <span className="font-extrabold">New operational cycle started.</span>{" "}
              Visits, trainings, SSA, cluster activities, and core school support
              requirements have reset for the new year. A school that completed
              SSA last cycle will show as &quot;Historical Only · Current Cycle SSA
              Missing&quot; — that&apos;s expected.
            </span>
          </div>
        )}

        {inClosing && !inFresh && (
          <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11.5px] text-amber-800 inline-flex items-start gap-1.5">
            <History size={11} className="mt-0.5 shrink-0" />
            <span>
              <span className="font-extrabold">Cycle closes in {daysLeft} day{daysLeft === 1 ? "" : "s"}.</span>{" "}
              On Oct 1 every counter resets. Outstanding visits + trainings + SIT in this
              cycle won&apos;t carry over — close them before Sep 30 or they archive to history.
            </span>
          </div>
        )}
      </div>

      <span className="text-caption muted shrink-0 hidden md:inline-flex items-center gap-0.5">
        Read the rule
        <ChevronRight size={10} />
      </span>
    </section>
  );
}

// ────────── tiny local date helpers ──────────

function ymd(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function daysBetween(fromIso: string, toIso: string): number {
  const ms = new Date(toIso).getTime() - new Date(fromIso).getTime();
  return Math.max(0, Math.floor(ms / 86_400_000));
}
