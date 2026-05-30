"use client";

import { CalendarRange, ShieldCheck, Sparkles, ArrowRight, AlertTriangle, RotateCw } from "lucide-react";
import { leaveRequests, publicHolidays, autoBlockedConflicts, isInRange } from "@/lib/leave-mock";

// LeaveTodaySnapshot — the answer-this-first hero.
//
// Most planning dashboards open with an undifferentiated wall of
// numbers; this card opens with what the planner needs to *do today*.
// Pulls live counts from the same engine that powers the rest of the
// page so the hero never lies.
//
// Visual: soft gradient halo + bold date + three contextual stats +
// one primary CTA (review conflicts). Inspired by the Stripe
// Dashboard "Today" hero and the Airbnb host calendar greeting.
export function LeaveTodaySnapshot() {
  // Default to a synthetic "today" inside the demo dataset (Jul 15,
  // 2025) so the snapshot always shows realistic numbers without
  // depending on real-world wall clock.
  const today = "2025-07-15";
  const todayDate = new Date(today + "T00:00:00");
  const dateLabel = todayDate.toLocaleDateString("en-US", {
    weekday: "long",
    month:   "long",
    day:     "numeric",
    year:    "numeric",
  });

  const onLeaveToday = leaveRequests.filter(
    (r) => r.approvalStatus === "Approved" && isInRange(today, r.startDate, r.endDate),
  ).length;

  const holidayToday = publicHolidays.find((h) => h.date === today);

  const criticalConflicts = autoBlockedConflicts.filter(
    (c) => c.severity === "Critical" || c.severity === "High",
  ).length;

  const autoRescheduled = autoBlockedConflicts.filter(
    (c) => c.action === "Auto-reschedule",
  ).length;

  return (
    <section
      className="relative overflow-hidden rounded-2xl border border-[var(--color-edify-divider)] bg-white shadow-[0_1px_2px_rgba(15,23,32,0.04),0_18px_44px_-24px_rgba(15,23,32,0.18)]"
    >
      {/* Soft halo backgrounds */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          backgroundImage:
            "radial-gradient(900px 320px at 0% 0%, rgba(16,185,129,0.10) 0%, transparent 60%), radial-gradient(700px 260px at 100% 0%, rgba(99,102,241,0.08) 0%, transparent 55%)",
        }}
      />

      <div className="grid grid-cols-1 lg:grid-cols-[1.4fr_1fr] gap-4 lg:gap-6 p-5 lg:p-6">
        {/* Left — date + summary */}
        <div className="min-w-0">
          <div className="inline-flex items-center gap-2 text-caption font-extrabold uppercase tracking-[0.14em] text-emerald-700">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
            Today&apos;s plan
          </div>
          <h2 className="text-[22px] lg:text-[26px] font-extrabold tracking-tight mt-1.5 leading-tight">
            {dateLabel}
          </h2>
          <p className="text-body text-secondary mt-1 max-w-[520px] leading-snug">
            The Planning Engine is actively blocking conflicts, auto-rescheduling overlaps, and surfacing decisions you need to make.
          </p>

          {/* Three contextual stats — bold, scannable, no chrome noise */}
          <div className="mt-4 grid grid-cols-3 gap-3">
            <SnapStat
              Icon={CalendarRange}
              label="On leave today"
              value={onLeaveToday}
              unit={onLeaveToday === 1 ? "person" : "people"}
              tone="amber"
            />
            <SnapStat
              Icon={RotateCw}
              label="Auto-rescheduled"
              value={autoRescheduled}
              unit={autoRescheduled === 1 ? "activity" : "activities"}
              tone="emerald"
            />
            <SnapStat
              Icon={AlertTriangle}
              label="Need review"
              value={criticalConflicts}
              unit={criticalConflicts === 1 ? "conflict" : "conflicts"}
              tone={criticalConflicts > 0 ? "rose" : "slate"}
            />
          </div>
        </div>

        {/* Right — primary actions */}
        <div className="flex flex-col gap-2 lg:items-end lg:justify-between">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="inline-flex items-center gap-1.5 h-7 px-2 rounded-full bg-white/80 border border-emerald-200 text-emerald-700 text-[11px] font-extrabold">
              <ShieldCheck size={11} /> Engine Active
            </span>
            {holidayToday && (
              <span className="inline-flex items-center gap-1.5 h-7 px-2 rounded-full bg-rose-50 border border-rose-200 text-rose-700 text-[11px] font-extrabold">
                <Sparkles size={11} /> {holidayToday.title}
              </span>
            )}
          </div>

          <div className="flex flex-col gap-2 w-full lg:w-auto">
            {criticalConflicts > 0 && (
              <a
                href="#conflicts"
                className="inline-flex items-center justify-center gap-1.5 h-11 px-4 rounded-xl bg-rose-600 hover:bg-rose-700 text-white text-body font-extrabold shadow-[0_10px_28px_-12px_rgba(190,18,60,0.5)]"
              >
                Review {criticalConflicts} {criticalConflicts === 1 ? "conflict" : "conflicts"}
                <ArrowRight size={13} />
              </a>
            )}
            <a
              href="#planning-calendar"
              className="inline-flex items-center justify-center gap-1.5 h-10 px-4 rounded-xl bg-white border border-[var(--color-edify-border)] text-body font-semibold text-[#0f1720] hover:bg-[var(--color-edify-soft)]/40"
            >
              Open calendar
              <ArrowRight size={13} className="text-[var(--color-edify-muted)]" />
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}

// ────────── SnapStat — premium stat tile used inside the hero ──────────

const TONE: Record<"amber" | "emerald" | "rose" | "slate", { iconBg: string; iconText: string; valueText: string }> = {
  amber:   { iconBg: "bg-amber-100",   iconText: "text-amber-700",   valueText: "text-amber-700"   },
  emerald: { iconBg: "bg-emerald-100", iconText: "text-emerald-700", valueText: "text-emerald-700" },
  rose:    { iconBg: "bg-rose-100",    iconText: "text-rose-700",    valueText: "text-rose-700"    },
  slate:   { iconBg: "bg-slate-100",   iconText: "text-slate-600",   valueText: "text-[#0f1720]"   },
};

function SnapStat({
  Icon,
  label,
  value,
  unit,
  tone,
}: {
  Icon:  typeof CalendarRange;
  label: string;
  value: number;
  unit:  string;
  tone:  "amber" | "emerald" | "rose" | "slate";
}) {
  const t = TONE[tone];
  return (
    <div className="flex items-start gap-2.5">
      <span className={`h-9 w-9 rounded-xl grid place-items-center shrink-0 ${t.iconBg} ${t.iconText}`}>
        <Icon size={15} />
      </span>
      <div className="min-w-0">
        <div className="text-caption font-bold uppercase tracking-[0.06em] text-muted">{label}</div>
        <div className="flex items-baseline gap-1 mt-0.5">
          <span className={`text-[22px] font-extrabold tabular leading-none ${t.valueText}`}>{value}</span>
          <span className="text-[11px] font-semibold text-muted">{unit}</span>
        </div>
      </div>
    </div>
  );
}
