"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { CheckCheck, AlertTriangle, Inbox, ArrowRight, X } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { StatusBadge, type ChipTone } from "@/components/ui/primitives";
import { useRecentMessages } from "@/components/shell/PageTitleContext";
import { formatMessageTime } from "@/lib/messages-v2/access";
import type {
  Message,
  MessagePriority,
  MessageCategory,
} from "@/lib/messages-v2/types";
import { cn } from "@/lib/utils";

// MessageDrawer — anchored floating popover the message icon opens.
//
// Same behavior contract as NotificationDrawer:
//   • Click message icon → popover opens below + right-aligned
//   • Click row → mark read, close popover, navigate to /messages/[id]
//   • Esc / outside-click → close
//
// Sized like a premium dropdown — ~400px wide × ~560px tall max —
// NOT a full-height side drawer. The page behind stays visible.

type Filter = "All" | "Unread" | "Action" | "Urgent";

const FILTERS: Filter[] = ["All", "Unread", "Action", "Urgent"];

const PRIORITY_TONE: Record<MessagePriority, ChipTone> = {
  Normal:    "grey",
  Important: "amber",
  Urgent:    "red",
  Critical:  "red",
};

const CATEGORY_LABEL: Record<MessageCategory, string> = {
  "field-debrief":        "Debrief",
  "partner-debrief":      "Debrief",
  "evidence-review":      "Evidence",
  "correction-request":   "Correction",
  "payment-update":       "Payment",
  "planning-assignment":  "Planning",
  "partner-scheduling":   "Scheduling",
  "school-followup":      "Follow-Up",
  "cluster-update":       "Cluster",
  "ssa-update":           "SSA",
  "finance":              "Finance",
  "hr-support":           "HR",
  "system-notification":  "System",
  "leadership-decision":  "Decision",
  "general":              "Internal",
};

