"use client";

// My Plan — the five urgency lanes (premium redesign).
//
// Order: Waiting on Me · Rescheduled / Needs Attention · Due Today ·
// Planned This Week · Planned This Month. Each lane is a numbered card
// with a soft accent rail, a count chip, a one-line subtitle, and a
// collapse chevron. Every row is one premium action tile with exactly
// one primary button. Inline panels for Complete and Reschedule — no
// modals. Focus Mode collapses This Week + This Month so blockers +
// today fill the screen on field days.
//
// All write paths are unchanged: backend rows POST to /api/activities/:id/:action;
// store rows call the my-plan-actions server actions. Optimistic exit
// (slide out on success) + router.refresh() — the section re-renders
// without the completed row.

import { useState, useTransition, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  CalendarClock, CheckCircle2, Footprints, GraduationCap, Hash,
  Sun, CalendarDays, CalendarRange, Hourglass, RotateCcw, Upload, Wallet, X,
  ChevronDown, Sparkles, ArrowRight, AlertTriangle, Paperclip, type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { csrfHeaders } from "@/lib/csrf-client";
import { completeActivity, rescheduleActivity } from "@/lib/actions/my-plan-actions";
import { RESCHEDULE_SLIP_LIMIT, reschedulesRemaining } from "@/lib/planning/planning-capacity";
import { weekMonthLabel, type MyPlanItem, type MyPlanSection, type MyPlanSectionKey } from "@/lib/planning/my-plan-sections";

const RESCHEDULE_REASONS = [
  "School closed / public holiday",
  "Head teacher unavailable",
  "Weather / road impassable",
  "Staff / partner unable to travel",
  "Funds not yet received",
  "Conflicting cluster meeting",
  "Other",
];

// Lane order matches the snapshot strip + spec §10: blockers first, then
// rescheduled work, then today, then forward calendar (week → month → quarter).
const LANE_ORDER: MyPlanSectionKey[] = ["waitingOnMe", "needsAttention", "dueToday", "thisWeek", "thisMonth", "thisQuarter"];

type LaneMeta = {
  number: number;
  icon: LucideIcon;
  subtitle: string;
  accent: string;
  numberTone: string;
  countTone: string;
  anchor: string;
};

const LANE_META: Record<MyPlanSectionKey, LaneMeta> = {
  waitingOnMe: {
    number: 1, icon: Hourglass,
    subtitle: "Activities blocked until you act.",
    accent: "bg-emerald-400",
    numberTone: "bg-emerald-100 text-emerald-700",
    countTone: "bg-emerald-100 text-emerald-700",
    anchor: "lane-waiting",
  },
  needsAttention: {
    number: 2, icon: RotateCcw,
    subtitle: "Moved work and items close to slip limit.",
    accent: "bg-amber-400",
    numberTone: "bg-amber-100 text-amber-700",
    countTone: "bg-amber-100 text-amber-700",
    anchor: "lane-attention",
  },
  dueToday: {
    number: 3, icon: Sun,
    subtitle: "Scheduled work for today and overdue items.",
    accent: "bg-rose-400",
    numberTone: "bg-rose-100 text-rose-700",
    countTone: "bg-rose-100 text-rose-700",
    anchor: "lane-today",
  },
  thisWeek: {
    number: 4, icon: CalendarDays,
    subtitle: "Your remaining field work this week.",
    accent: "bg-sky-400",
    numberTone: "bg-sky-100 text-sky-700",
    countTone: "bg-sky-100 text-sky-700",
    anchor: "lane-week",
  },
  thisMonth: {
    number: 5, icon: CalendarRange,
    subtitle: "Open scheduled work later this month.",
    accent: "bg-slate-300",
    numberTone: "bg-slate-100 text-slate-600",
    countTone: "bg-slate-100 text-slate-600",
    anchor: "lane-month",
  },
  thisQuarter: {
    number: 6, icon: CalendarRange,
    subtitle: "Open scheduled work later this quarter.",
    accent: "bg-violet-300",
    numberTone: "bg-violet-100 text-violet-700",
    countTone: "bg-violet-100 text-violet-700",
    anchor: "lane-quarter",
  },
};

const FUNDING_TONE: Record<NonNullable<MyPlanItem["funding"]>, string> = {
  "Not Requested": "bg-slate-50 text-slate-500 border-slate-200 dark:bg-slate-800/40 dark:text-slate-400 dark:border-slate-700",
  Requested: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-900/50",
  Approved:  "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:border-sky-900/50",
  Disbursed: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:border-emerald-900/50",
  Accounted: "bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800/60 dark:text-slate-200 dark:border-slate-700",
  Returned:  "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:border-rose-900/50",
};

const ugx = (cents: number) => `UGX ${Math.round(cents / 100).toLocaleString()}`;

const isoDay = (d: Date) => d.toISOString().slice(0, 10);

function diffDays(todayIso: string, dateIso: string): number {
  const a = Date.UTC(+todayIso.slice(0, 4), +todayIso.slice(5, 7) - 1, +todayIso.slice(8, 10));
  const b = Date.UTC(+dateIso.slice(0, 4), +dateIso.slice(5, 7) - 1, +dateIso.slice(8, 10));
  return Math.max(0, Math.round((a - b) / 86400000));
}

// ── Toast ────────────────────────────────────────────────────────────

function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  useEffect(() => {
    const id = window.setTimeout(onClose, 3500);
    return () => window.clearTimeout(id);
  }, [onClose]);
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2 inline-flex items-center gap-2 rounded-xl border border-emerald-200 bg-white px-4 py-2.5 shadow-[0_18px_44px_-18px_rgba(15,23,32,0.4)] animate-in fade-in slide-in-from-bottom-2 duration-200 dark:bg-slate-900 dark:border-emerald-800/50"
    >
      <CheckCircle2 size={15} className="text-emerald-500 shrink-0" />
      <span className="text-[12.5px] font-semibold text-slate-800 dark:text-slate-100">{message}</span>
    </div>
  );
}

