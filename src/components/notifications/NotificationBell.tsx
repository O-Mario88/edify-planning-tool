"use client";

// NotificationBell — bell icon button that opens the NotificationDrawer
// as an anchored popover (NOT a full-height drawer).
//
// Behavior:
//   • Click → popover opens below + right-aligned to the bell
//   • Popover is ~400px wide × ~560px tall max — sized like a premium
//     dropdown menu, NOT a side drawer
//   • Esc / outside-click → closes (handled inside NotificationDrawer)
//   • Click row → closes + navigates

import { useRef, useState } from "react";
import { Bell } from "lucide-react";
import { NotificationDrawer } from "./NotificationDrawer";
import { useNotifications } from "@/lib/notifications-store";
import { cn } from "@/lib/utils";

type Variant = "today" | "default" | "dark";

export function NotificationBell({
  variant = "default",
}: {
  variant?: Variant;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  // Live counts from the shared store, so marking a notification read in
  // the drawer updates this badge immediately.
  const { counts } = useNotifications();
  const unreadNotificationCount = counts.unread;
  const urgentNotificationCount = counts.urgent;

  const trigger =
    variant === "today"
      ? "relative grid place-items-center h-10 w-10 rounded-xl bg-white border border-[var(--color-edify-divider)] shadow-[0_1px_2px_rgba(15,23,32,0.04)] hover:bg-[var(--color-edify-soft)]/40 transition-colors"
      : variant === "dark"
        ? "relative grid place-items-center h-9 w-9 rounded-xl text-white hover:bg-white/10 active:bg-white/[0.14] transition-colors shrink-0 pressable"
        : "relative h-10 w-10 rounded-xl border border-[var(--color-edify-border)] bg-[var(--surface-1)] flex items-center justify-center hover:bg-[var(--surface-hover)] transition-colors";

  const hasUrgent = urgentNotificationCount > 0;
  const iconSize = variant === "today" ? 17 : variant === "dark" ? 17 : 16;

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-label={`Notifications (${unreadNotificationCount} unread)`}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}
        className={cn(trigger, open && variant !== "dark" && "bg-[var(--color-edify-soft)]")}
      >
        <Bell size={iconSize} className={variant === "today" ? "text-secondary" : ""} />
        {unreadNotificationCount > 0 && (
          <span
            className={cn(
              "absolute -top-1 -right-1 grid place-items-center rounded-full text-white text-[10px] font-bold",
              hasUrgent ? "bg-rose-600" : "bg-[var(--color-edify-primary)]",
              variant === "dark"
                ? "ring-2 ring-[#0e1c2c] h-[16px] min-w-[16px] px-1"
                : "ring-2 ring-white dark:ring-[var(--bg-page)] h-[18px] min-w-[18px] px-[5px] py-[1px]",
            )}
          >
            {unreadNotificationCount}
          </span>
        )}
        {hasUrgent && unreadNotificationCount === 0 && (
          <span
            aria-label="Urgent notifications"
            className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-rose-500 animate-pulse"
          />
        )}
      </button>

      <NotificationDrawer
        open={open}
        onClose={() => setOpen(false)}
        triggerRef={triggerRef}
      />
    </div>
  );
}
