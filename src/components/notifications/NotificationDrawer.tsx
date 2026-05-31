"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { CheckCheck, AlertTriangle, Inbox, ArrowRight, X } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { StatusBadge } from "@/components/ui/primitives";
import type { Notification, NotificationPriority } from "@/lib/notifications-mock";
import {
  useNotifications,
  markNotificationRead,
  markAllNotificationsRead,
} from "@/lib/notifications-store";
import { cn } from "@/lib/utils";

// NotificationDrawer — anchored floating popover the bell opens.
//
// Behavior contract:
//   • Bell click → popover opens, user stays on the current page.
//   • Selecting a notification → mark read, close popover, navigate.
//   • Esc / outside-click → close, no navigation.
//   • Filter pills (All / Unread / Action / Urgent) re-scope the list.
//   • Mark all as read → clears unread state on every notification.
//
// Sized like a premium dropdown — ~400px wide, max ~560px tall — so
// the page behind it stays visible (per spec: "slightly bigger than
// the avatar menu, NOT covering the entire section of the page").
// Outside-click + Esc + focus-restore are handled here; the bell
// passes `triggerRef` so we can ignore clicks on the trigger itself.

// Read state + counts come from the shared notifications-store so the
// bell badge stays in sync with what's marked read here.
type Filter = "All" | "Unread" | "Action" | "Urgent";

const FILTERS: Filter[] = ["All", "Unread", "Action", "Urgent"];

const PRIORITY_TONE: Record<NotificationPriority, "amber" | "red" | "violet" | "grey"> = {
  normal:    "grey",
  important: "amber",
  urgent:    "red",
  critical:  "red",
};

const PRIORITY_LABEL: Record<NotificationPriority, string> = {
  normal:    "Normal",
  important: "Important",
  urgent:    "Urgent",
  critical:  "Critical",
};