export function MessageDrawer({
  open,
  onClose,
  triggerRef,
}: {
  open:        boolean;
  onClose:     () => void;
  triggerRef?: React.RefObject<HTMLElement | null>;
}) {
  const router = useRouter();
  const recent = useRecentMessages();
  const [readIds, setReadIds] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<Filter>("All");
  const panelRef = useRef<HTMLDivElement | null>(null);

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

  const messages = useMemo(
    () =>
      recent.map((m) => ({
        ...m,
        status: readIds.has(m.id) ? ("read" as const) : m.status,
      })),
    [recent, readIds],
  );

  const isUnread = (m: Message) =>
    m.status === "unread" || m.status === "action_required";
  const isActionRequired = (m: Message) =>
    m.status === "action_required" ||
    m.recipients.some((r) => r.actionRequired && (r.status === "unread" || r.status === "action_required"));
  const isUrgent = (m: Message) =>
    m.priority === "Urgent" || m.priority === "Critical";

  const counts = useMemo(() => ({
    all:    messages.length,
    unread: messages.filter(isUnread).length,
    action: messages.filter((m) => isUnread(m) && isActionRequired(m)).length,
    urgent: messages.filter((m) => isUnread(m) && isUrgent(m)).length,
  }), [messages]);

  const visible = useMemo(() => {
    if (filter === "Unread") return messages.filter(isUnread);
    if (filter === "Action") return messages.filter((m) => isUnread(m) && isActionRequired(m));
    if (filter === "Urgent") return messages.filter((m) => isUnread(m) && isUrgent(m));
    return messages;
  }, [filter, messages]);

  function handleSelect(m: Message) {
    setReadIds((prev) => {
      const next = new Set(prev);
      next.add(m.id);
      return next;
    });
    onClose();
    // Routing branches on viewport:
    //   • Desktop (≥lg) → /messages — the two-pane layout shows the
    //     inbox list + detail at once.  Passing `?id=<m.id>` so
    //     MessageCenterLayout can pre-select that thread.
    //   • Tablet / mobile (<lg) → /messages/[id] — the dedicated
    //     detail page is the right surface on narrow viewports where
    //     a side-by-side layout doesn't fit.
    setTimeout(() => {
      const isDesktop =
        typeof window !== "undefined" &&
        window.matchMedia("(min-width: 1024px)").matches;
      router.push(isDesktop ? `/messages?id=${m.id}` : `/messages/${m.id}`);
    }, 100);
  }

  function markAllRead() {
    setReadIds(new Set(recent.map((m) => m.id)));
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Page-blur backdrop — same pattern as NotificationDrawer.
              Soft 12px blur + barely-there dim; click passes through
              to the document so the outside-click handler closes the
              drawer. */}
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
            aria-label="Messages"
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.16, ease: [0.2, 0.6, 0.2, 1] }}
            className={cn(
              "absolute right-0 top-[calc(100%+8px)] z-50",
              "w-[420px] max-w-[calc(100vw-24px)]",
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
                Messages
              </h2>
              <p className="text-[11.5px] text-muted leading-snug mt-0.5">
                Recent messages, actions, replies, and updates.
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close messages"
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
                  {f === "Action" ? "Action" : f}
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

          {/* Message list */}
          <div className="flex-1 min-h-0 overflow-y-auto">
            {visible.length === 0 ? (
              <EmptyState filter={filter} />
            ) : (
              <ul className="divide-y divide-[var(--color-edify-divider)]">
                {visible.map((m) => (
                  <li key={m.id}>
                    <MessageRow message={m} onSelect={() => handleSelect(m)} />
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
              href="/messages"
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

function MessageRow({
  message: m,
  onSelect,
}: {
  message:  Message;
  onSelect: () => void;
}) {
  const unread = m.status === "unread" || m.status === "action_required";
  const initials =
    m.senderInitials ?? m.senderName
      .split(/\s+/)
      .map((n) => n[0])
      .join("")
      .slice(0, 2)
      .toUpperCase();
  const time = formatMessageTime(m.createdAt);
  const actionRequired = m.status === "action_required";
  const showPriority = m.priority !== "Normal";

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full text-left flex items-start gap-2.5 px-3.5 py-2.5 transition-colors group relative",
        unread
          ? "bg-[var(--color-edify-soft)]/30 hover:bg-[var(--color-edify-soft)]/50"
          : "bg-transparent hover:bg-[var(--surface-hover)]",
      )}
    >
      {unread && (
        <span
          aria-hidden
          className="absolute left-0 top-3 bottom-3 w-[2.5px] rounded-r-full bg-[var(--color-edify-primary)]"
        />
      )}

      <span className="h-8 w-8 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center shrink-0 text-[10px] font-extrabold tabular">
        {initials}
      </span>

      <div className="flex-1 min-w-0">
        <div className="flex items-baseline justify-between gap-2">
          <h4 className={cn(
            "text-[12.5px] truncate leading-snug",
            unread
              ? "font-extrabold text-[var(--text-primary)]"
              : "font-bold text-[var(--text-secondary)]",
          )}>
            {m.subject}
          </h4>
          <time className="text-[10px] text-muted shrink-0 tabular">{time}</time>
        </div>

        <p className="text-[10.5px] text-muted leading-tight mt-0.5 truncate">
          {m.senderName}
          <span className="mx-1">·</span>
          {m.senderRole}
        </p>

        <p className={cn(
          "text-[10.5px] mt-0.5 leading-snug line-clamp-2",
          unread ? "text-[var(--text-secondary)]" : "text-muted",
        )}>
          {m.preview}
        </p>

        <div className="flex flex-wrap items-center gap-1 mt-1.5">
          <StatusBadge tone="grey">{CATEGORY_LABEL[m.category]}</StatusBadge>
          {showPriority && (
            <StatusBadge tone={PRIORITY_TONE[m.priority]}>
              {m.priority === "Urgent" || m.priority === "Critical" ? (
                <AlertTriangle size={8} className="mr-0.5" />
              ) : null}
              {m.priority}
            </StatusBadge>
          )}
          {actionRequired && (
            <StatusBadge tone="amber">Action</StatusBadge>
          )}
        </div>
      </div>
    </button>
  );
}

function EmptyState({ filter }: { filter: Filter }) {
  const heading =
    filter === "Unread" ? "No unread messages." :
    filter === "Action" ? "No action-required messages." :
    filter === "Urgent" ? "No urgent messages." :
                          "You are all caught up.";
  const sub =
    filter === "All"
      ? "No new messages need your attention."
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
