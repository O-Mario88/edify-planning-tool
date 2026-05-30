"use client";

import { useMemo, useState } from "react";
import {
  ExternalLink,
  Clipboard,
  CheckCircle2,
} from "lucide-react";
import { MobileShell } from "@/components/mobile/MobileShell";
import { MobileBottomNav } from "@/components/mobile/MobileBottomNav";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import {
  sfQueueCounts,
  sfQueueItems,
  type SfFilter,
  type SfStatus,
  type SfQueueItem,
} from "@/lib/mobile-mock";
import { cn } from "@/lib/utils";

// Tab labels are intentionally SHORT (single word where possible) so
// the four tiles all fit on one row at iPhone SE width (320px) without
// the labels wrapping to 2-3 uneven lines. The full status name still
// lives in the card status pill + the aria-label below.
const TABS: { key: SfStatus; label: string; ariaLabel: string; count: number; dot: string; valueTone: string }[] = [
  { key: "Awaiting SF ID", label: "Awaiting",  ariaLabel: "Awaiting SF ID",          count: sfQueueCounts.awaiting,  dot: "bg-rose-500",    valueTone: "text-rose-600"    },
  { key: "Submitted",      label: "Submitted", ariaLabel: "Submitted for Verification", count: sfQueueCounts.submitted, dot: "bg-amber-500",   valueTone: "text-amber-600"   },
  { key: "Returned",       label: "Returned",  ariaLabel: "Returned",                count: sfQueueCounts.returned,  dot: "bg-orange-500",  valueTone: "text-orange-600"  },
  { key: "Verified",       label: "Verified",  ariaLabel: "Verified",                count: sfQueueCounts.verified,  dot: "bg-emerald-500", valueTone: "text-emerald-600" },
];

const FILTERS: { key: SfFilter; label: string }[] = [
  { key: "all",       label: "All" },
  { key: "cluster",   label: "Cluster" },
  { key: "in_school", label: "In-School" },
  { key: "follow_up", label: "Follow-Up" },
];

const STATUS_PILL: Record<SfStatus, string> = {
  "Awaiting SF ID": "bg-rose-50 text-rose-700",
  Submitted:        "bg-amber-50 text-amber-700",
  Returned:         "bg-orange-50 text-orange-700",
  Verified:         "bg-emerald-50 text-emerald-700",
};

export function QueueView() {
  const [activeTab, setActiveTab] = useState<SfStatus>("Awaiting SF ID");
  const [filter, setFilter] = useState<SfFilter>("all");

  const visible = useMemo(() => {
    return sfQueueItems.filter((i) =>
      i.status === activeTab && (filter === "all" || i.filter === filter),
    );
  }, [activeTab, filter]);

  return (
    <MobileShell>
      <MobileTopBar backHref="/dashboard" />

      <main className="flex-1 px-3 py-3 space-y-3">
        {/* Status tab tiles.
            Premium pattern: the BIG count is the headline, a small colored
            status dot sits next to a 11px label. Selection is signalled
            by a 1.5px brand-tinted bottom rail + slightly elevated white
            card — no loud full-card tint, no ring, no thick border. The
            tile is always the same height; the label never wraps. */}
        <section
          role="tablist"
          aria-label="Salesforce queue status"
          className="grid grid-cols-4 gap-2"
        >
          {TABS.map((t) => {
            const active = activeTab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={active ? true : false}
                aria-controls="queue-items"
                aria-label={t.ariaLabel}
                tabIndex={active ? 0 : -1}
                onClick={() => setActiveTab(t.key)}
                className={cn(
                  "relative rounded-xl bg-white border p-2.5 text-center transition-all overflow-hidden",
                  active
                    ? "border-[var(--color-edify-primary)]/25 shadow-[0_2px_8px_-2px_rgba(15,23,32,0.08)]"
                    : "border-[var(--color-edify-border)] hover:border-[var(--color-edify-primary)]/15",
                )}
              >
                <div className={cn("text-[22px] font-extrabold tabular leading-none", active ? t.valueTone : "text-[var(--color-edify-text)]")}>
                  {t.count}
                </div>
                <div className="flex items-center justify-center gap-1 mt-1.5">
                  <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", t.dot)} />
                  <span className={cn(
                    "text-[10.5px] font-semibold leading-none whitespace-nowrap",
                    active ? "text-[var(--color-edify-text)]" : "muted",
                  )}>
                    {t.label}
                  </span>
                </div>
                {/* Bottom rail — premium selection signal */}
                {active && (
                  <span className="absolute bottom-0 left-2.5 right-2.5 h-[2px] rounded-full bg-[var(--color-edify-primary)]" />
                )}
                {active && <span className="sr-only"> (selected)</span>}
              </button>
            );
          })}
        </section>

        {/* Filter pills — the active pill uses the brand color (deep teal)
            not green, so the green stays meaningful as the "Verified /
            Confirm Match" action color. Subtle, premium. */}
        <div className="flex items-center gap-1.5 overflow-x-auto -mx-1 px-1 pb-0.5">
          {FILTERS.map((f) => {
            const active = filter === f.key;
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={cn(
                  "h-8 px-3.5 rounded-full text-[12px] font-semibold whitespace-nowrap shrink-0 transition-colors",
                  active
                    ? "bg-[var(--color-edify-primary)] text-white"
                    : "bg-white border border-[var(--color-edify-border)] text-[var(--color-edify-text)] hover:border-[var(--color-edify-primary)]/30",
                )}
              >
                {f.label}
              </button>
            );
          })}
          <span className="ml-auto text-[11.5px] muted shrink-0 pr-1 tabular">
            {visible.length} item{visible.length === 1 ? "" : "s"}
          </span>
        </div>

        {/* Queue items */}
        <div
          id="queue-items"
          role="tabpanel"
          aria-label={`Queue items — ${activeTab}`}
          className="space-y-2.5"
        >
          {visible.length === 0 ? (
            <div className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-6 text-center text-body muted">
              No items in this filter.
            </div>
          ) : (
            visible.map((item) => <QueueRow key={item.id} item={item} />)
          )}
        </div>
      </main>

      <MobileBottomNav role="ImpactAssessment" />
    </MobileShell>
  );
}

