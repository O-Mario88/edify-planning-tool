"use client";

import Link from "next/link";
import { AlertOctagon, Home, RefreshCw } from "lucide-react";

// RouteError — per-route error boundary card.
//
// Rendered when a route segment throws. Sits inside the existing shell
// (sidebar / mobile top bar / role bottom nav stay mounted) so the
// user can still navigate away — unlike the global error boundary
// which replaces the whole screen.
//
// The page-level `error.tsx` is a client component (Next.js
// requirement for error boundaries). This shared primitive accepts
// the standard `error` + `reset` props and keeps the visual treatment
// consistent everywhere.

export function RouteError({
  error,
  reset,
  /** Where the "Go home" button points. Defaults to /dashboard so any
   *  signed-in user lands somewhere they can act. */
  homeHref = "/dashboard",
  /** Override the title for routes that need a specific message
   *  ("Couldn't load this school", "Couldn't load this thread"). */
  title = "Something went wrong",
  /** Override the body copy. */
  subtitle = "This page hit an unexpected error. Try again, or head home — your data is safe.",
}: {
  error:     Error & { digest?: string };
  reset:     () => void;
  homeHref?: string;
  title?:    string;
  subtitle?: string;
}) {
  return (
    <section className="px-4 sm:px-5 md:px-6 py-10 lg:py-16">
      <div className="mx-auto w-full max-w-[520px] rounded-3xl border border-rose-200 bg-white shadow-[0_24px_60px_rgba(244,63,94,0.08)] p-7 lg:p-8 text-center">
        <div className="inline-flex h-12 w-12 rounded-2xl bg-rose-100 text-rose-600 items-center justify-center mb-3">
          <AlertOctagon size={22} />
        </div>
        <h1 className="text-[18px] lg:text-[20px] font-extrabold tracking-tight">{title}</h1>
        <p className="text-body muted mt-1.5 max-w-[360px] mx-auto leading-snug">
          {subtitle}
        </p>
        {error.digest && (
          <p className="text-caption muted mt-2 font-mono">Error ID: {error.digest}</p>
        )}
        <div className="mt-5 flex items-center justify-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={reset}
            className="h-10 px-3.5 rounded-xl bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-body font-extrabold inline-flex items-center gap-1.5"
          >
            <RefreshCw size={13} />
            Try again
          </button>
          <Link
            href={homeHref}
            className="h-10 px-3.5 rounded-xl border border-[var(--color-edify-border)] bg-white text-body font-semibold inline-flex items-center gap-1.5 hover:bg-[var(--color-edify-soft)]/60"
          >
            <Home size={13} />
            Go home
          </Link>
        </div>
      </div>
    </section>
  );
}