// ── Root ─────────────────────────────────────────────────────────────

export function MyPlanSections({ sections, live }: { sections: MyPlanSection[]; live: boolean }) {
  const total = sections.reduce((n, s) => n + s.items.length, 0);
  const [focus, setFocus] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  // Persist Focus Mode across reloads — it's a personal view preference.
  useEffect(() => {
    if (typeof window === "undefined") return;
    setFocus(window.localStorage.getItem("myPlanFocus") === "1");
  }, []);
  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("myPlanFocus", focus ? "1" : "0");
  }, [focus]);

  const ordered = useMemo(() => {
    const byKey = new Map(sections.map((s) => [s.key, s]));
    return LANE_ORDER.map((k) => byKey.get(k)).filter((s): s is MyPlanSection => !!s);
  }, [sections]);

  if (total === 0) return <EmptyAllCleared live={live} />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-[11.5px] muted">
          {total} scheduled {total === 1 ? "activity" : "activities"} still in play
          {live && (
            <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200 align-middle">
              Live · backend
            </span>
          )}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setFocus((f) => !f)}
            aria-pressed={focus}
            title="Show only blockers, attention, and today"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10.5px] font-bold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-edify-primary)]/40",
              focus
                ? "bg-[var(--color-edify-primary)] text-white border-transparent shadow-[0_4px_10px_-6px_rgba(15,23,32,0.4)]"
                : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50 dark:bg-slate-900 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800",
            )}
          >
            <Sparkles size={11} />
            Focus Mode{focus ? " · on" : ""}
          </button>
          <Link
            href="/completed-activities"
            className="inline-flex items-center gap-1 text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline"
          >
            View Completed Log <ArrowRight size={11} />
          </Link>
        </div>
      </div>

      {ordered.map((section) => {
        const meta = LANE_META[section.key];
        const collapsedByFocus = focus && (section.key === "thisWeek" || section.key === "thisMonth");
        return (
          <Lane
            key={section.key}
            section={section}
            meta={meta}
            startCollapsed={collapsedByFocus}
            focus={focus}
            onToast={setToast}
          />
        );
      })}

      {toast && <Toast message={toast} onClose={() => setToast(null)} />}
    </div>
  );
}

// ── Lane ─────────────────────────────────────────────────────────────

