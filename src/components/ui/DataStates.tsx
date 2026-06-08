"use client";

// Canonical empty / error / loading states for the backend-only migration.
// Every real surface uses these instead of inventing mock data:
//   • backend returned no records  → <EmptyState>
//   • backend request failed        → <ErrorState onRetry={…}>
//   • request in flight             → <LoadingState>
// "No backend data = empty state. Backend failure = error. Never fake data."

import { Inbox, AlertTriangle, Loader2, RefreshCw } from "lucide-react";

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

export function LoadingState({ message = "Loading…", compact = false }: { message?: string; compact?: boolean }) {
  return (
    <div className={`flex items-center justify-center gap-2 text-[12px] muted ${compact ? "py-6" : "py-12"}`}>
      <Loader2 size={15} className="animate-spin" /> {message}
    </div>
  );
}
