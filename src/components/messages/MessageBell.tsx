"use client";

// MessageBell — message icon button that opens the MessageDrawer as an
// anchored popover (NOT a full-height side drawer).
//
// Sibling of NotificationBell: same trigger geometry, same anchored
// popover pattern, same close + navigate flow.

import { useRef, useState } from "react";
import { MessageSquare } from "lucide-react";
import { MessageDrawer } from "./MessageDrawer";
import { useMessages } from "./messages-store";
import { cn } from "@/lib/utils";

type Variant = "default" | "today" | "dark";

export function MessageBell({ variant = "default" }: { variant?: Variant }) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const { counts } = useMessages();
  const unread = counts.unread;

  const trigger =
    variant === "today"
      ? "relative grid place-items-center h-10 w-10 rounded-xl bg-white border border-[var(--color-edify-divider)] shadow-[0_1px_2px_rgba(15,23,32,0.04)] hover:bg-[var(--color-edify-soft)]/40 transition-colors"
      : variant === "dark"
        ? "relative grid place-items-center h-9 w-9 rounded-xl text-white hover:bg-white/10 active:bg-white/[0.14] transition-colors shrink-0 pressable"
        : "relative h-10 w-10 rounded-xl border border-[var(--color-edify-border)] bg-[var(--surface-1)] flex items-center justify-center hover:bg-[var(--surface-hover)] transition-colors";

  const iconSize = variant === "today" ? 17 : variant === "dark" ? 17 : 16;

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-label={`Messages (${unread} unread)`}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}
        className={cn(trigger, open && variant !== "dark" && "bg-[var(--color-edify-soft)]")}
      >
        <MessageSquare
          size={iconSize}
          className={variant === "today" ? "text-secondary" : ""}
        />
        {unread > 0 && (
          <span
            className={cn(
              "absolute -top-1 -right-1 grid place-items-center rounded-full bg-[var(--color-edify-primary)] text-white text-[10px] font-bold",
              variant === "dark"
                ? "ring-2 ring-[#0e1c2c] h-[16px] min-w-[16px] px-1"
                : "ring-2 ring-white dark:ring-[var(--bg-page)] h-[18px] min-w-[18px] px-1",
            )}
          >
            {unread}
          </span>
        )}
      </button>

      <MessageDrawer
        open={open}
        onClose={() => setOpen(false)}
        triggerRef={triggerRef}
      />
    </div>
  );
}
