"use client";

import { useState } from "react";
import Link from "next/link";
import { Calendar, Check, ChevronRight } from "lucide-react";
import { myTasks, taskTabCounts, type WorkTask, type TaskTabKey, type TaskStatus, type Priority } from "@/lib/work-plan-mock";
import { cn } from "@/lib/utils";

const TABS: { key: TaskTabKey; label: string }[] = [
  { key: "all",         label: "All" },
  { key: "completed",   label: "Completed" },
  { key: "in_progress", label: "In Progress" },
  { key: "overdue",     label: "Overdue" },
];

const STATUS_BADGE: Record<TaskStatus, string> = {
  Completed:     "bg-emerald-50 text-emerald-700",
  "In Progress": "bg-blue-50 text-blue-700",
  Overdue:       "bg-rose-50 text-rose-700",
  "Not Started": "bg-[#eef2f4] text-[#475467]",
};

const STATUS_RADIO: Record<TaskStatus, string> = {
  Completed:     "bg-emerald-500 border-emerald-500 text-white",
  "In Progress": "border-blue-500 text-blue-500",
  Overdue:       "border-rose-500 text-rose-500",
  "Not Started": "border-[var(--color-edify-border)] text-[var(--color-edify-muted)]",
};

const PRIORITY_BADGE: Record<Priority, string> = {
  High:   "bg-rose-50 text-rose-700",
  Medium: "bg-blue-50 text-blue-700",
  Low:    "bg-[#eef2f4] text-[#475467]",
};

// Override: when status is Completed, show priority pill in green to mirror
// the screenshot (priority pill picks up the "good" tone for completed tasks).
function priorityClass(p: Priority, s: TaskStatus): string {
  if (s === "Completed") return "bg-emerald-50 text-emerald-700";
  if (s === "In Progress" && p === "High") return "bg-orange-50 text-orange-700";
  return PRIORITY_BADGE[p];
}

export function MyTasksCard() {
  const [tab, setTab] = useState<TaskTabKey>("all");
  const counts = taskTabCounts();

  const filtered = myTasks.filter((t) => {
    if (tab === "all") return true;
    if (tab === "completed")   return t.status === "Completed";
    if (tab === "in_progress") return t.status === "In Progress";
    if (tab === "overdue")     return t.status === "Overdue";
    return true;
  });

  return (
    <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-4">
      <h3 className="text-[15px] font-extrabold tracking-tight mb-3">My Tasks</h3>

      {/* Tabs */}
      <div className="flex items-center gap-4 border-b border-[#eef2f4] -mx-1 px-1 overflow-x-auto">
        {TABS.map((t) => {
          const active = tab === t.key;
          const count = counts[t.key];
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={cn(
                "h-9 inline-flex items-center gap-1.5 text-body font-semibold whitespace-nowrap relative",
                active ? "text-emerald-600" : "text-[var(--color-edify-muted)]",
              )}
            >
              {t.label} <span className="muted">({count})</span>
              {active && <span className="absolute -bottom-px left-0 right-0 h-[2px] bg-emerald-500 rounded-t" />}
            </button>
          );
        })}
      </div>

      {/* Task rows */}
      <div className="divide-y divide-[var(--color-edify-divider)]">
        {filtered.length === 0 ? (
          <div className="text-[12px] muted text-center py-6">No tasks in this view.</div>
        ) : (
          filtered.map((t) => <TaskRow key={t.id} task={t} />)
        )}
      </div>
    </section>
  );
}

function TaskRow({ task }: { task: WorkTask }) {
  return (
    <Link href="/notifications" className="flex items-start gap-3 py-3 active:bg-[var(--color-edify-soft)]/40 -mx-1 px-1 rounded-md">
      <span
        className={cn(
          "mt-0.5 w-5 h-5 rounded-full border-2 grid place-items-center shrink-0",
          STATUS_RADIO[task.status],
        )}
      >
        {task.status === "Completed" && <Check size={12} strokeWidth={3} />}
      </span>

      <div className="flex-1 min-w-0">
        <div className="text-[13px] font-bold leading-tight line-clamp-2">{task.title}</div>
        <div className="flex items-center gap-2 mt-1.5">
          <span
            className={cn(
              "inline-flex items-center px-2 py-[2px] rounded-md text-caption font-extrabold",
              priorityClass(task.priority, task.status),
            )}
          >
            {task.priority}
          </span>
          <span className="inline-flex items-center gap-1 text-[11px] muted">
            <Calendar size={10} />
            {task.dueDate}
          </span>
        </div>
      </div>

      <span
        className={cn(
          "shrink-0 inline-flex items-center px-2 py-[3px] rounded-md text-[11px] font-extrabold",
          STATUS_BADGE[task.status],
        )}
      >
        {task.status}
      </span>
      <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0 mt-1" />
    </Link>
  );
}
