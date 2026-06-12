// My Plan — daily field briefing.
//
// Pure functions over the already-sectioned MyPlanItem[] that produce
//   (1) one warm, intelligent sentence for the hero,
//   (2) a short verdict ("Clear the blockers first", "On track", …),
//   (3) the five snapshot chips the urgency strip renders.
//
// Read-only. No I/O. The page passes whatever the data path produced —
// no mock fallbacks, no fork.

import type { MyPlanSection, MyPlanSectionKey, MyPlanItem } from "./my-plan-sections";

// ── Brief ────────────────────────────────────────────────────────────

export type BriefVerdict =
  | "blockers"       // waiting > 0 — rose
  | "fieldHeavy"     // many due today — amber
  | "needsAttention" // slip-limit close — amber
  | "fundingHold"    // scheduled work waiting for funds — sky
  | "onTrack"        // healthy — emerald
  | "clear";         // nothing urgent — emerald

export type DailyBrief = {
  greeting: string;     // "Good morning, Sarah."
  dateLabel: string;    // "Friday, June 12"
  focus: string;        // the one smart sentence
  secondary?: string;   // optional secondary nuance
  verdict: BriefVerdict;
  verdictLabel: string; // chip copy
};

const VERDICT_LABEL: Record<BriefVerdict, string> = {
  blockers: "Clear the blockers first",
  fieldHeavy: "Today is field-heavy",
  needsAttention: "One needs attention",
  fundingHold: "Funds pending",
  onTrack: "On track",
  clear: "Plan clear",
};

