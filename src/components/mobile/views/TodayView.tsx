"use client";

import Link from "next/link";
import {
  GraduationCap,
  Building2,
  Footprints,
  Handshake,
  ShieldCheck,
  Users,
  Sun,
  Sunrise,
  Moon,
  ChevronRight,
  Clock,
  CheckCircle2,
  AlertOctagon,
  CircleDashed,
  CheckSquare,
  type LucideIcon,
} from "lucide-react";
import { MobileShell } from "@/components/mobile/MobileShell";
import { MobileBottomNav } from "@/components/mobile/MobileBottomNav";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import {
  todayHeader,
  todaysTasks,
  todaysTaskCounts,
  todayQuickActions,
  type TodaysTask,
  type TodaysTaskBlock,
} from "@/lib/mobile-mock";
import { cn } from "@/lib/utils";

const KIND_ICON: Record<TodaysTask["kind"], LucideIcon> = {
  "Cluster Training":  GraduationCap,
  "Cluster Meeting":   Users,
  "School Visit":      Building2,
  "Follow-Up Visit":   Footprints,
  "Partner Meeting":   Handshake,
  "SSA Verification":  ShieldCheck,
};

const KIND_TONE: Record<TodaysTask["kind"], string> = {
  "Cluster Training":  "bg-emerald-100 text-emerald-700",
  "Cluster Meeting":   "bg-violet-100  text-violet-700",
  "School Visit":      "bg-sky-100     text-sky-700",
  "Follow-Up Visit":   "bg-orange-100  text-orange-700",
  "Partner Meeting":   "bg-blue-100    text-blue-700",
  "SSA Verification":  "bg-amber-100   text-amber-700",
};

const STATUS_TONE: Record<TodaysTask["status"], string> = {
  "Planned":     "bg-slate-100   text-slate-700",
  "In Progress": "bg-amber-100   text-amber-700",
  "Completed":   "bg-emerald-100 text-emerald-700",
  "Overdue":     "bg-rose-100    text-rose-700",
};

const STATUS_ICON: Record<TodaysTask["status"], LucideIcon> = {
  "Planned":     CircleDashed,
  "In Progress": Clock,
  "Completed":   CheckCircle2,
  "Overdue":     AlertOctagon,
};

const BLOCK_ORDER: TodaysTaskBlock[] = ["Morning", "Afternoon", "Evening"];

const BLOCK_ICON: Record<TodaysTaskBlock, LucideIcon> = {
  Morning:   Sunrise,
  Afternoon: Sun,
  Evening:   Moon,
};

const QA_ICON = {
  logVisit: CheckSquare,
  route:    Footprints,
};