function Lane({
  section, meta, startCollapsed, focus, onToast,
}: {
  section: MyPlanSection;
  meta: LaneMeta;
  startCollapsed: boolean;
  focus: boolean;
  onToast: (m: string) => void;
}) {
  const [open, setOpen] = useState(!startCollapsed);
  useEffect(() => { setOpen(!startCollapsed); }, [startCollapsed]);
  const Icon = meta.icon;
  const empty = section.items.length === 0;

  return (
    <section
      id={meta.anchor}
      aria-label={section.title}
      className="relative scroll-mt-4 rounded-2xl border border-slate-200/70 bg-white transition-shadow dark:border-slate-800 dark:bg-slate-900/30"
    >
      <span aria-hidden className={`absolute left-0 top-0 h-full w-1 rounded-l-2xl ${meta.accent}`} />
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={`${meta.anchor}-body`}
        className="w-full flex items-center gap-3 px-4 pl-5 py-3 text-left rounded-2xl focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-edify-primary)]/40"
      >
        <span
          className={cn(
            "grid h-7 w-7 shrink-0 place-items-center rounded-full text-[12px] font-extrabold tabular",
            meta.numberTone,
          )}
        >
          {meta.number}
        </span>
        <Icon size={14} className="text-slate-400 shrink-0" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="text-[13px] font-extrabold text-slate-800 dark:text-slate-100">{section.title}</h2>
            <span
              className={cn(
                "inline-flex items-center justify-center rounded-full px-1.5 py-px text-[10px] font-bold tabular",
                meta.countTone,
              )}
            >
              {section.items.length}
            </span>
          </div>
          {!empty && (
            <p className="text-[11px] text-slate-500 truncate">{meta.subtitle}</p>
          )}
        </div>
        <ChevronDown
          size={15}
          className={cn(
            "text-slate-400 transition-transform duration-200",
            open ? "rotate-180" : "rotate-0",
          )}
          aria-hidden
        />
      </button>

      {open && (
        <div id={`${meta.anchor}-body`} className="px-3 sm:px-4 pb-3 animate-in fade-in duration-200">
          {empty ? (
            <LaneEmptyState sectionKey={section.key} />
          ) : (
            <div className="space-y-2">
              {section.items.map((item) => (
                <ActivityRow
                  key={item.id}
                  item={item}
                  sectionKey={section.key}
                  focus={focus}
                  onToast={onToast}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

// ── Empty states ─────────────────────────────────────────────────────

const EMPTY_COPY: Record<MyPlanSectionKey, { headline: string; sub: string }> = {
  waitingOnMe:    { headline: "Nothing is waiting on you.",       sub: "No Salesforce IDs, evidence, or returned items pending." },
  needsAttention: { headline: "No rescheduled work.",              sub: "Nothing is close to slip limit." },
  dueToday:       { headline: "No activities due today.",          sub: "You can breathe." },
  thisWeek:       { headline: "No more scheduled work this week.", sub: "Tomorrow's calendar is open." },
  thisMonth:      { headline: "Nothing further planned this month.", sub: "Open Planning to schedule the next slot." },
  thisQuarter:    { headline: "Nothing planned later this quarter.", sub: "Work beyond this month lands here as you schedule it." },
};

function LaneEmptyState({ sectionKey }: { sectionKey: MyPlanSectionKey }) {
  const copy = EMPTY_COPY[sectionKey];
  return (
    <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/50 px-4 py-5 text-center dark:bg-slate-900/40 dark:border-slate-800">
      <p className="text-[12.5px] font-semibold text-slate-700 dark:text-slate-200">{copy.headline}</p>
      <p className="mt-0.5 text-[11.5px] text-slate-500">{copy.sub}</p>
    </div>
  );
}

function EmptyAllCleared({ live }: { live: boolean }) {
  return (
    <div className="rounded-3xl border border-slate-200 bg-gradient-to-br from-emerald-50/70 to-white px-6 py-12 text-center dark:from-emerald-900/20 dark:to-slate-900/40 dark:border-slate-800">
      <div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-emerald-100 text-emerald-600 dark:bg-emerald-900/40 dark:text-emerald-300">
        <CheckCircle2 size={22} />
      </div>
      <h3 className="mt-3 text-[17px] font-extrabold text-slate-800 dark:text-slate-100">Your plan is clear.</h3>
      <p className="mt-1 text-[12.5px] text-slate-500 max-w-sm mx-auto">
        Scheduled activities will appear here after planning. Completed work is safely stored in Completed Activities.
      </p>
      <div className="mt-4 flex items-center justify-center gap-2 flex-wrap">
        <Link
          href="/planning"
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--color-edify-primary)] text-white px-3 py-1.5 text-[11.5px] font-extrabold hover:bg-[var(--color-edify-dark)] no-underline"
        >
          Go to Planning <ArrowRight size={12} />
        </Link>
        <Link
          href="/completed-activities"
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 text-slate-700 px-3 py-1.5 text-[11.5px] font-extrabold hover:bg-slate-50 no-underline dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          View Completed Activities
        </Link>
      </div>
      {live && (
        <p className="mt-3 inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200">
          Live · backend
        </p>
      )}
    </div>
  );
}

// ── Activity row ─────────────────────────────────────────────────────

function ActivityRow({
  item, sectionKey, focus, onToast,
}: {
  item: MyPlanItem;
  sectionKey: MyPlanSectionKey;
  focus: boolean;
  onToast: (m: string) => void;
}) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [mode, setMode] = useState<null | "complete" | "reschedule">(null);
  const [field, setField] = useState("");
  const [reason, setReason] = useState(RESCHEDULE_REASONS[0]);
  const [error, setError] = useState<string | null>(null);
  const [exiting, setExiting] = useState(false);

  const Icon = /training|meeting/i.test(item.typeLabel) ? GraduationCap : Footprints;

  const todayIso = isoDay(new Date());
  const itemIso = item.dateIso?.slice(0, 10);
  const overdue = !!itemIso && itemIso < todayIso;

  const dateLabel = item.exactDate
    ? item.dateIso
      ? new Date(item.dateIso).toLocaleDateString("en-UG", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })
      : "Date TBD"
    : (weekMonthLabel(item) ?? "Not yet dated");

  // Warm status line. Returns null when there's nothing useful to add —
  // we don't fill silence with noise.
  const statusLine: string | null = item.waitingOn === "salesforceId"
    ? "Waiting for Salesforce ID"
    : item.waitingOn === "evidence"
      ? "Evidence required"
      : item.waitingOn === "returned"
        ? `Returned${item.lastReason ? ` — ${item.lastReason}` : ""}`
        : sectionKey === "needsAttention" && item.lastReason
          ? `Last reason: ${item.lastReason}`
          : sectionKey === "dueToday" && overdue && itemIso
            ? (() => {
                const d = diffDays(todayIso, itemIso);
                return `Needs your attention — ${d === 0 ? "due today" : `${d} day${d === 1 ? "" : "s"} overdue`}`;
              })()
            : null;

  async function run(
    fn: () => Promise<{ ok: boolean; reason?: string; message?: string } | Response>,
    successMsg: string,
  ) {
    setError(null);
    start(async () => {
      try {
        const r = await fn();
        if (r instanceof Response) {
          const j = await r.json();
          if (!j.live) { setError(j.error || "The action was rejected"); return; }
        } else if (!r.ok) {
          setError(
            r.message ||
              (r.reason === "SLIP_LIMIT"
                ? `Slip limit (${RESCHEDULE_SLIP_LIMIT}) reached — escalate or deliver.`
                : "The action was rejected"),
          );
          return;
        }
        setMode(null);
        setField("");
        onToast(successMsg);
        // Optimistic exit: slide the row out before the refresh lands.
        setExiting(true);
        window.setTimeout(() => router.refresh(), 220);
      } catch {
        setError("Could not reach the server");
      }
    });
  }

  const COMPLETION_UNLOCKED = new Set([
    "completion_started", "in_progress", "evidence_uploaded", "evidence_accepted", "salesforce_id_required",
  ]);

  const doComplete = () => {
    setError(null);
    start(async () => {
      try {
        if (item.source === "backend" && item.backendStatus && !COMPLETION_UNLOCKED.has(item.backendStatus)) {
          const start = await fetch(`/api/activities/${item.id}/start-completion`, {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json", ...csrfHeaders() },
            body: "{}",
          });
          const sj = await start.json();
          if (!start.ok || !sj.live) {
            setError(sj.error || "Could not start completion");
            return;
          }
          setMode("complete");
          onToast("Upload evidence, then enter your Activity Code and submit.");
          router.refresh();
          return;
        }
        const r = item.source === "backend"
          ? await fetch(`/api/activities/${item.id}/complete`, {
              method: "POST",
              credentials: "include",
              headers: { "Content-Type": "application/json", ...csrfHeaders() },
              body: JSON.stringify({ salesforceId: field.trim() }),
            })
          : await completeActivity(item.id, field.trim() || undefined);
        if (r instanceof Response) {
          const j = await r.json();
          if (!r.ok || !j.live) { setError(j.error || "The action was rejected"); return; }
        } else if (!r.ok) {
          setError(r.message || "The action was rejected");
          return;
        }
        setMode(null);
        setField("");
        onToast("Submitted for review.");
        setExiting(true);
        window.setTimeout(() => router.refresh(), 220);
      } catch {
        setError("Could not reach the server");
      }
    });
  };

  const doReschedule = () => {
    const remainingAfter = reschedulesRemaining((item.rescheduleCount ?? 0) + 1);
    return run(
      () =>
        item.source === "backend"
          ? fetch(`/api/activities/${item.id}/reschedule`, {
              method: "POST",
              credentials: "include",
              headers: { "Content-Type": "application/json", ...csrfHeaders() },
              body: JSON.stringify({ scheduledDate: field, reason }),
            })
          : rescheduleActivity(item.id, field, reason),
      `New date saved. ${remainingAfter} move${remainingAfter === 1 ? "" : "s"} left.`,
    );
  };

  return (
    <div
      className={cn(
        "group rounded-xl border border-slate-200 bg-white transition-all dark:border-slate-800 dark:bg-slate-900/40",
        "hover:border-slate-300 hover:shadow-[0_8px_22px_-14px_rgba(15,23,32,0.35)]",
        exiting && "opacity-0 -translate-y-1 scale-[0.99]",
      )}
      style={{ transitionDuration: "220ms" }}
    >
      <div className="flex items-center gap-3 px-3 sm:px-3.5 py-2.5">
        <span className="grid place-items-center h-9 w-9 rounded-lg bg-[var(--color-edify-soft)]/70 text-[var(--color-edify-primary)] shrink-0">
          <Icon size={15} aria-hidden />
        </span>

        <div className="min-w-0 flex-1 grid grid-cols-1 sm:grid-cols-[140px_minmax(0,1fr)_auto] gap-y-1 sm:gap-x-3 items-center">
          <div className="text-[12px] font-bold text-slate-700 dark:text-slate-200 truncate">
            {item.typeLabel}
          </div>

          <div className="min-w-0">
            <div className="text-[13px] font-extrabold text-slate-900 dark:text-slate-50 truncate">
              {item.entityName}
            </div>
            <div className="mt-0.5 text-[11px] text-slate-500 inline-flex items-center gap-3 flex-wrap">
              <span
                className={cn(
                  "inline-flex items-center gap-1 tabular",
                  overdue && "text-rose-700 font-bold dark:text-rose-300",
                )}
              >
                <CalendarClock size={10} aria-hidden />
                {overdue ? `Overdue · ${dateLabel}` : dateLabel}
              </span>
              {item.costCents != null && (
                <span className="inline-flex items-center gap-1 tabular">
                  <Wallet size={10} aria-hidden /> {ugx(item.costCents)}
                </span>
              )}
              {item.rescheduleCount > 0 && (
                <span
                  className={cn(
                    "inline-flex items-center gap-1 font-bold",
                    item.atSlipLimit ? "text-rose-700 dark:text-rose-300" : "text-amber-700 dark:text-amber-300",
                  )}
                >
                  <RotateCcw size={10} aria-hidden />
                  {item.rescheduleCount} {item.rescheduleCount === 1 ? "move" : "moves"}
                  {item.atSlipLimit ? " · slip limit" : ""}
                </span>
              )}
            </div>
          </div>

          <div className="flex items-center justify-start sm:justify-end gap-2 shrink-0 flex-wrap">
            {item.funding && (
              <span
                className={cn(
                  "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-extrabold uppercase tracking-wide",
                  FUNDING_TONE[item.funding],
                )}
              >
                {item.funding}
              </span>
            )}
            <Link
              href={`/activities/${item.id}/evidence`}
              title="Upload / preview evidence"
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 text-slate-600 px-2 py-1.5 text-[11px] font-bold hover:bg-slate-50 no-underline dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <Paperclip size={12} aria-hidden /> Evidence
            </Link>
            <NextActionButton
              item={item}
              pending={pending}
              mode={mode}
              setMode={(m) => { setMode(m); setField(""); setError(null); }}
              focus={focus}
            />
          </div>
        </div>
      </div>

      {statusLine && !mode && (
        <div className="px-3 sm:px-3.5 pb-2 pl-[60px] sm:pl-[60px]">
          <p
            className={cn(
              "text-[11px] truncate",
              item.waitingOn ? "text-slate-600 dark:text-slate-300" : "text-slate-500",
              overdue && "text-rose-700 dark:text-rose-300 font-semibold",
            )}
          >
            {statusLine}
          </p>
        </div>
      )}

      {mode === "complete" && (
        <InlinePanel
          title={item.nextAction === "enterSalesforceId" ? "Enter Salesforce ID" : "Confirm this activity"}
          subtitle={
            item.nextAction === "enterSalesforceId"
              ? "Paste the ID from Salesforce. Sent to IA on save."
              : "Provide Salesforce ID to complete."
          }
        >
          <div className="flex items-center gap-2 flex-wrap">
            <Hash size={12} className="text-slate-400 shrink-0" aria-hidden />
            <input
              autoFocus
              value={field}
              onChange={(e) => setField(e.target.value)}
              placeholder={item.exactDate ? "TS-…" : "SV-…"}
              aria-label="Salesforce ID"
              className="flex-1 min-w-[180px] rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[12px] focus:border-[var(--color-edify-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/20 dark:bg-slate-900 dark:border-slate-700 dark:text-slate-100"
            />
            <ConfirmBtn
              label={item.nextAction === "enterSalesforceId" ? "Save & send to IA" : "Confirm & Complete"}
              disabled={pending || (item.nextAction === "enterSalesforceId" && !field.trim())}
              onClick={doComplete}
              pending={pending}
            />
            <CloseBtn onClick={() => { setMode(null); setField(""); }} />
          </div>
        </InlinePanel>
      )}

      {mode === "reschedule" && (
        <InlinePanel
          title="Choose a new date"
          subtitle={`You have ${reschedulesRemaining(item.rescheduleCount)} move${reschedulesRemaining(item.rescheduleCount) === 1 ? "" : "s"} left before slip limit.`}
        >
          <div className="flex items-end gap-2 flex-wrap">
            <label className="flex flex-col">
              <span className="text-[10px] font-bold uppercase tracking-wide text-slate-500 mb-1">New date</span>
              <input
                type="date"
                value={field}
                onChange={(e) => setField(e.target.value)}
                aria-label="New scheduled date"
                className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[12px] focus:border-[var(--color-edify-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/20 dark:bg-slate-900 dark:border-slate-700 dark:text-slate-100"
              />
            </label>
            <label className="flex flex-col">
              <span className="text-[10px] font-bold uppercase tracking-wide text-slate-500 mb-1">Reason</span>
              <select
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                aria-label="Reschedule reason"
                className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[12px] max-w-[240px] focus:border-[var(--color-edify-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/20 dark:bg-slate-900 dark:border-slate-700 dark:text-slate-100"
              >
                {RESCHEDULE_REASONS.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </label>
            <span className="inline-flex items-center rounded-full bg-sky-50 text-sky-700 px-2 py-0.5 text-[10px] font-bold border border-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:border-sky-900/50">
              {reschedulesRemaining(item.rescheduleCount)} move{reschedulesRemaining(item.rescheduleCount) === 1 ? "" : "s"} left
            </span>
            <ConfirmBtn
              label="Save new date"
              disabled={pending || !field}
              onClick={doReschedule}
              pending={pending}
            />
            <CloseBtn onClick={() => { setMode(null); setField(""); }} />
          </div>
        </InlinePanel>
      )}

      {error && (
        <div className="mx-3 mb-2 inline-flex items-start gap-1.5 rounded-md border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-[11px] font-semibold text-rose-700 dark:bg-rose-950/30 dark:border-rose-900/50 dark:text-rose-200">
          <AlertTriangle size={12} className="mt-px shrink-0" />
          {error}
        </div>
      )}
    </div>
  );
}

// ── Next-action button (one per row) ─────────────────────────────────

function NextActionButton({
  item, pending, mode, setMode, focus,
}: {
  item: MyPlanItem;
  pending: boolean;
  mode: null | "complete" | "reschedule";
  setMode: (m: null | "complete" | "reschedule") => void;
  focus: boolean;
}) {
  // Focus Mode bumps the primary button slightly larger for field-day legibility.
  const sizing = focus ? "h-9 px-3 text-[12px]" : "h-8 px-2.5 text-[11px]";
  const base = `inline-flex items-center gap-1.5 ${sizing} rounded-lg font-extrabold transition-all disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-edify-primary)]/40`;
  const primary = cn(
    base,
    "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white shadow-[0_4px_12px_-6px_rgba(15,23,32,0.4)] no-underline active:scale-[0.97]",
  );
  const outline = cn(
    base,
    "border border-slate-200 text-slate-700 hover:bg-slate-50 active:scale-[0.97] dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800",
  );

  const spinner = pending ? (
    <span className="h-3 w-3 rounded-full border-2 border-current border-t-transparent animate-spin" aria-hidden />
  ) : null;

  switch (item.nextAction) {
    case "enterSalesforceId":
      return (
        <button
          type="button"
          disabled={pending}
          onClick={() => setMode(mode === "complete" ? null : "complete")}
          className={primary}
        >
          {spinner ?? <Hash size={12} />} Enter Salesforce ID
        </button>
      );
    case "uploadEvidence":
      return (
        <Link href="/completed-activities" className={primary}>
          <Upload size={12} /> Upload Evidence
        </Link>
      );
    case "complete":
      return (
        <button
          type="button"
          disabled={pending}
          onClick={() => setMode(mode === "complete" ? null : "complete")}
          className={primary}
        >
          {spinner ?? <CheckCircle2 size={12} />}
          {item.waitingOn === "returned" ? "Fix & Complete" : "Complete"}
        </button>
      );
    case "reschedule":
      return (
        <button
          type="button"
          disabled={pending || item.atSlipLimit}
          title={item.atSlipLimit ? `Slip limit (${RESCHEDULE_SLIP_LIMIT}) reached` : undefined}
          onClick={() => setMode(mode === "reschedule" ? null : "reschedule")}
          className={outline}
        >
          {spinner ?? <CalendarClock size={12} />} Reschedule
        </button>
      );
  }
}

// ── Inline panel primitives ──────────────────────────────────────────

function InlinePanel({
  title, subtitle, children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      role="group"
      aria-label={title}
      className="mx-3 mb-3 rounded-xl border border-emerald-200/70 bg-emerald-50/40 px-3 py-2.5 animate-in fade-in slide-in-from-top-1 duration-200 dark:bg-emerald-950/20 dark:border-emerald-900/40"
    >
      <div className="mb-2 flex items-center gap-2">
        <span className="grid h-5 w-5 place-items-center rounded-full bg-emerald-500 text-white shrink-0">
          <CheckCircle2 size={11} />
        </span>
        <div className="min-w-0">
          <div className="text-[12px] font-extrabold text-slate-800 dark:text-slate-100">{title}</div>
          {subtitle && <div className="text-[10.5px] text-slate-500 dark:text-slate-400">{subtitle}</div>}
        </div>
      </div>
      {children}
    </div>
  );
}

function ConfirmBtn({
  label, onClick, disabled, pending,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  pending?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-1.5 rounded-md bg-[var(--color-edify-primary)] text-white px-3 py-1.5 text-[11.5px] font-extrabold transition-all hover:bg-[var(--color-edify-dark)] active:scale-[0.97] disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-edify-primary)]/40"
    >
      {pending && (
        <span
          className="h-3 w-3 rounded-full border-2 border-white border-t-transparent animate-spin"
          aria-hidden
        />
      )}
      {label}
    </button>
  );
}

function CloseBtn({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Close panel"
      className="h-7 w-7 grid place-items-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800"
    >
      <X size={12} />
    </button>
  );
}

