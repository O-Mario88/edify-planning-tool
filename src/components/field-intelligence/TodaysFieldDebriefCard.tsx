"use client";

import { useState } from "react";
import {
  ClipboardList,
  CheckCircle2,
  ChevronDown,
  Star,
  ThumbsUp,
  AlertTriangle,
  Frown,
  CircleSlash,
  Target,
  TrendingUp,
  Sparkles,
  Save,
  Send,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { type DayOutcome } from "@/lib/field-intelligence-mock";

const OUTCOMES: { key: DayOutcome; Icon: LucideIcon }[] = [
  { key: "Very Successful",          Icon: Star          },
  { key: "Good",                     Icon: ThumbsUp      },
  { key: "Challenging",              Icon: AlertTriangle },
  { key: "Very Difficult",           Icon: Frown         },
  { key: "Could Not Execute Planned Work", Icon: CircleSlash    },
];

export function TodaysFieldDebriefCard({
  staffName,
  planned,
  completed,
  verified,
  incomplete,
  rawAchievementPct,
  contextAdjustedPct,
}: {
  staffName: string;
  planned: number;
  completed: number;
  verified: number;
  incomplete: number;
  rawAchievementPct: number;
  contextAdjustedPct: number;
}) {
  const [outcome, setOutcome] = useState<DayOutcome | null>(null);
  const [whatWentWell, setWhatWentWell] = useState("");
  const [whatDidNotGoWell, setWhatDidNotGoWell] = useState("");
  const [whyItDidNotGoWell, setWhyItDidNotGoWell] = useState("");
  const [whatStaffDidAboutIt, setWhatStaffDidAboutIt] = useState("");
  const [whatToDoDifferently, setWhatToDoDifferently] = useState("");

  return (
    <article className="card rounded-2xl flex flex-col">
      {/* Header */}
      <header className="px-4 lg:px-5 pt-4 pb-3 flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="h-7 w-7 rounded-md bg-emerald-100 text-emerald-700 grid place-items-center">
            <ClipboardList size={14} />
          </span>
          <h2 className="text-[15px] font-extrabold tracking-tight">
            Today&apos;s Field Debrief
          </h2>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700 px-2.5 py-1 text-caption font-semibold">
            <CheckCircle2 size={11} />
            Auto-saved 2m ago
          </span>
          <button type="button" aria-label="Options" className="h-7 w-7 rounded-md grid place-items-center hover:bg-[var(--color-edify-soft)]/60">
            <ChevronDown size={14} className="text-[var(--color-edify-muted)]" />
          </button>
        </div>
      </header>

      <div className="px-4 lg:px-5 pb-2 text-[11.5px] muted">
        <span className="font-semibold text-[var(--color-edify-text)]">{staffName}</span>
        {" · "}The system has filled in your activity numbers — you only need to share field context.
      </div>

      {/* Auto-filled stats: Planned / Completed / Verified / Incomplete */}
      <section className="mx-4 lg:mx-5 mt-3 grid grid-cols-4 gap-2 rounded-2xl bg-[var(--color-edify-soft)]/40 border border-[var(--color-edify-border)] p-2.5">
        <Stat label="PLANNED"     value={planned}    tone="text-[var(--color-edify-text)]" />
        <Stat label="COMPLETED"   value={completed}  tone="text-emerald-600" />
        <Stat label="VERIFIED"    value={verified}   tone="text-emerald-600" />
        <Stat label="INCOMPLETE"  value={incomplete} tone="text-rose-600" />
      </section>

      {/* Achievement: Raw / Context-Adjusted */}
      <section className="mx-4 lg:mx-5 mt-2 grid grid-cols-2 gap-2">
        <AchievementCard
          Icon={Target}
          label="Raw Achievement"
          value={`${rawAchievementPct}%`}
          tone="violet"
        />
        <AchievementCard
          Icon={TrendingUp}
          label="Context-Adjusted"
          value={`${contextAdjustedPct}%`}
          tone="green"
        />
      </section>

      {/* Q1 — Day outcome */}
      <fieldset className="mx-4 lg:mx-5 mt-4">
        <legend className="text-body font-extrabold tracking-tight">
          1. How did your day go?
        </legend>
        <div className="mt-2 flex flex-wrap gap-2">
          {OUTCOMES.map((o) => {
            const active = outcome === o.key;
            return (
              <button
                key={o.key}
                type="button"
                onClick={() => setOutcome(o.key)}
                className={cn(
                  "h-9 px-3 rounded-xl border text-[12px] font-semibold inline-flex items-center gap-1.5 transition-colors",
                  active
                    ? "bg-[var(--color-edify-primary)] border-[var(--color-edify-primary)] text-white"
                    : "bg-white border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/60",
                )}
              >
                <o.Icon size={13} />
                {o.key}
              </button>
            );
          })}
        </div>
      </fieldset>

      {/* Q2 — What went well */}
      <Question
        idx={2}
        title="What went well?"
        placeholder="Share what went well today…"
        value={whatWentWell}
        onChange={setWhatWentWell}
      />

      {/* Q3 — What did not go well */}
      <Question
        idx={3}
        title="What did not go well?"
        placeholder="Share what did not go well…"
        value={whatDidNotGoWell}
        onChange={setWhatDidNotGoWell}
      />

      {/* Q4 — Why it did not go well */}
      <Question
        idx={4}
        title="Why did it not go well?"
        placeholder="Share the root causes or reasons…"
        value={whyItDidNotGoWell}
        onChange={setWhyItDidNotGoWell}
      />

      {/* Q5 + Q6 — side by side */}
      <section className="mx-4 lg:mx-5 mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
        <Question
          idx={5}
          title="What did you do about it today?"
          placeholder="Describe the actions you took…"
          value={whatStaffDidAboutIt}
          onChange={setWhatStaffDidAboutIt}
          inline
        />
        <Question
          idx={6}
          title="What will you do differently next time?"
          placeholder="Share what you will do differently…"
          value={whatToDoDifferently}
          onChange={setWhatToDoDifferently}
          inline
        />
      </section>

      {/* Footer — AI summary affordance + actions */}
      <footer className="mx-4 lg:mx-5 mt-5 mb-4 pt-3 border-t border-[#eef2f4] flex items-center justify-between gap-3">
        <span className="inline-flex items-center gap-2 rounded-xl bg-violet-50 border border-violet-200 text-violet-700 px-3 py-1.5 text-[11px] font-semibold">
          <Sparkles size={12} />
          AI can summarize this for weekly review
          <span className="inline-block px-1.5 py-[1px] rounded-md bg-violet-200/70 text-[9px] font-extrabold tracking-wide">
            Beta
          </span>
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="h-9 px-3.5 rounded-xl border border-[var(--color-edify-border)] bg-white text-body font-semibold inline-flex items-center gap-1.5 hover:bg-[var(--color-edify-soft)]/60"
          >
            <Save size={13} />
            Save Draft
          </button>
          <button
            type="button"
            className="h-9 px-3.5 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-white text-body font-semibold inline-flex items-center gap-1.5 shadow-sm shadow-emerald-500/25"
          >
            <Send size={12} />
            Submit Debrief
          </button>
        </div>
      </footer>
    </article>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="text-center">
      <div className="text-[9.5px] font-bold tracking-wide muted uppercase">{label}</div>
      <div className={cn("text-[22px] font-extrabold tabular leading-none mt-1", tone)}>{value}</div>
    </div>
  );
}

function AchievementCard({
  Icon,
  label,
  value,
  tone,
}: {
  Icon: LucideIcon;
  label: string;
  value: string;
  tone: "violet" | "green";
}) {
  const styles =
    tone === "violet"
      ? "bg-violet-50 border-violet-200 text-violet-700"
      : "bg-emerald-50 border-emerald-200 text-emerald-700";
  return (
    <div className={cn("rounded-xl border p-3 flex items-center gap-3", styles)}>
      <div className="flex-1 min-w-0">
        <div className="text-[11px] font-semibold leading-tight">{label}</div>
        <div className="text-[26px] font-extrabold tabular leading-none mt-1 text-[var(--color-edify-text)]">
          {value}
        </div>
      </div>
      <span className="h-10 w-10 rounded-xl bg-white grid place-items-center shrink-0">
        <Icon size={18} />
      </span>
    </div>
  );
}

function Question({
  idx,
  title,
  placeholder,
  value,
  onChange,
  inline = false,
}: {
  idx: number;
  title: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  inline?: boolean;
}) {
  return (
    <fieldset className={inline ? "" : "mx-4 lg:mx-5 mt-4"}>
      <legend className="text-body font-extrabold tracking-tight">
        {idx}. {title}
      </legend>
      <div className="relative mt-2">
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value.slice(0, 1000))}
          placeholder={placeholder}
          maxLength={1000}
          rows={inline ? 3 : 2}
          className="w-full rounded-xl border border-[var(--color-edify-border)] bg-white text-body px-3 py-2 placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30 resize-none"
        />
        <span className="absolute bottom-2 right-3 text-[10px] muted tabular pointer-events-none">
          {value.length}/1000
        </span>
      </div>
    </fieldset>
  );
}
