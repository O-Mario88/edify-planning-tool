"use client";

// Canonical empty / error / loading states for the backend-only migration.
// Every real surface uses these instead of inventing mock data:
//   • backend returned no records  → <EmptyState>
//   • backend request failed        → <ErrorState onRetry={…}>
//   • request in flight             → <LoadingState>
// "No backend data = empty state. Backend failure = error. Never fake data."

import { Inbox, AlertTriangle, RefreshCw } from "lucide-react";
import { Skeleton } from "@/components/ui/Skeleton";

export function EmptyState({
  title = "No records yet",
  message,
  icon: Icon = Inbox,
  compact = false,
}: {
  title?: string;
  message?: string;
  icon?: typeof Inbox;
  compact?: boolean;
}) {
  return (
    <div className={`text-center ${compact ? "py-6" : "py-12"}`}>
      <div className="mx-auto mb-3 grid place-items-center w-11 h-11 rounded-full bg-[var(--color-edify-soft)]/60">
        <Icon size={20} className="text-[var(--color-edify-muted)]" />
      </div>
      <p className="text-[13px] font-bold text-[var(--color-edify-text)]">{title}</p>
      {message && <p className="text-[12px] muted mt-1 max-w-sm mx-auto leading-snug">{message}</p>}
    </div>
  );
}

export function ErrorState({
  message = "Could not load data.",
  onRetry,
  at,
  compact = false,
}: {
  message?: string;
  onRetry?: () => void;
  /** Timestamp of the failed attempt. */
  at?: Date | string | number;
  compact?: boolean;
}) {
  const when = at ? new Date(at).toLocaleTimeString() : null;
  return (
    <div className={`text-center ${compact ? "py-6" : "py-12"}`}>
      <div className="mx-auto mb-3 grid place-items-center w-11 h-11 rounded-full bg-rose-50 border border-rose-200">
        <AlertTriangle size={20} className="text-rose-600" />
      </div>
      <p className="text-[13px] font-bold text-rose-700">{message}</p>
      {when && <p className="text-[11px] muted mt-0.5">Failed at {when}</p>}
      {onRetry && (
        <button onClick={onRetry} className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-edify-border)] px-3 py-1.5 text-[12px] font-bold hover:bg-slate-50">
          <RefreshCw size={13} /> Retry
        </button>
      )}
    </div>
  );
}

// Skeleton rows, not a spinner: the layout holds its shape while data
// streams in, so nothing jumps when rows replace the shimmer. `message`
// stays for screen readers.
const SKELETON_LINE_WIDTHS = ["w-3/5", "w-2/5", "w-1/2", "w-2/3"];

export function LoadingState({
  message = "Loading…",
  compact = false,
  rows,
}: {
  message?: string;
  compact?: boolean;
  /** Number of shimmer rows. Defaults to 2 (compact) / 3. */
  rows?: number;
}) {
  const count = rows ?? (compact ? 2 : 3);
  return (
    <div role="status" aria-label={message} className={compact ? "py-3 space-y-2.5" : "py-5 space-y-3"}>
      <span className="sr-only">{message}</span>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-9 w-9 rounded-lg shrink-0" />
          <div className="flex-1 min-w-0 space-y-1.5">
            <Skeleton className={`h-3 ${SKELETON_LINE_WIDTHS[i % SKELETON_LINE_WIDTHS.length]}`} />
            <Skeleton className={`h-2.5 ${SKELETON_LINE_WIDTHS[(i + 2) % SKELETON_LINE_WIDTHS.length]}`} />
          </div>
        </div>
      ))}
    </div>
  );
}
