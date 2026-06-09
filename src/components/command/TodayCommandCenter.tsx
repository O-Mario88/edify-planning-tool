"use client";

// The recommendation-led home screen. The app brings the work to the user:
// a role-scoped, priority-ranked feed of "what must I do next", each item with
// ONE primary action and a plain-language reason. Backend-driven
// (/api/command-center/today) — real state, no mock, no hunting for buttons.

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, ChevronRight, ListChecks } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { cn } from "@/lib/utils";
import type { BeTodayFeed, BeActionItem } from "@/lib/api/surfaces";

type Data = Omit<BeTodayFeed, "live">;

const TONE: Record<string, { dot: string; chip: string; border: string }> = {
  critical: { dot: "bg-rose-500", chip: "bg-rose-50 text-rose-700 border-rose-200", border: "border-l-rose-400" },
  high: { dot: "bg-amber-500", chip: "bg-amber-50 text-amber-700 border-amber-200", border: "border-l-amber-400" },
  medium: { dot: "bg-sky-500", chip: "bg-sky-50 text-sky-700 border-sky-200", border: "border-l-sky-300" },
};

export function TodayCommandCenter() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true); setError(null);
    fetch("/api/command-center/today", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setData(j as Data); else setError(j.error || "Could not load your tasks"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[14px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><ListChecks size={15} /> What you must do next</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · recommended for you</span>
      </header>

      {loading ? (
        <LoadingState compact />
      ) : error ? (
        <ErrorState compact message={error} onRetry={load} />
      ) : !data || data.summary.total === 0 ? (
        <EmptyState compact title="You're all caught up" message="No red alerts or pending actions in your scope right now. The system will surface the next task here as soon as one appears." />
      ) : (
        <>
          {/* Three-question summary */}
          <div className="grid grid-cols-3 gap-2 mb-3">
            <Stat label="Red alerts" value={data.summary.critical} tone="critical" />
            <Stat label="To do next" value={data.summary.action} tone="high" />
            <Stat label="Watch" value={data.summary.attention} tone="medium" />
          </div>

          <div className="space-y-3">
            {data.groups.map((g) => (
              <Group key={g.key} label={g.label} items={g.items} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  const t = TONE[tone];
  return (
    <div className="rounded-lg border border-[var(--color-edify-border)] p-2 flex items-center gap-2">
      <span className={cn("w-2.5 h-2.5 rounded-full shrink-0", t.dot)} />
      <div className="min-w-0">
        <div className="text-[18px] font-extrabold tabular leading-none">{value}</div>
        <div className="text-[9.5px] muted uppercase tracking-wide truncate">{label}</div>
      </div>
    </div>
  );
}

function Group({ label, items }: { label: string; items: BeActionItem[] }) {
  // Rollups (count set) lead; concrete examples collapse under them.
  const rollups = items.filter((i) => i.count != null);
  const examples = items.filter((i) => i.count == null);
  return (
    <div>
      <div className="text-[10px] font-bold uppercase tracking-wide muted mb-1.5">{label}</div>
      <ul className="space-y-1.5">
        {rollups.map((i) => <Row key={i.id} item={i} examples={examples.filter((e) => e.kind === i.kind)} />)}
        {/* examples whose rollup isn't present (shouldn't happen, but safe) */}
        {examples.filter((e) => !rollups.some((r) => r.kind === e.kind)).map((i) => <Row key={i.id} item={i} examples={[]} />)}
      </ul>
    </div>
  );
}

function Row({ item, examples }: { item: BeActionItem; examples: BeActionItem[] }) {
  const [open, setOpen] = useState(false);
  const t = TONE[item.priority] ?? TONE.medium;
  return (
    <li className={cn("rounded-lg border border-[var(--color-edify-border)] border-l-[3px] overflow-hidden", t.border)}>
      <div className="flex items-center gap-2 p-2.5">
        {item.priority === "critical" ? <AlertTriangle size={14} className="text-rose-500 shrink-0" /> : <span className={cn("w-2 h-2 rounded-full shrink-0", t.dot)} />}
        <div className="min-w-0 flex-1">
          <div className="text-[12.5px] font-bold leading-tight truncate">{item.title}</div>
          <div className="text-[11px] muted leading-snug">{item.reason}</div>
        </div>
        <Link href={item.action.href} className="inline-flex items-center gap-1 h-8 px-2.5 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[11.5px] font-bold whitespace-nowrap shrink-0">
          {item.action.label} <ArrowRight size={12} />
        </Link>
      </div>
      {examples.length > 0 && (
        <div className="border-t border-[var(--color-edify-divider)]">
          <button onClick={() => setOpen((v) => !v)} className="w-full flex items-center gap-1 px-2.5 py-1 text-[10.5px] font-semibold muted hover:bg-[var(--surface-3)]">
            {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />} {open ? "Hide" : "Show"} {examples.length} example{examples.length === 1 ? "" : "s"}
          </button>
          {open && (
            <ul className="px-2.5 pb-2 space-y-1">
              {examples.map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-2 text-[11px]">
                  <span className="truncate"><CheckCircle2 size={10} className="inline mr-1 text-slate-300" />{e.subject?.name ?? e.title}</span>
                  <Link href={e.action.href} className="text-[10.5px] font-bold text-[var(--color-edify-primary)] whitespace-nowrap shrink-0">{e.action.label} →</Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}
