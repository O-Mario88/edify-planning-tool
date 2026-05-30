"use client";

import { useState } from "react";
import { ClipboardCheck, Clock, Send } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { recentDebriefs, todayFocus } from "@/lib/my-targets-billion-mock";
import { useDemoStore } from "@/components/demo/DemoStore";

// Daily Debrief — the end-of-day reflection. Three sections so the
// card has the visual weight to sit aligned next to Today Focus:
//
//   1. Today's input + Submit
//   2. Tag-a-blocker chip rail (one-click attachments)
//   3. Recent Debriefs — last 3 days, with tag previews, so the CCEO
//      has continuity context and the card fills its row naturally.
export function DailyDebriefCard() {
  const f = todayFocus;
  const { pushToast } = useDemoStore();
  const [debrief, setDebrief] = useState("");
  const [activeBlockers, setActiveBlockers] = useState<Record<string, true>>({});
  const [submitted, setSubmitted] = useState(false);

  function toggleBlocker(chip: string) {
    setActiveBlockers((prev) => {
      const next = { ...prev };
      if (next[chip]) delete next[chip];
      else next[chip] = true;
      return next;
    });
  }

  function handleSubmit() {
    const blockerNames = Object.keys(activeBlockers);
    pushToast({
      tone: "success",
      title: "Daily debrief submitted",
      body: blockerNames.length
        ? `${debrief ? "Note saved. " : ""}Tagged ${blockerNames.length} blocker${blockerNames.length === 1 ? "" : "s"}: ${blockerNames.join(", ")}.`
        : debrief
          ? "Note saved to today's debrief."
          : "Debrief submitted.",
    });
    setSubmitted(true);
    setDebrief("");
    setActiveBlockers({});
    setTimeout(() => setSubmitted(false), 2200);
  }

  return (
    <SectionCard
      icon={<ClipboardCheck size={13} />}
      title="Daily Debrief"
      subtitle={f.debriefHelp}
    >
      {/* Input + submit */}
      <div className="flex items-center gap-1.5">
        <input
          type="text"
          value={debrief}
          onChange={(e) => setDebrief(e.target.value)}
          placeholder="What did you complete today? What got in the way?"
          className="flex-1 h-9 px-2.5 rounded-lg bg-[var(--color-edify-soft)]/40 border border-[var(--color-edify-border)] text-[11.5px] placeholder:text-slate-400 outline-none focus:border-emerald-400 focus:bg-white transition-colors"
        />
        <button
          type="button"
          onClick={handleSubmit}
          disabled={submitted}
          className="inline-flex items-center gap-1 h-9 px-3 rounded-lg bg-emerald-500 hover:bg-emerald-400 disabled:opacity-60 text-white text-[11.5px] font-extrabold shrink-0 transition-colors"
        >
          <Send size={11} />
          {submitted ? "Sent" : "Submit"}
        </button>
      </div>

      {/* Quick blocker tags */}
      <div className="text-[9.5px] uppercase tracking-[0.12em] text-slate-500 font-bold mt-3 mb-1.5">
        Tag a blocker
      </div>
      <div className="flex flex-wrap gap-1.5">
        {f.blockerChips.map((chip) => {
          const active = !!activeBlockers[chip];
          return (
            <button
              key={chip}
              type="button"
              onClick={() => toggleBlocker(chip)}
              {...(active ? { "aria-pressed": "true" as const } : { "aria-pressed": "false" as const })}
              className={
                active
                  ? "inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-caption font-extrabold bg-rose-100 text-rose-700 border border-rose-300 transition-colors"
                  : "inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-caption font-bold bg-[var(--color-edify-soft)]/50 border border-[var(--color-edify-border)] text-slate-700 hover:bg-[var(--color-edify-soft)] transition-colors"
              }
            >
              {active ? "✓" : "+"} {chip}
            </button>
          );
        })}
      </div>

      {/* Recent debriefs — last 3 days. Fills the card to a natural
          height that matches Today Focus on the right, and gives the
          CCEO continuity context before they write today's note. */}
      <div className="mt-4 pt-3 border-t border-[#eef2f4]">
        <div className="text-[9.5px] uppercase tracking-[0.12em] text-slate-500 font-bold mb-2 inline-flex items-center gap-1.5">
          <Clock size={10} className="opacity-70" />
          Recent debriefs
        </div>
        <ul className="space-y-2">
          {recentDebriefs.map((d) => (
            <li
              key={d.key}
              className="rounded-lg border border-[var(--color-edify-border)] bg-white p-2.5"
            >
              <div className="flex items-baseline justify-between gap-2 mb-1">
                <span className="text-[10px] font-extrabold uppercase tracking-wide text-slate-500">
                  {d.date}
                </span>
                {d.tags.length > 0 && (
                  <span className="inline-flex flex-wrap gap-1 justify-end">
                    {d.tags.map((t) => (
                      <span
                        key={t}
                        className="inline-flex items-center px-1.5 py-[1px] rounded-md text-[9px] font-bold bg-rose-50 text-rose-700 border border-rose-200"
                      >
                        {t}
                      </span>
                    ))}
                  </span>
                )}
              </div>
              <p className="text-[11.5px] text-slate-700 leading-snug">{d.note}</p>
            </li>
          ))}
        </ul>
      </div>
    </SectionCard>
  );
}
