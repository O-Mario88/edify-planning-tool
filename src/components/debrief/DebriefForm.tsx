"use client";

// DebriefForm — the unified debrief submission form. One component, three
// variants: CCEO Field, PL Program, Partner Activity. The submitterRole
// prop selects the prompt set; the category picker, priority chips, and
// routed-recipient strip are all spec-aligned and shared.
//
// Submit is mock today (logs + redirects to a success state). The real
// store wires into the existing field-intelligence-mock the next phase.

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Activity,
  AlertOctagon,
  CheckCircle2,
  ChevronRight,
  Coffee,
  Loader2,
  Send,
  ShieldCheck,
  Sparkles,
  Sun,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  categoriesForRole,
  type CategoryOption,
} from "@/lib/debrief/categories";
import { PRIORITIES, type PriorityOption } from "@/lib/debrief/priorities";
import {
  promptsForRole,
  subtitleForRole,
  titleForRole,
} from "@/lib/debrief/prompts";
import {
  labelForRecipient,
  routeRecipients,
} from "@/lib/debrief/routing";
import type {
  DebriefCategory,
  DebriefMood,
  DebriefPriority,
  DebriefSubmitterRole,
} from "@/lib/debrief/types";

const MOOD_OPTIONS: { key: DebriefMood; Icon: LucideIcon; tone: string }[] = [
  { key: "Calm",       Icon: Sun,         tone: "text-emerald-600" },
  { key: "Busy",       Icon: Activity,    tone: "text-sky-600" },
  { key: "Difficult",  Icon: Coffee,      tone: "text-amber-600" },
  { key: "Blocked",    Icon: AlertOctagon, tone: "text-orange-600" },
  { key: "Successful", Icon: Sparkles,    tone: "text-violet-600" },
  { key: "Urgent",     Icon: Zap,         tone: "text-rose-600" },
];