export function NotificationDrawer({
  open,
  onClose,
  triggerRef,
}: {
  open:        boolean;
  onClose:     () => void;
  /** The button that opened this popover, so the outside-click handler
   *  can ignore clicks on it (otherwise the toggle would immediately
   *  re-close as it re-fires). */
  triggerRef?: React.RefObject<HTMLElement | null>;
}) {
  const router = useRouter();
  const { list: notifications, counts } = useNotifications();
  const [filter, setFilter] = useState<Filter>("All");
  const panelRef = useRef<HTMLDivElement | null>(null);

  // Outside-click + Esc to close.
  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      const t = e.target as Node;
      if (panelRef.current && !panelRef.current.contains(t) &&
          (!triggerRef?.current || !triggerRef.current.contains(t))) {
        onClose();
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose, triggerRef]);

  const visible = useMemo(() => {
    if (filter === "Unread")  return notifications.filter((n) => n.unread);
    if (filter === "Action")  return notifications.filter((n) => n.unread && n.actionRequired);
    if (filter === "Urgent")  return notifications.filter((n) =>
      n.unread && (n.priority === "urgent" || n.priority === "critical")
    );
    return notifications;
  }, [filter, notifications]);

  function handleSelect(n: Notification) {
    markNotificationRead(n.id);
    onClose();
    setTimeout(() => router.push(n.href), 100);
  }

  function markAllRead() {
    markAllNotificationsRead();
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Page-blur backdrop — fixed to the viewport so it sits
              above page content but under the popover panel.  Click
              passes through to the document so the outside-click
              handler closes the drawer.  Soft blur + barely-there
              dim keeps the page readable behind. */}
          <motion.div
            aria-hidden
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="fixed inset-0 z-40 backdrop-blur-md bg-[rgba(15,23,32,0.10)] dark:bg-[rgba(0,0,0,0.30)] pointer-events-none"
          />

          <motion.div
            ref={panelRef}
            role="dialog"
            aria-label="Notifications"
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.16, ease: [0.2, 0.6, 0.2, 1] }}
            className={cn(
              "absolute right-0 top-[calc(100%+8px)] z-50",
              "w-[400px] max-w-[calc(100vw-24px)]",
              "premium-popover rounded-2xl overflow-hidden",
              "shadow-[0_24px_64px_-12px_rgba(15,23,32,0.30),0_4px_10px_rgba(15,23,32,0.10)]",
              "flex flex-col",
            )}
            style={{ maxHeight: "min(560px, calc(100vh - 80px))" }}
          >
          {/* Header */}
          <header className="px-4 py-3 border-b border-[var(--color-edify-border)] flex items-start gap-3">
            <div className="flex-1 min-w-0">
              <h2 className="text-[14px] font-extrabold tracking-tight text-[var(--text-primary)]">
                Notifications
              </h2>
              <p className="text-[11.5px] text-muted leading-snug mt-0.5">
                Updates on messages, approvals, evidence, payments, planning, and field activity.
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close notifications"
              className="h-7 w-7 rounded-md grid place-items-center text-[var(--text-muted)] hover:bg-[var(--surface-hover)] shrink-0"
            >
              <X size={14} />
            </button>
          </header>

          {/* Filter rail + mark-all-read */}
          <div className="px-3 pt-2.5 pb-2 border-b border-[var(--color-edify-border)] flex items-center gap-1.5 overflow-x-auto scrollbar -mx-0.5">
            {FILTERS.map((f) => {
              const active = filter === f;
              const count =
                f === "All"    ? counts.all :
                f === "Unread" ? counts.unread :
                f === "Action" ? counts.action :
                                 counts.urgent;
              return (
                <button
                  key={f}
                  type="button"
                  onClick={() => setFilter(f)}
                  className={cn(
                    "shrink-0 inline-flex items-center gap-1 h-6 px-2 rounded-full text-[11px] font-bold transition-colors",
                    active
                      ? "bg-[var(--color-edify-primary)] text-white"
                      : "bg-[var(--color-edify-soft)]/60 text-[var(--text-primary)] hover:bg-[var(--color-edify-soft)]",
                  )}
                >
                  {f}
                  <span className={cn(
                    "inline-flex items-center justify-center min-w-[15px] h-[15px] px-0.5 rounded-full text-[9px] tabular",
                    active ? "bg-white/25 text-white" : "bg-white text-[var(--text-muted)]",
                  )}>
                    {count}
                  </span>
                </button>
              );
            })}
            {counts.unread > 0 && (
              <button
                type="button"
                onClick={markAllRead}
                className="shrink-0 ml-auto inline-flex items-center gap-1 h-6 px-2 rounded-full text-[10.5px] font-bold text-[var(--color-edify-primary)] hover:bg-[var(--color-edify-soft)]/40 transition-colors"
              >
                <CheckCheck size={10} />
                Mark all read
              </button>
            )}
          </div>

          {/* Notification list — flex-1 + min-h-0 so it scrolls inside
              the bounded popover height. */}
          <div className="flex-1 min-h-0 overflow-y-auto">
            {visible.length === 0 ? (
              <EmptyState filter={filter} />
            ) : (
              <ul className="divide-y divide-[var(--color-edify-divider)]">
                {visible.map((n) => (
                  <li key={n.id}>
                    <NotificationRow notification={n} onSelect={() => handleSelect(n)} />
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Footer */}
          <footer className="border-t border-[var(--color-edify-border)] px-3 py-2 flex items-center justify-between bg-[var(--surface-popover)]">
            <span className="text-[10.5px] text-muted tabular">
              {counts.unread} unread of {counts.all}
            </span>
            <Link
              href="/notifications"
              onClick={onClose}
              className="inline-flex items-center gap-1 text-[10.5px] font-bold text-[var(--color-edify-primary)] hover:underline"
            >
              View All
              <ArrowRight size={10} />
            </Link>
          </footer>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

function NotificationRow({
  notification: n,
  onSelect,
}: {
  notification: Notification;
  onSelect:     () => void;
}) {
  const priorityTone = n.priority ? PRIORITY_TONE[n.priority] : null;
  const showPriorityBadge =
    n.priority && (n.priority === "urgent" || n.priority === "critical" || n.priority === "important");

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full text-left flex items-start gap-2.5 px-3.5 py-2.5 transition-colors group relative",
        n.unread
          ? "bg-[var(--color-edify-soft)]/30 hover:bg-[var(--color-edify-soft)]/50"
          : "bg-transparent hover:bg-[var(--surface-hover)]",
      )}
    >
      {n.unread && (
        <span
          aria-hidden
          className="absolute left-0 top-3 bottom-3 w-[2.5px] rounded-r-full bg-[var(--color-edify-primary)]"
        />
      )}

      <span className={cn(
        "h-8 w-8 rounded-md grid place-items-center shrink-0",
        n.iconBg,
        n.iconText,
      )}>
        <n.Icon size={13} />
      </span>

      <div className="flex-1 min-w-0">
        <div className="flex items-baseline justify-between gap-2">
          <h4 className={cn(
            "text-[12.5px] truncate leading-snug",
            n.unread
              ? "font-extrabold text-[var(--text-primary)]"
              : "font-bold text-[var(--text-secondary)]",
          )}>
            {n.title}
          </h4>
          <time className="text-[10px] text-muted shrink-0 tabular">{n.ago}</time>
        </div>

        <p className={cn(
          "text-[10.5px] mt-0.5 leading-snug line-clamp-2",
          n.unread ? "text-[var(--text-secondary)]" : "text-muted",
        )}>
          {n.body}
        </p>

        {(n.category || showPriorityBadge || n.contextLabel) && (
          <div className="flex flex-wrap items-center gap-1 mt-1.5">
            {n.category && (
              <StatusBadge tone="grey">{n.category}</StatusBadge>
            )}
            {showPriorityBadge && priorityTone && (
              <StatusBadge tone={priorityTone}>
                <AlertTriangle size={8} className="mr-0.5" />
                {n.priority ? PRIORITY_LABEL[n.priority] : ""}
              </StatusBadge>
            )}
            {n.actionRequired && (
              <StatusBadge tone="amber">Action</StatusBadge>
            )}
            {n.contextLabel && (
              <span className="text-[10px] text-muted truncate ml-0.5">
                · {n.contextLabel}
              </span>
            )}
          </div>
        )}

        {/* Action affordance — when the notification requires the user to
            act, surface the concrete action it routes to (e.g. "Review
            Queue", "Submit Debrief") so the row reads as a task, not just
            an FYI. Selecting the row already navigates to n.href. */}
        {n.actionRequired && n.actionLabel && (
          <span className="mt-1.5 inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-edify-primary)] group-hover:gap-1.5 transition-all">
            {n.actionLabel}
            <ArrowRight size={11} />
          </span>
        )}
      </div>
    </button>
  );
}

function EmptyState({ filter }: { filter: Filter }) {
  const heading =
    filter === "Unread" ? "All unread cleared." :
    filter === "Action" ? "No action-required items." :
    filter === "Urgent" ? "No urgent items." :
                          "You are all caught up.";
  const sub =
    filter === "All"
      ? "No new notifications need your attention."
      : "Nothing in this filter at the moment.";

  return (
    <div className="px-4 py-10 flex flex-col items-center text-center gap-2.5">
      <span className="w-10 h-10 rounded-full bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 grid place-items-center">
        <Inbox size={16} />
      </span>
      <div className="space-y-0.5 max-w-sm">
        <p className="text-[12.5px] font-bold text-[var(--text-primary)]">{heading}</p>
        <p className="text-[10.5px] text-muted">{sub}</p>
      </div>
    </div>
  );
}
