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
  type LucideIcon,
} from "lucide-react";
import { MobileViewDesktopShell } from "@/components/mobile/MobileViewDesktopShell";
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

const BLOCK_ICON: Record<TodaysTaskBlock, LucideIcon> = {
  Morning:   Sunrise,
  Afternoon: Sun,
  Evening:   Moon,
};

const BLOCKS: TodaysTaskBlock[] = ["Morning", "Afternoon", "Evening"];

export function TodayDesktopView() {
  return (
    <MobileViewDesktopShell
      title="Today's Tasks"
      subtitle={`${todayHeader.dateLabel} · ${todayHeader.weekLabel}`}
      asideRight={<TodaySidebar />}
    >
      <section className="space-y-4">
        {BLOCKS.map((b) => {
          const tasks = todaysTasks.filter((t) => t.block === b);
          if (tasks.length === 0) return null;
          const BIcon = BLOCK_ICON[b];
          return (
            <article key={b} className="card p-3.5">
              <header className="flex items-baseline justify-between mb-3">
                <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
                  <BIcon size={14} className="text-[var(--color-edify-primary)]" />
                  {b}
                </h2>
                <span className="text-caption muted">{tasks.length} task{tasks.length === 1 ? "" : "s"}</span>
              </header>
              <ul className="divide-y divide-[var(--color-edify-divider)]">
                {tasks.map((t) => {
                  const Icon = KIND_ICON[t.kind];
                  const SIcon = STATUS_ICON[t.status];
                  return (
                    <li key={t.id} className="py-2.5 flex items-start gap-3">
                      <span className={cn("h-9 w-9 rounded-md grid place-items-center shrink-0", KIND_TONE[t.kind])}>
                        <Icon size={15} />
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px] font-extrabold tracking-tight truncate">{t.title}</div>
                        <div className="text-caption muted truncate">
                          {t.startTime}–{t.endTime} · {t.location}
                        </div>
                      </div>
                      <span className={cn(
                        "inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap shrink-0",
                        STATUS_TONE[t.status],
                      )}>
                        <SIcon size={10} />
                        {t.status}
                      </span>
                      {t.hasSalesforceId && (
                        <span className="text-[9.5px] font-extrabold text-emerald-700 shrink-0">SF ✓</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </article>
          );
        })}
      </section>
    </MobileViewDesktopShell>
  );
}

function TodaySidebar() {
  return (
    <>
      <div className="card p-3.5">
        <h3 className="text-body font-extrabold tracking-tight uppercase muted mb-2">Today at a glance</h3>
        <div className="grid grid-cols-2 gap-2">
          <Stat label="Total"        value={todaysTaskCounts.total}      />
          <Stat label="Completed"    value={todaysTaskCounts.completed}  tone="green" />
          <Stat label="In progress"  value={todaysTaskCounts.inProgress} tone="amber" />
          <Stat label="Planned"      value={todaysTaskCounts.planned}    />
          {todaysTaskCounts.overdue > 0 && (
            <Stat label="Overdue"    value={todaysTaskCounts.overdue}    tone="rose" />
          )}
        </div>
      </div>
      <div className="card p-3.5">
        <h3 className="text-body font-extrabold tracking-tight uppercase muted mb-2">Quick actions</h3>
        <div className="grid grid-cols-2 gap-2">
          {todayQuickActions.map((a) => (
            <Link
              key={a.key}
              href={a.href}
              className="rounded-xl border border-[var(--color-edify-border)] p-3 flex items-center gap-2 hover:bg-[var(--color-edify-soft)]/40"
            >
              <span className="text-body font-extrabold tracking-tight">{a.label}</span>
              <ChevronRight size={11} className="ml-auto text-[var(--color-edify-muted)]" />
            </Link>
          ))}
        </div>
      </div>
    </>
  );
}

function Stat({ label, value, tone = "edify" }: { label: string; value: number; tone?: "edify" | "green" | "amber" | "rose" }) {
  const TONE = {
    edify: "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
    green: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100   text-amber-700",
    rose:  "bg-rose-100    text-rose-700",
  } as const;
  return (
    <div className={cn("rounded-xl p-2.5", TONE[tone])}>
      <div className="text-[10px] font-bold uppercase tracking-wide leading-tight opacity-90">{label}</div>
      <div className="text-[20px] font-extrabold tabular leading-none mt-1">{value}</div>
    </div>
  );
}
