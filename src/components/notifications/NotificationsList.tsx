"use client";

// NotificationsList — the full-page notifications inbox, backed by the live
// notifications-store (the same snapshot that powers the bell badge + drawer).
// No mock data: empty database → EmptyState, request failure → ErrorState,
// in-flight → LoadingState. Every row links to n.href (the backend
// targetRoute) and marks itself read on click, so read-state written here
// stays in sync with the bell.

import Link from "next/link";
import { AlertTriangle, ArrowRight, Bell, CheckCheck } from "lucide-react";
import { StatusBadge } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import type { Notification, NotificationPriority } from "@/lib/notifications-types";
import {
  useNotifications,
  markNotificationRead,
  markAllNotificationsRead,
} from "@/lib/notifications-store";
import { cn } from "@/lib/utils";

const PRIORITY_TONE: Record<NotificationPriority, "amber" | "red" | "violet" | "grey"> = {
  normal: "grey",
  important: "amber",
  urgent: "red",
  critical: "red",
};

const PRIORITY_LABEL: Record<NotificationPriority, string> = {
  normal: "Normal",
  important: "Important",
  urgent: "Urgent",
  critical: "Critical",
};

export function NotificationsList() {
  const { list, counts, loading, error, reload } = useNotifications();

  if (loading) {
    return (
      <section className="card rounded-2xl px-4 py-2">
        <LoadingState message="Loading notifications…" rows={5} />
      </section>
    );
  }

  if (error) {
    return (
      <section className="card rounded-2xl px-4">
        <ErrorState message="Could not load notifications." onRetry={reload} />
      </section>
    );
  }

  if (list.length === 0) {
    return (
      <section className="card rounded-2xl px-4">
        <EmptyState
          icon={Bell}
          title="You are all caught up."
          message="No notifications need your attention right now. New alerts about evidence, payments, approvals, and field work will appear here."
        />
      </section>
    );
  }

  return (
    <section className="card rounded-2xl overflow-hidden">
      {/* Mark-all-read header — only when something is unread. */}
      {counts.unread > 0 && (
        <div className="flex items-center justify-between gap-2 px-4 py-2.5 border-b border-[var(--color-edify-divider)]">
          <span className="text-caption muted tabular">
            {counts.unread} unread of {counts.all}
          </span>
          <button
            type="button"
            onClick={() => markAllNotificationsRead()}
            className="inline-flex items-center gap-1.5 rounded-full px-2.5 h-7 text-[11px] font-bold text-[var(--color-edify-primary)] hover:bg-[var(--color-edify-soft)]/40 transition-colors"
          >
            <CheckCheck size={12} />
            Mark all read
          </button>
        </div>
      )}

      <ul className="divide-y divide-[var(--color-edify-divider)]">
        {list.map((n) => (
          <li key={n.id}>
            <NotificationRow notification={n} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function NotificationRow({ notification: n }: { notification: Notification }) {
  const priorityTone = n.priority ? PRIORITY_TONE[n.priority] : null;
  const showPriorityBadge =
    n.priority &&
    (n.priority === "urgent" || n.priority === "critical" || n.priority === "important");

  return (
    <Link
      href={n.href}
      onClick={() => markNotificationRead(n.id)}
      className={cn(
        "flex items-start gap-3 px-4 py-3.5 transition-colors group relative",
        n.unread
          ? "bg-[var(--color-edify-soft)]/30 hover:bg-[var(--color-edify-soft)]/50"
          : "hover:bg-[var(--surface-hover)]",
      )}
    >
      {n.unread && (
        <span
          aria-hidden
          className="absolute left-0 top-3 bottom-3 w-[2.5px] rounded-r-full bg-[var(--color-edify-primary)]"
        />
      )}

      <span className={cn("h-9 w-9 rounded-md grid place-items-center shrink-0", n.iconBg, n.iconText)}>
        <n.Icon size={15} />
      </span>

      <div className="flex-1 min-w-0">
        <div className="flex items-baseline justify-between gap-2">
          <h4
            className={cn(
              "text-body tracking-tight",
              n.unread
                ? "font-extrabold text-[var(--text-primary)]"
                : "font-bold text-[var(--text-secondary)]",
            )}
          >
            {n.title}
            {n.unread && (
              <span
                className="ml-2 inline-block w-1.5 h-1.5 rounded-full bg-[var(--color-edify-primary)] align-middle"
                aria-label="Unread"
              />
            )}
          </h4>
          <time className="text-caption muted shrink-0 tabular">{n.ago}</time>
        </div>

        <p
          className={cn(
            "text-[11.5px] leading-snug mt-0.5",
            n.unread ? "text-[var(--text-secondary)]" : "muted",
          )}
        >
          {n.body}
        </p>

        {(n.category || showPriorityBadge || n.actionRequired || n.contextLabel) && (
          <div className="flex flex-wrap items-center gap-1 mt-1.5">
            {n.category && <StatusBadge tone="grey">{n.category}</StatusBadge>}
            {showPriorityBadge && priorityTone && (
              <StatusBadge tone={priorityTone}>
                <AlertTriangle size={8} className="mr-0.5" />
                {n.priority ? PRIORITY_LABEL[n.priority] : ""}
              </StatusBadge>
            )}
            {n.actionRequired && <StatusBadge tone="amber">Action</StatusBadge>}
            {n.contextLabel && (
              <span className="text-[10px] muted truncate ml-0.5">· {n.contextLabel}</span>
            )}
          </div>
        )}

        {n.actionRequired && n.actionLabel && (
          <span className="mt-1.5 inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-edify-primary)] group-hover:gap-1.5 transition-all">
            {n.actionLabel}
            <ArrowRight size={11} />
          </span>
        )}
      </div>
    </Link>
  );
}