function timeGreeting(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function firstName(name: string): string {
  const trimmed = (name ?? "").trim();
  if (!trimmed) return "there";
  return trimmed.split(/\s+/)[0];
}

function plural(n: number, singular: string, pluralForm?: string): string {
  if (n === 1) return singular;
  return pluralForm ?? `${singular}s`;
}

function itemsOf(sections: MyPlanSection[], key: MyPlanSectionKey): MyPlanItem[] {
  return sections.find((s) => s.key === key)?.items ?? [];
}

export function dailyBrief(opts: {
  name: string;
  now?: Date;
  sections: MyPlanSection[];
}): DailyBrief {
  const now = opts.now ?? new Date();
  const dateLabel = now.toLocaleDateString("en-UG", {
    weekday: "long", month: "long", day: "numeric", timeZone: "UTC",
  });
  const greeting = `${timeGreeting(now.getUTCHours())}, ${firstName(opts.name)}.`;

  const todayIso = now.toISOString().slice(0, 10);
  const waiting = itemsOf(opts.sections, "waitingOnMe");
  const attention = itemsOf(opts.sections, "needsAttention");
  const dueToday = itemsOf(opts.sections, "dueToday");
  const week = itemsOf(opts.sections, "thisWeek");
  const month = itemsOf(opts.sections, "thisMonth");
  const overdue = dueToday.filter((i) => (i.dateIso ?? "9999").slice(0, 10) < todayIso);
  const slipNow = attention.find((i) => i.atSlipLimit);
  const fundingPending = [...dueToday, ...week].filter((i) => i.funding === "Requested");

  let verdict: BriefVerdict = "onTrack";
  let focus = "Your plan is clear. Nothing urgent is waiting on you.";
  let secondary: string | undefined;

  if (waiting.length > 0 && dueToday.length > 0) {
    verdict = "blockers";
    focus = `Start with ${waiting.length} ${plural(waiting.length, "item")} waiting on you, then deliver today's ${dueToday.length} scheduled ${plural(dueToday.length, "activity", "activities")}.`;
    if (slipNow) {
      secondary = `One ${slipNow.typeLabel.toLowerCase()} is at slip limit — deliver or escalate.`;
    } else if (week.length > 0) {
      secondary = `Your week is on track. ${week.length} more ${plural(week.length, "activity", "activities")} scheduled.`;
    }
  } else if (waiting.length > 0) {
    verdict = "blockers";
    focus = `Clear ${waiting.length} ${plural(waiting.length, "blocker")} first — they're holding verification or payment.`;
    if (week.length > 0) secondary = `Your week is on track. ${week.length} more ${plural(week.length, "activity", "activities")} scheduled.`;
  } else if (slipNow) {
    verdict = "needsAttention";
    focus = "One activity is close to slip limit. Deliver it or escalate.";
    if (dueToday.length > 0) secondary = `Then run today's ${dueToday.length} field ${plural(dueToday.length, "activity", "activities")}.`;
  } else if (overdue.length > 0) {
    verdict = "blockers";
    focus = `${overdue.length} ${plural(overdue.length, "activity", "activities")} overdue. Catch up today, then move forward.`;
  } else if (dueToday.length >= 3) {
    verdict = "fieldHeavy";
    focus = `Field-heavy day — ${dueToday.length} scheduled ${plural(dueToday.length, "activity", "activities")} due. Plan your route before travel.`;
  } else if (dueToday.length > 0) {
    verdict = "onTrack";
    focus = `Deliver today's ${dueToday.length} scheduled ${plural(dueToday.length, "activity", "activities")}, then prepare for the week.`;
  } else if (fundingPending.length > 0) {
    verdict = "fundingHold";
    focus = `${fundingPending.length} scheduled ${plural(fundingPending.length, "item")} waiting on funds. Review funding before travel.`;
  } else if (week.length > 0 || month.length > 0) {
    verdict = "onTrack";
    const count = week.length || month.length;
    focus = `No blockers today — your next ${count} ${plural(count, "activity", "activities")} ${week.length ? "this week" : "this month"} ${plural(count, "is", "are")} ready.`;
  } else {
    verdict = "clear";
  }

  return { greeting, dateLabel, focus, secondary, verdict, verdictLabel: VERDICT_LABEL[verdict] };
}

// ── Snapshot ─────────────────────────────────────────────────────────

export type SnapshotChipKey = "open" | "waiting" | "today" | "week" | "attention";
export type SnapshotTone = "emerald" | "sky" | "amber" | "rose" | "violet" | "slate";

export type SnapshotChip = {
  key: SnapshotChipKey;
  label: string;
  count: number;
  caption?: string;
  /** Hash for scroll-to (matches the lane anchor id). */
  target: string;
  tone: SnapshotTone;
};

export function snapshotChips(sections: MyPlanSection[], now: Date = new Date()): SnapshotChip[] {
  const todayIso = now.toISOString().slice(0, 10);
  const waiting = itemsOf(sections, "waitingOnMe");
  const attention = itemsOf(sections, "needsAttention");
  const dueToday = itemsOf(sections, "dueToday");
  const week = itemsOf(sections, "thisWeek");
  const month = itemsOf(sections, "thisMonth");
  const open = [...waiting, ...attention, ...dueToday, ...week, ...month].length;
  const overdue = dueToday.filter((i) => (i.dateIso ?? "9999").slice(0, 10) < todayIso).length;

  return [
    {
      key: "open",
      label: "Open items",
      count: open,
      target: "#lane-waiting",
      tone: "emerald",
      caption: open ? `${open === 1 ? "item" : "items"} in play` : "all clear",
    },
    {
      key: "waiting",
      label: "Waiting on Me",
      count: waiting.length,
      target: "#lane-waiting",
      tone: waiting.length > 0 ? "sky" : "slate",
      caption: waiting.length ? "blocks to clear" : "no blockers",
    },
    {
      key: "today",
      label: "Due Today",
      count: dueToday.length,
      target: "#lane-today",
      tone: overdue ? "rose" : dueToday.length ? "amber" : "slate",
      caption: overdue
        ? `${overdue} overdue`
        : dueToday.length
          ? "field actions"
          : "you can breathe",
    },
    {
      key: "week",
      label: "This Week",
      count: week.length,
      target: "#lane-week",
      tone: week.length ? "violet" : "slate",
      caption: week.length ? "scheduled" : "nothing left",
    },
    {
      key: "attention",
      label: "Needs Attention",
      count: attention.length,
      target: "#lane-attention",
      tone: attention.length ? "rose" : "slate",
      caption: attention.length ? "rescheduled" : "all steady",
    },
  ];
}