export function DebriefForm({
  submitterRole,
  submitterName,
}: {
  submitterRole: DebriefSubmitterRole;
  submitterName: string;
}) {
  const router = useRouter();
  const prompts = useMemo(() => promptsForRole(submitterRole), [submitterRole]);
  const allCategories = useMemo(() => categoriesForRole(submitterRole), [submitterRole]);

  const [mood, setMood] = useState<DebriefMood | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [selectedCategories, setSelectedCategories] = useState<Set<DebriefCategory>>(new Set());
  const [priority, setPriority] = useState<DebriefPriority>("Normal");
  const [submitting, setSubmitting] = useState(false);
  const [submittedAt, setSubmittedAt] = useState<Date | null>(null);

  const recipients = useMemo(
    () => routeRecipients(submitterRole, [...selectedCategories], priority),
    [submitterRole, selectedCategories, priority],
  );

  const canSubmit =
    mood !== null &&
    // Spec: at least one substantive answer + at least one category.
    Object.values(answers).some((v) => v.trim().length > 0) &&
    selectedCategories.size > 0 &&
    !submitting;

  function toggleCategory(key: DebriefCategory) {
    setSelectedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);

    // eslint-disable-next-line no-console
    console.info("[debrief] submission draft", {
      submitterRole,
      submitterName,
      mood,
      categories: [...selectedCategories],
      priority,
      answers: prompts.map((p) => ({ key: p.key, prompt: p.prompt, text: answers[p.key] ?? "" })),
      routedTo: recipients,
    });

    // Fire the server action — persists the debrief (mock) and emits
    // a system message into the inbox of every reviewer the routing
    // engine flagged. We don't await navigation; the client-side
    // success card renders below for the existing UX, while HR/CD/PL
    // inboxes light up server-side. Best-effort: if the action fails
    // (e.g. not signed in), we still show success so the demo flow
    // doesn't stall.
    try {
      const fd = new FormData();
      fd.append("submitterRole", submitterRole);
      fd.append("categories",    [...selectedCategories].join(","));
      fd.append("priority",      priority);
      const { submitDebriefAction } = await import("@/app/(shell)/debriefs/new/actions");
      await submitDebriefAction(fd);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("[debrief] system-message emit failed", err);
    }

    await new Promise((r) => setTimeout(r, 600));
    setSubmittedAt(new Date());
    setSubmitting(false);
  }

  if (submittedAt) {
    return <DebriefSuccessCard at={submittedAt} recipients={recipients} priority={priority} onClose={() => router.push("/dashboard")} />;
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <header className="card p-3.5 lg:p-5">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <h1 className="text-[18px] lg:text-[20px] font-extrabold tracking-tight">
              {titleForRole(submitterRole)}
            </h1>
            <p className="text-body muted mt-1 leading-snug max-w-[640px]">
              {subtitleForRole(submitterRole)}
            </p>
          </div>
          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700 text-[11px] font-semibold">
            <ShieldCheck size={11} />
            Healthy framing — supportive, not punitive
          </div>
        </div>
      </header>

      <section className="card p-3.5 lg:p-5">
        <h2 className="text-[13px] font-extrabold tracking-tight">How was today&apos;s field reality?</h2>
        <p className="text-[11.5px] muted mt-1">Pick the one closest to your day. No wrong answer.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {MOOD_OPTIONS.map((m) => {
            const active = mood === m.key;
            return (
              <button
                key={m.key}
                type="button"
                onClick={() => setMood(m.key)}
                className={cn(
                  "h-10 px-3.5 rounded-xl border text-body font-semibold inline-flex items-center gap-2 transition-colors",
                  active
                    ? "bg-[var(--color-edify-primary)] border-[var(--color-edify-primary)] text-white"
                    : "bg-white border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/60",
                )}
              >
                <m.Icon size={14} className={active ? "text-white" : m.tone} />
                {m.key}
              </button>
            );
          })}
        </div>
      </section>

      <section className="card p-3.5 lg:p-5 space-y-4">
        {prompts.map((p, idx) => (
          <fieldset key={p.key}>
            <legend className="text-body font-extrabold tracking-tight">
              {idx + 1}. {p.prompt}
            </legend>
            <div className="relative mt-2">
              <textarea
                value={answers[p.key] ?? ""}
                onChange={(e) =>
                  setAnswers((prev) => ({ ...prev, [p.key]: e.target.value.slice(0, 1000) }))
                }
                placeholder={p.placeholder}
                maxLength={1000}
                rows={p.short ? 2 : 3}
                className="w-full rounded-xl border border-[var(--color-edify-border)] bg-white text-body px-3 py-2 placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30 resize-none"
              />
              <span className="absolute bottom-2 right-3 text-[10px] muted tabular pointer-events-none">
                {(answers[p.key]?.length ?? 0)}/1000
              </span>
            </div>
          </fieldset>
        ))}
      </section>

      <CategorySection
        options={allCategories}
        selected={selectedCategories}
        onToggle={toggleCategory}
      />

      <PrioritySection value={priority} onChange={setPriority} />

      <RecipientStrip recipients={recipients} />

      <footer className="card p-3.5 lg:p-5 flex items-center justify-between gap-3 flex-wrap">
        <div className="text-[11.5px] muted leading-snug max-w-[420px]">
          We use this to support staff and improve programs — never to punish.
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => router.back()}
            className="h-10 px-3.5 rounded-xl border border-[var(--color-edify-border)] bg-white text-body font-semibold hover:bg-[var(--color-edify-soft)]/60"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!canSubmit}
            className={cn(
              "h-10 px-4 rounded-xl text-white text-body font-extrabold inline-flex items-center gap-2 shadow-sm transition-colors",
              canSubmit
                ? "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] shadow-[var(--focus-ring)]"
                : "bg-[var(--color-edify-muted)] cursor-not-allowed",
            )}
          >
            {submitting ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
            {submitting ? "Submitting…" : "Submit Debrief"}
          </button>
        </div>
      </footer>
    </form>
  );
}

// ───────────────────────── Sub-components ─────────────────────────

function CategorySection({
  options,
  selected,
  onToggle,
}: {
  options:  CategoryOption[];
  selected: Set<DebriefCategory>;
  onToggle: (key: DebriefCategory) => void;
}) {
  return (
    <section className="card p-3.5 lg:p-5">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-[13px] font-extrabold tracking-tight">Categories</h2>
        <span className="text-[11px] muted">Pick all that apply — routing depends on these.</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {options.map((o) => {
          const active = selected.has(o.key);
          return (
            <button
              key={o.key}
              type="button"
              onClick={() => onToggle(o.key)}
              className={cn(
                "h-8 px-3 rounded-full border text-[12px] font-semibold inline-flex items-center gap-1.5 transition-colors",
                active
                  ? "bg-[var(--color-edify-primary)] border-[var(--color-edify-primary)] text-white"
                  : "bg-white border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/60",
              )}
            >
              {active && <CheckCircle2 size={11} />}
              {o.label}
            </button>
          );
        })}
      </div>
    </section>
  );
}