function QueueRow({ item }: { item: SfQueueItem }) {
  const [recordId, setRecordId] = useState(item.recordId ?? "");
  const [confirmed, setConfirmed] = useState(item.status === "Submitted" || item.status === "Verified");

  // Status accent — applied as a 3px left rail rather than a full
  // colored border. That keeps a list of (e.g.) eight "Awaiting"
  // cards from screaming red at the user while still giving each
  // row a clear status signal at a glance.
  const accentBar =
    item.status === "Awaiting SF ID" ? "bg-rose-500"    :
    item.status === "Submitted"      ? "bg-amber-500"   :
    item.status === "Returned"       ? "bg-orange-500"  :
                                        "bg-emerald-500";

  return (
    <section className="relative rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-[0_1px_2px_rgba(15,23,32,0.04)] overflow-hidden">
      {/* Left status rail. Premium replacement for the old loud 2px
          colored ring that wrapped the whole card. */}
      <span aria-hidden className={cn("absolute left-0 top-0 bottom-0 w-[3px]", accentBar)} />

      <header className="flex items-start justify-between gap-2 px-3.5 pt-3 pb-2">
        <div className="min-w-0">
          <div className="text-[14px] font-extrabold tracking-tight leading-tight truncate">
            {item.schoolName}
          </div>
          <div className="text-[11.5px] muted leading-tight mt-0.5">
            {item.contextLabel} · {item.weekLabel}
            {item.dateRange && <span> ({item.dateRange})</span>}
          </div>
        </div>
        {/* Status pill — kept but visually quieter than before. The
            redundancy with the active tab is intentional: when the
            user filters to "All", these pills remain meaningful. */}
        <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-bold whitespace-nowrap shrink-0", STATUS_PILL[item.status])}>
          {item.status}
        </span>
      </header>

      <div className="px-3.5 pb-3 space-y-2.5">
        <label className="block">
          <span className="text-[10.5px] font-semibold muted uppercase tracking-wide">Salesforce Record ID</span>
          <div className="relative mt-1">
            <Clipboard size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)]" />
            <input
              type="text"
              value={recordId}
              onChange={(e) => setRecordId(e.target.value)}
              placeholder="Paste ID here"
              className="w-full h-9 pl-8 pr-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12.5px] font-mono focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/25 focus:border-[var(--color-edify-primary)]/40"
            />
          </div>
        </label>

        {/* Action row. Secondary "Open Salesforce" is ghosted so the
            primary "Confirm Match" carries the visual weight — the
            two used to compete for attention. */}
        <div className="flex items-center gap-2">
          <a
            href="https://salesforce.com"
            target="_blank"
            rel="noreferrer"
            className="h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white inline-flex items-center justify-center gap-1.5 text-[12px] font-semibold text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/50 transition-colors shrink-0 whitespace-nowrap"
          >
            <ExternalLink size={12} />
            Open
          </a>
          <button
            type="button"
            disabled={recordId.trim().length === 0 || confirmed}
            onClick={() => setConfirmed(true)}
            className={cn(
              "flex-1 h-9 rounded-lg inline-flex items-center justify-center gap-1.5 text-[12.5px] font-bold transition-colors whitespace-nowrap",
              confirmed
                ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                : recordId.trim().length === 0
                  ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] cursor-not-allowed"
                  : "bg-emerald-600 hover:bg-emerald-500 text-white shadow-[0_1px_2px_rgba(15,23,32,0.06)]",
            )}
          >
            <CheckCircle2 size={13} />
            {confirmed ? "Confirmed" : "Confirm Match"}
          </button>
        </div>
      </div>
    </section>
  );
}
