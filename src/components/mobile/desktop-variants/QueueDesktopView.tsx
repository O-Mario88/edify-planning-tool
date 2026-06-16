"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  ExternalLink,
  Clipboard,
  CheckCircle2,
  ChevronRight,
  Building2,
  GraduationCap,
  Footprints,
  type LucideIcon,
} from "lucide-react";
import {
  sfQueueItems,
  sfQueueCounts,
  type SfStatus,
  type SfFilter,
  type SfQueueItem,
} from "@/lib/mobile-mock";
import { PageHeader } from "@/components/ui/PageHeader";
import { cn } from "@/lib/utils";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

const STATUS_TABS: SfStatus[] = ["Awaiting SF ID", "Submitted", "Returned", "Verified"];

const STATUS_TONE: Record<SfStatus, string> = {
  "Awaiting SF ID": "bg-amber-100   text-amber-700",
  "Submitted":      "bg-sky-100     text-sky-700",
  "Returned":       "bg-rose-100    text-rose-700",
  "Verified":       "bg-emerald-100 text-emerald-700",
};

const FILTERS: { key: SfFilter; label: string }[] = [
  { key: "all",        label: "All" },
  { key: "cluster",    label: "Cluster" },
  { key: "in_school",  label: "In-School" },
  { key: "follow_up",  label: "Follow-Up" },
];

const CTX_ICON: Record<string, LucideIcon> = {
  "School Visit":         Building2,
  "Cluster Meeting":      GraduationCap,
  "Cluster Training":     GraduationCap,
  "Partner Follow-Up Visit": Footprints,
  "Follow-Up Visit":      Footprints,
};

export function QueueDesktopView() {
  const [activeTab, setActiveTab] = useState<SfStatus>("Awaiting SF ID");
  const [filter, setFilter] = useState<SfFilter>("all");

  const visible = useMemo(() => {
    return sfQueueItems.filter((i) => {
      if (i.status !== activeTab) return false;
      if (filter !== "all" && i.filter !== filter) return false;
      return true;
    });
  }, [activeTab, filter]);

  // The Salesforce/ID queue is mock-backed (mobile-mock); never show fabricated
  // queue rows in production — withhold until wired to the live verification queue.
  if (!isMockAllowed()) return <InsufficientData surface="the Salesforce ID queue" />;

  return (
    <>
      <PageHeader
        title="Salesforce Verification Queue"
        subtitle="Submit Salesforce IDs for verified activities and track which records are still awaiting confirmation."
      />
      <div className="mx-auto w-full max-w-5xl px-4 sm:px-5 md:px-6 pb-10 md:pb-6">
        <div className="grid grid-cols-12 gap-4 items-start">
          <div className="col-span-12 lg:col-span-8">
            {/* Status tabs */}
      <div className="card rounded-2xl p-2 flex items-center gap-1 flex-wrap mb-3">
        {STATUS_TABS.map((s) => {
          const active = s === activeTab;
          return (
            <button
              key={s}
              type="button"
              onClick={() => setActiveTab(s)}
              className={cn(
                "h-9 px-3 rounded-lg text-[12px] font-extrabold tracking-tight whitespace-nowrap",
                active
                  ? "bg-[var(--color-edify-primary)] text-white"
                  : "text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/40",
              )}
            >
              {s}
            </button>
          );
        })}
      </div>

      {/* Filter chips */}
      <div className="card rounded-2xl p-3 flex items-center gap-1.5 flex-wrap mb-3">
        {FILTERS.map((f) => {
          const active = f.key === filter;
          return (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={cn(
                "h-9 px-3 rounded-full text-[12px] font-extrabold tracking-tight border whitespace-nowrap",
                active
                  ? "bg-[var(--color-edify-deep)] text-white border-[var(--color-edify-deep)]"
                  : "bg-white text-[var(--color-edify-text)] border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/40",
              )}
            >
              {f.label}
            </button>
          );
        })}
      </div>

      {/* Queue list */}
      <ul className="space-y-2">
        {visible.length === 0 ? (
          <li className="card rounded-2xl p-8 text-center">
            <div className="text-body-lg font-extrabold tracking-tight">Nothing here</div>
            <p className="text-[11.5px] muted mt-1">Try a different status tab or filter.</p>
          </li>
        ) : (
          visible.map((i) => <QueueRow key={i.id} item={i} />)
        )}
            </ul>
          </div>
          <aside className="col-span-12 lg:col-span-4 lg:sticky lg:top-4 space-y-3">
            <div className="card p-3.5">
              <h3 className="text-body font-extrabold tracking-tight uppercase muted mb-2">By status</h3>
              <ul className="space-y-1.5 text-[12px]">
                <Row label="Awaiting SF ID" count={sfQueueCounts.awaiting}  tone="amber" />
                <Row label="Submitted"      count={sfQueueCounts.submitted} tone="sky" />
                <Row label="Returned"       count={sfQueueCounts.returned}  tone="rose" />
                <Row label="Verified"       count={sfQueueCounts.verified}  tone="green" />
              </ul>
            </div>
            <Link href="/dashboards/impact" className="card p-3.5 flex items-center gap-2 hover:bg-[var(--color-edify-soft)]/40">
              <ExternalLink size={14} className="text-[var(--color-edify-primary)]" />
              <span className="text-body font-extrabold tracking-tight">Open Impact dashboard</span>
              <ChevronRight size={12} className="ml-auto text-[var(--color-edify-muted)]" />
            </Link>
          </aside>
        </div>
      </div>
    </>
  );
}

function QueueRow({ item }: { item: SfQueueItem }) {
  const Icon = CTX_ICON[item.contextLabel] ?? Building2;
  return (
    <li className="card rounded-2xl p-3 flex items-start gap-3">
      <span className="h-10 w-10 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
        <Icon size={16} />
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-[13px] font-extrabold tracking-tight">{item.schoolName}</div>
        <div className="text-caption muted">
          {item.contextLabel} · {item.weekLabel} · {item.dateRange}
        </div>
        {item.recordId && (
          <div className="text-caption mt-0.5">
            <span className="font-mono text-[10px] muted">{item.recordId}</span>
          </div>
        )}
      </div>
      <span className={cn(
        "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap shrink-0",
        STATUS_TONE[item.status],
      )}>
        {item.status}
      </span>
      {item.status === "Awaiting SF ID" && (
        <button
          type="button"
          className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] text-white text-[11.5px] font-semibold inline-flex items-center gap-1 shrink-0"
        >
          <Clipboard size={11} />
          Submit ID
        </button>
      )}
      {item.status === "Verified" && (
        <CheckCircle2 size={16} className="text-emerald-600 shrink-0 mt-1" />
      )}
    </li>
  );
}

function Row({ label, count, tone }: { label: string; count: number; tone: "amber" | "sky" | "rose" | "green" }) {
  const TONE = {
    amber: "text-amber-700",
    sky:   "text-sky-700",
    rose:  "text-rose-700",
    green: "text-emerald-700",
  } as const;
  return (
    <li className="flex items-baseline justify-between">
      <span className="muted">{label}</span>
      <span className={cn("font-extrabold tabular", TONE[tone])}>{count}</span>
    </li>
  );
}
