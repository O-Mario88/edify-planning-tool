"use client";

import Link from "next/link";
import { AlertOctagon, RefreshCw, Home } from "lucide-react";

// Global error boundary. Renders when a server component throws and the
// segment doesn't have its own error.tsx. Keeps the user calm and gives
// them an actionable escape.
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <section className="flex h-screen items-center justify-center px-6 py-10 bg-[var(--color-page)]">
      <div className="w-full max-w-[480px] rounded-3xl border border-rose-200 bg-white shadow-[0_24px_60px_rgba(244,63,94,0.12)] p-8 text-center">
        <div className="inline-flex h-14 w-14 rounded-2xl bg-rose-100 text-rose-600 items-center justify-center mb-3">
          <AlertOctagon size={26} />
        </div>
        <h1 className="text-[22px] font-extrabold tracking-tight">Something went wrong</h1>
        <p className="text-body muted mt-1.5 max-w-[320px] mx-auto">
          The page hit an unexpected error. Try again, or head home — your data is safe.
        </p>
        {error.digest && (
          <p className="text-caption muted mt-2 font-mono">Error ID: {error.digest}</p>
        )}
        <div className="mt-5 flex items-center justify-center gap-2">
          <button
            type="button"
            onClick={reset}
            className="h-10 px-3.5 rounded-xl bg-[var(--color-edify-primary)] text-white text-body font-semibold inline-flex items-center gap-1.5"
          >
            <RefreshCw size={13} />
            Try again
          </button>
          <Link
            href="/dashboard"
            className="h-10 px-3.5 rounded-xl border border-[var(--color-edify-border)] text-body font-semibold inline-flex items-center gap-1.5 hover:bg-[var(--color-edify-soft)]/60"
          >
            <Home size={13} />
            Go home
          </Link>
        </div>
      </div>
    </section>
  );
}
