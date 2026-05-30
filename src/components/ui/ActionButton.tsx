"use client";

import { useState, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { useDemoStore, type Toast } from "@/components/demo/DemoStore";
import { cn } from "@/lib/utils";

// Tiny client-side action button. Drop-in replacement for the inert
// <button> placeholders scattered across server pages. Shows a loading
// spinner for 400–600ms, pushes a toast via DemoStore, then optionally
// flips into a "done" state.
//
// Usage:
//   <ActionButton
//     toast={{ tone: "success", title: "Plan submitted to Program Lead." }}
//     label="Submit"
//     className="btn btn-sm btn-primary"
//   />
//
// For a one-shot button that disappears after click (e.g. "Approve"
// turning into an "Approved" badge), set `oneShot` and provide
// `oneShotLabel`.
export function ActionButton({
  label,
  toast,
  className,
  busyMs = 450,
  disabled,
  oneShot,
  oneShotLabel,
  oneShotClassName,
  ariaLabel,
  Icon,
}: {
  label: ReactNode;
  toast: Omit<Toast, "id">;
  className?: string;
  busyMs?: number;
  disabled?: boolean;
  oneShot?: boolean;
  oneShotLabel?: ReactNode;
  oneShotClassName?: string;
  ariaLabel?: string;
  Icon?: React.ComponentType<{ size?: number; className?: string }>;
}) {
  const { pushToast } = useDemoStore();
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  function go() {
    if (busy || done) return;
    setBusy(true);
    window.setTimeout(() => {
      setBusy(false);
      if (oneShot) setDone(true);
      pushToast(toast);
    }, busyMs);
  }

  if (done && oneShot) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 h-7 px-2.5 rounded-md text-[11.5px] font-bold bg-emerald-100 text-emerald-700",
          oneShotClassName,
        )}
      >
        {oneShotLabel ?? "Done"}
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={go}
      disabled={disabled || busy}
      aria-label={ariaLabel}
      className={cn(
        "inline-flex items-center gap-1.5 disabled:opacity-55 disabled:cursor-not-allowed",
        className,
      )}
    >
      {busy ? <Loader2 size={12} className="animate-spin" /> : Icon ? <Icon size={12} /> : null}
      {label}
    </button>
  );
}
