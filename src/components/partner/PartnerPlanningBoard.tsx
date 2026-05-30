"use client";

// PartnerPlanningBoard — 4-week visual planner. Each week column
// shows scheduled activities with facilitator + day, plus a
// capacity meter so the partner doesn't over-commit. The
// "needs scheduling" surface lives in PartnerUnscheduledList on
// /partner/schedule, above this board.

import { GraduationCap, Footprints, Truck, ClipboardCheck, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

type PlannedItem = {
  id: string;
  week: "wk22" | "wk23" | "wk24" | "wk25";
  day: string;
  school: string;
  activity: string;
  facilitator: string;
  kind: "training" | "visit" | "delivery" | "observation";
};

const WEEKS = [
  { key: "wk22" as const, label: "Wk 22 · May 12 - 18", capacity: 8 },
  { key: "wk23" as const, label: "Wk 23 · May 19 - 25", capacity: 8 },
  { key: "wk24" as const, label: "Wk 24 · May 26 - Jun 1", capacity: 8 },
  { key: "wk25" as const, label: "Wk 25 · Jun 2 - 8", capacity: 8 },
];

const PLANNED: PlannedItem[] = [
  { id: "P1", week: "wk22", day: "Mon", school: "Hope Primary",     activity: "In-School literacy training", facilitator: "Daniel Mwangi",  kind: "training" },
  { id: "P2", week: "wk22", day: "Tue", school: "Grace Primary",    activity: "Numeracy follow-up visit",    facilitator: "Ruth Kabuye",   kind: "visit" },
  { id: "P3", week: "wk22", day: "Thu", school: "Kireka Primary",   activity: "Training debrief",            facilitator: "Joseph Nsubuga",kind: "training" },
  { id: "P4", week: "wk22", day: "Fri", school: "St. Mary's",       activity: "Leadership support visit",    facilitator: "Ruth Kabuye",   kind: "visit" },
  { id: "P5", week: "wk22", day: "Wed", school: "Namilyango",       activity: "Resource delivery",           facilitator: "Simon Otim",    kind: "delivery" },
  { id: "P6", week: "wk23", day: "Tue", school: "Hope Primary",     activity: "Follow-Up coaching visit",    facilitator: "Daniel Mwangi", kind: "visit" },
  { id: "P7", week: "wk23", day: "Wed", school: "Grace Primary",    activity: "Math improvement coaching",   facilitator: "Irene Mutebi",  kind: "visit" },
  { id: "P8", week: "wk23", day: "Thu", school: "St. Mary's",       activity: "Classroom observation",       facilitator: "Ruth Kabuye",   kind: "observation" },
  { id: "P9", week: "wk24", day: "Mon", school: "Kireka Primary",   activity: "Leadership training",         facilitator: "Joseph Nsubuga",kind: "training" },
  { id: "P10",week: "wk24", day: "Fri", school: "Namilyango",       activity: "Follow-Up visit",             facilitator: "Simon Otim",    kind: "visit" },
  { id: "P11",week: "wk25", day: "Tue", school: "Eden Foundation",  activity: "Observation + coaching",      facilitator: "Daniel Mwangi", kind: "observation" },
];

const KIND_TONE: Record<PlannedItem["kind"], { bg: string; text: string; Icon: LucideIcon }> = {
  training:    { bg: "bg-blue-50",    text: "text-blue-700",    Icon: GraduationCap  },
  visit:       { bg: "bg-amber-50",   text: "text-amber-700",   Icon: Footprints     },
  observation: { bg: "bg-violet-50",  text: "text-violet-700",  Icon: ClipboardCheck },
  delivery:    { bg: "bg-emerald-50", text: "text-emerald-700", Icon: Truck          },
};

export function PartnerPlanningBoard() {
  // The "needs scheduling" strip that used to live at the top of
  // this component has been promoted to its own page-level section
  // (PartnerUnscheduledList) on /partner/schedule. The week board
  // below is now the only piece this component owns.
  return (
    <>
      {/* Week board */}
      <section className="card p-3.5">
        <header className="flex items-start justify-between gap-3 mb-4">
          <div>
            <h3 className="text-[15px] font-extrabold tracking-tight">4-week delivery plan</h3>
            <p className="text-[12px] muted mt-1">
              Each card is a scheduled activity. The meter shows how much of your weekly capacity is used.
            </p>
          </div>
        </header>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
          {WEEKS.map((w) => {
            const items = PLANNED.filter((p) => p.week === w.key);
            const used = items.length;
            const pct = Math.round((used / w.capacity) * 100);
            const meterTone =
              pct >= 100 ? "bg-rose-500" :
              pct >= 75  ? "bg-amber-500" :
              "bg-emerald-500";
            return (
              <div key={w.key} className="rounded-xl border border-[var(--color-edify-divider)] bg-white p-3 flex flex-col gap-2.5">
                <header>
                  <div className="text-caption uppercase tracking-wide font-bold muted">{w.label}</div>
                  <div className="flex items-baseline justify-between gap-2 mt-1">
                    <div className="text-[18px] font-extrabold tabular num-hero text-[var(--color-edify-text)] leading-none">
                      {used}<span className="text-[12px] text-[var(--color-edify-muted)]">/{w.capacity}</span>
                    </div>
                    <span className="text-[10px] uppercase tracking-wide font-bold muted">
                      activities
                    </span>
                  </div>
                  <div className="mt-1.5 h-1.5 w-full rounded-full bg-[var(--color-edify-soft)] overflow-hidden">
                    <div className={cn("h-full transition-all", meterTone)} style={{ width: `${Math.min(100, pct)}%` }} />
                  </div>
                </header>
                <ul className="space-y-1.5 flex-1">
                  {items.length === 0 ? (
                    <li className="text-[11px] muted italic text-center py-3">Nothing scheduled.</li>
                  ) : (
                    items.map((p) => <PlannedRow key={p.id} item={p} />)
                  )}
                </ul>
                <button
                  type="button"
                  className="inline-flex items-center justify-center h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)]/60"
                >
                  + Add to this week
                </button>
              </div>
            );
          })}
        </div>
      </section>
    </>
  );
}

function PlannedRow({ item }: { item: PlannedItem }) {
  const tone = KIND_TONE[item.kind];
  return (
    <li className="rounded-md border border-[var(--color-edify-divider)] bg-white p-2 flex items-start gap-2">
      <span className={cn("grid place-items-center h-6 w-6 rounded-md shrink-0", tone.bg, tone.text)}>
        <tone.Icon size={11} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[11.5px] font-extrabold tracking-tight truncate">{item.school}</div>
        <div className="text-caption muted leading-tight truncate">{item.activity}</div>
        <div className="text-[10px] muted mt-0.5 inline-flex items-center gap-1">
          <span className="font-bold">{item.day}</span>
          <span>·</span>
          <span>{item.facilitator}</span>
        </div>
      </div>
    </li>
  );
}