export function TodayView() {
  return (
    <MobileShell>
      <MobileTopBar title="Today's Tasks" backHref="/more" monthLabel={todayHeader.shortDate} />
      <p className="px-4 pt-2 pb-1 text-[11.5px] muted">
        {todayHeader.dateLabel} · {todayHeader.weekLabel}
      </p>

      <main className="flex-1 px-3 pt-3 pb-4 space-y-3 bg-[var(--color-page)]">
        {/* Summary chips */}
        <section className="grid grid-cols-4 gap-2">
          <SummaryChip Icon={CircleDashed} label="Planned"     value={todaysTaskCounts.planned}    tone="slate" />
          <SummaryChip Icon={Clock}        label="In Progress" value={todaysTaskCounts.inProgress} tone="amber" />
          <SummaryChip Icon={CheckCircle2} label="Completed"   value={todaysTaskCounts.completed}  tone="emerald" />
          <SummaryChip Icon={AlertOctagon} label="Overdue"     value={todaysTaskCounts.overdue}    tone="rose" />
        </section>

        {/* Time-grouped task list */}
        {BLOCK_ORDER.map((block) => {
          const tasks = todaysTasks.filter((t) => t.block === block);
          if (tasks.length === 0) return null;
          const BlockIcon = BLOCK_ICON[block];
          return (
            <section
              key={block}
              className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm"
            >
              <div className="px-3 pt-3 pb-2 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="w-7 h-7 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center">
                    <BlockIcon size={14} />
                  </span>
                  <h3 className="text-body font-extrabold tracking-tight">{block}</h3>
                </div>
                <span className="text-caption muted font-semibold">
                  {tasks.length} task{tasks.length === 1 ? "" : "s"}
                </span>
              </div>
              <ul className="divide-y divide-[var(--color-edify-divider)]">
                {tasks.map((t) => {
                  const Icon = KIND_ICON[t.kind];
                  const StatusIcon = STATUS_ICON[t.status];
                  return (
                    <li key={t.id}>
                      <Link
                        href="/notifications"
                        className="flex items-start gap-3 px-3 py-3 active:bg-[var(--color-edify-soft)]/40"
                      >
                        <div className="text-center w-12 shrink-0 pt-0.5">
                          <div className="text-[11px] font-extrabold tabular leading-none">
                            {t.startTime}
                          </div>
                          <div className="text-[9.5px] muted leading-tight mt-0.5">
                            – {t.endTime}
                          </div>
                        </div>
                        <span className={cn("h-9 w-9 rounded-md grid place-items-center shrink-0 mt-0.5", KIND_TONE[t.kind])}>
                          <Icon size={15} />
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-start justify-between gap-2">
                            <div className="text-body font-extrabold tracking-tight leading-tight">
                              {t.title}
                            </div>
                            <span className={cn("inline-flex items-center gap-0.5 px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap shrink-0", STATUS_TONE[t.status])}>
                              <StatusIcon size={9} />
                              {t.status}
                            </span>
                          </div>
                          <div className="text-caption muted truncate">
                            {t.location}
                          </div>
                          <div className="flex items-center gap-2 mt-0.5 text-[10px] muted">
                            <span>{t.cluster} cluster</span>
                            <span>·</span>
                            <span className={cn(
                              "font-semibold",
                              t.priority === "High"   ? "text-rose-600" :
                              t.priority === "Medium" ? "text-amber-600" :
                                                        "text-slate-500",
                            )}>
                              {t.priority}
                            </span>
                            {t.hasSalesforceId && (
                              <>
                                <span>·</span>
                                <span className="text-emerald-600 font-semibold">SF logged</span>
                              </>
                            )}
                          </div>
                        </div>
                        <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0 mt-1" />
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}

        {/* Quick actions */}
        <section className="grid grid-cols-2 gap-2">
          {todayQuickActions.map((qa) => {
            const Icon = QA_ICON[qa.icon];
            return (
              <Link
                key={qa.key}
                href={qa.href}
                className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm px-3 py-3 flex items-center gap-2.5 active:bg-[var(--color-edify-soft)]/40"
              >
                <span className="h-9 w-9 rounded-md bg-emerald-50 text-emerald-600 grid place-items-center">
                  <Icon size={15} />
                </span>
                <div className="flex-1 text-body font-extrabold tracking-tight">
                  {qa.label}
                </div>
                <ChevronRight size={14} className="text-[var(--color-edify-muted)]" />
              </Link>
            );
          })}
        </section>
      </main>

      <MobileBottomNav />
    </MobileShell>
  );
}

function SummaryChip({
  Icon,
  label,
  value,
  tone,
}: {
  Icon: LucideIcon;
  label: string;
  value: number;
  tone: "slate" | "amber" | "emerald" | "rose";
}) {
  const t =
    tone === "slate"   ? "bg-slate-100   text-slate-700"   :
    tone === "amber"   ? "bg-amber-100   text-amber-700"   :
    tone === "emerald" ? "bg-emerald-100 text-emerald-700" :
                         "bg-rose-100    text-rose-700";
  return (
    <div className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-2 text-center">
      <span className={cn("h-7 w-7 rounded-full grid place-items-center mx-auto", t)}>
        <Icon size={13} />
      </span>
      <div className="text-[18px] font-extrabold tabular leading-none mt-1.5">{value}</div>
      <div className="text-[9.5px] muted font-semibold mt-0.5 line-clamp-1">{label}</div>
    </div>
  );
}