const PRIORITY_TONE: Record<PriorityOption["tone"], { active: string; idle: string; dot: string }> = {
  slate: { active: "bg-slate-700 border-slate-700 text-white",     idle: "bg-white border-[var(--color-edify-border)]", dot: "bg-slate-400" },
  blue:  { active: "bg-blue-600 border-blue-600 text-white",       idle: "bg-white border-[var(--color-edify-border)]", dot: "bg-blue-500" },
  amber: { active: "bg-amber-500 border-amber-500 text-white",     idle: "bg-white border-[var(--color-edify-border)]", dot: "bg-amber-500" },
  rose:  { active: "bg-rose-600 border-rose-600 text-white",       idle: "bg-white border-[var(--color-edify-border)]", dot: "bg-rose-500" },
};

function PrioritySection({
  value,
  onChange,
}: {
  value:    DebriefPriority;
  onChange: (p: DebriefPriority) => void;
}) {
  return (
    <section className="card p-3.5 lg:p-5">
      <h2 className="text-[13px] font-extrabold tracking-tight">Priority</h2>
      <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
        {PRIORITIES.map((p) => {
          const active = value === p.key;
          const tone = PRIORITY_TONE[p.tone];
          return (
            <button
              key={p.key}
              type="button"
              onClick={() => onChange(p.key)}
              className={cn(
                "text-left rounded-xl border px-3 py-2.5 transition-colors",
                active ? tone.active : tone.idle,
              )}
            >
              <div className="flex items-center gap-2">
                <span className={cn("h-2 w-2 rounded-full", active ? "bg-white/80" : tone.dot)} />
                <span className="text-body font-extrabold">{p.label}</span>
              </div>
              <p className={cn("text-[11px] mt-1 leading-snug", active ? "text-white/85" : "muted")}>
                {p.caption}
              </p>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function RecipientStrip({ recipients }: { recipients: ReturnType<typeof routeRecipients> }) {
  return (
    <section className="card p-3.5 lg:p-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <h2 className="text-[13px] font-extrabold tracking-tight">Who will see this</h2>
          <p className="text-[11.5px] muted mt-1">Auto-routed from your categories + priority. Read-only.</p>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          {recipients.length === 0 ? (
            <span className="text-[11.5px] muted italic">Pick a category to see routing.</span>
          ) : (
            recipients.map((r) => (
              <span
                key={r}
                className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full bg-[var(--color-edify-soft)]/70 border border-[var(--color-edify-border)] text-[11.5px] font-semibold"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                {labelForRecipient(r)}
              </span>
            ))
          )}
        </div>
      </div>
    </section>
  );
}

function DebriefSuccessCard({
  at,
  recipients,
  priority,
  onClose,
}: {
  at:         Date;
  recipients: ReturnType<typeof routeRecipients>;
  priority:   DebriefPriority;
  onClose:    () => void;
}) {
  const time = at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return (
    <article className="card rounded-2xl p-6 text-center">
      <div className="mx-auto h-14 w-14 rounded-full bg-emerald-100 text-emerald-700 grid place-items-center">
        <CheckCircle2 size={26} />
      </div>
      <h2 className="text-[18px] font-extrabold tracking-tight mt-4">Debrief submitted</h2>
      <p className="text-[13px] muted mt-2 max-w-[420px] mx-auto leading-snug">
        Submitted at {time}. Status: <span className="font-semibold text-[var(--color-edify-text)]">Awaiting review</span>.
        {priority === "Critical" || priority === "Urgent"
          ? " Marked as " + priority + " — reviewers are paged immediately."
          : ""}
      </p>
      <div className="mt-4 flex flex-wrap items-center justify-center gap-1.5">
        {recipients.map((r) => (
          <span key={r} className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full bg-[var(--color-edify-soft)]/70 border border-[var(--color-edify-border)] text-[11.5px] font-semibold">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            {labelForRecipient(r)}
          </span>
        ))}
      </div>
      <button
        type="button"
        onClick={onClose}
        className="mt-5 h-10 px-4 rounded-xl bg-[var(--color-edify-primary)] text-white text-body font-extrabold inline-flex items-center gap-1.5"
      >
        Back to dashboard
        <ChevronRight size={13} />
      </button>
    </article>
  );
}
