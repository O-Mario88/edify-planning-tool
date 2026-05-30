"use client";

import Link from "next/link";
import { AlertTriangle, RefreshCw, ArrowLeft } from "lucide-react";

// Shared error UI used by every per-segment error.tsx. Renders inside the
// (shell) layout's <main> slot, so it inherits the sidebar + page padding.
// Keeps the user calm — no raw stack trace.
export function SegmentError({
  error,
  reset,
  module,
  backHref = "/dashboard",
  backLabel = "Back to dashboard",
}: {
  error: Error & { digest?: string };
  reset: () => void;
  module: string;
  backHref?: string;
  backLabel?: string;
}) {
  return (
    <div className="px-4 sm:px-5 md:px-6 py-12 flex justify-center">
      <div className="card rounded-2xl p-6 max-w-[520px] w-full text-center">
        <span className="h-12 w-12 rounded-xl bg-rose-100 text-rose-700 grid place-items-center mx-auto mb-3">
          <AlertTriangle size={22} />
        </span>
        <h1 className="text-[16px] font-extrabold tracking-tight">
          Something went wrong while loading {module}
        </h1>
        <p className="text-body muted mt-1.5 leading-snug">
          The page hit an unexpected error. Try again, or head back to your dashboard. If the problem
          continues, share the reference code below with your administrator.
        </p>
        {error.digest && (
          <code className="inline-block mt-3 px-2 py-1 rounded bg-[var(--color-edify-soft)]/80 text-caption tabular text-[var(--color-edify-dark)]">
            ref: {error.digest}
          </code>
        )}
        <div className="mt-4 flex items-center justify-center gap-2">
          <button
            type="button"
            onClick={reset}
            className="btn btn-sm btn-primary"
            aria-label={`Retry loading ${module}`}
          >
            <RefreshCw size={11} />
            Retry
          </button>
          <Link href={backHref} className="btn btn-sm">
            <ArrowLeft size={11} />
            {backLabel}
          </Link>
        </div>
      </div>
    </div>
  );
}
