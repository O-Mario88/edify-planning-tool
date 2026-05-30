import Link from "next/link";
import { Compass, Home, ArrowLeft } from "lucide-react";

// Custom 404. Routed to whenever Next.js doesn't find a matching route.
// Keeps the brand chrome (no sidebar — the user may be unauth) and
// offers the two most useful escape hatches: home + sign in.
export default function NotFound() {
  return (
    <section className="flex h-screen items-center justify-center px-6 py-10 bg-[var(--color-page)]">
      <div className="w-full max-w-[480px] rounded-3xl border border-[var(--color-edify-border)] bg-white shadow-[0_24px_60px_rgba(15,23,32,0.10)] p-8 text-center">
        <div className="inline-flex h-14 w-14 rounded-2xl bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] items-center justify-center mb-3">
          <Compass size={26} />
        </div>
        <h1 className="text-[28px] font-extrabold tracking-tight">404</h1>
        <p className="text-[13px] muted mt-1.5 max-w-[320px] mx-auto">
          We couldn&apos;t find that page. Either the URL is off, or this surface hasn&apos;t shipped yet.
        </p>
        <div className="mt-5 flex items-center justify-center gap-2">
          <Link
            href="/dashboard"
            className="h-10 px-3.5 rounded-xl bg-[var(--color-edify-primary)] text-white text-body font-semibold inline-flex items-center gap-1.5"
          >
            <Home size={13} />
            Go to dashboard
          </Link>
          <Link
            href="/login"
            className="h-10 px-3.5 rounded-xl border border-[var(--color-edify-border)] text-body font-semibold inline-flex items-center gap-1.5 hover:bg-[var(--color-edify-soft)]/60"
          >
            <ArrowLeft size={13} />
            Sign in
          </Link>
        </div>
      </div>
    </section>
  );
}
