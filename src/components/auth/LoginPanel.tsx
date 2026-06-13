"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import {
  Mail,
  Lock,
  Eye,
  EyeOff,
  LogIn,
  ShieldCheck,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchJson } from "@/lib/csrf-client";
import { DEMO_USERS, ROLE_REDIRECT } from "@/lib/auth-public";

// ROLE_REDIRECT used to live here — it now lives in lib/auth.ts. We import
// only DEMO_USERS (the client-safe view of the user store) so this file
// stays small and the canonical role→route map stays server-side.

export function LoginPanel() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!email || !password) {
      setError("Invalid email or password.");
      return;
    }
    setSubmitting(true);
    // Server-backed: POST /api/auth/login. The server validates against the
    // user store and sets HTTP-only session cookies that JS cannot read.
    // The client no longer touches document.cookie directly.
    try {
      const { ok, data } = await fetchJson<{ ok?: boolean; message?: string; redirect?: string }>(
        "/api/auth/login",
        { body: { email: email.trim().toLowerCase(), password, remember } },
      );
      if (!ok || !data?.ok) {
        setSubmitting(false);
        setError(data?.message ?? "Invalid email or password.");
        return;
      }
      const fallback = ROLE_REDIRECT[DEMO_USERS[email.trim().toLowerCase()]?.role ?? "CCEO"];
      router.push(data.redirect ?? fallback);
    } catch {
      setSubmitting(false);
      setError("Network error. Please try again.");
    }
  }

  function handleGoogleSignIn() {
    setError(null);
    // Production: window.location.href = "/api/auth/google";
    setError("Google sign-in is not enabled in this environment.");
  }

  return (
    <section className="flex h-screen items-center justify-center px-6 py-10 bg-[var(--color-page)]">
      <div className="w-full max-w-[440px] rounded-3xl border border-[var(--color-edify-border)] bg-white shadow-[0_24px_60px_rgba(15,23,32,0.10)] p-8">
        {/* Brand — logo only (the logo IS the edify wordmark). On this white
            panel the full-colour logo is used. */}
        <div className="flex flex-col items-center text-center">
          <Image src="/edify-logo.png" alt="Edify" width={77} height={32} className="object-contain" priority />
          <h1 className="text-[26px] font-extrabold tracking-tight mt-4 leading-none">Sign in</h1>
          <p className="text-body muted mt-1.5">Access your Edify account</p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="mt-6 space-y-3.5" noValidate>
          <div>
            <label htmlFor="login-email" className="text-[12px] font-bold text-[var(--color-edify-text)]">
              Email address
            </label>
            <div className="relative mt-1">
              <Mail
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)] pointer-events-none"
              />
              <input
                id="login-email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Enter your email address"
                className="w-full h-11 pl-9 pr-3 rounded-xl border border-[var(--color-edify-border)] bg-white text-[13.5px] placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
              />
            </div>
          </div>

          <div>
            <label htmlFor="login-password" className="text-[12px] font-bold text-[var(--color-edify-text)]">
              Password
            </label>
            <div className="relative mt-1">
              <Lock
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)] pointer-events-none"
              />
              <input
                id="login-password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                className="w-full h-11 pl-9 pr-10 rounded-xl border border-[var(--color-edify-border)] bg-white text-[13.5px] placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                className="absolute right-2 top-1/2 -translate-y-1/2 h-7 w-7 rounded-md grid place-items-center text-[var(--color-edify-muted)] hover:text-[var(--color-edify-primary)]"
              >
                {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>

          {/* Remember + forgot */}
          <div className="flex items-center justify-between text-body">
            <label className="inline-flex items-center gap-2 cursor-pointer select-none">
              <span
                className={cn(
                  "relative w-4 h-4 rounded-[4px] border grid place-items-center transition-colors",
                  remember
                    ? "bg-[var(--color-edify-primary)] border-[var(--color-edify-primary)]"
                    : "bg-white border-[var(--color-edify-border)]",
                )}
              >
                {remember && (
                  <svg viewBox="0 0 16 16" className="w-3 h-3 text-white" fill="none" stroke="currentColor" strokeWidth={3}>
                    <path d="M3 8l3.5 3.5L13 5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </span>
              <input
                type="checkbox"
                className="sr-only"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
              />
              Remember me
            </label>
            <a href="/forgot-password" className="font-semibold text-[var(--color-edify-primary)] hover:underline">
              Forgot password?
            </a>
          </div>

          {error && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
              {error}
            </div>
          )}

          {/* Primary submit */}
          <button
            type="submit"
            disabled={submitting}
            className={cn(
              "w-full h-11 rounded-xl bg-[#2d4f66] hover:bg-[#23404f] text-white font-bold text-[14.5px] inline-flex items-center justify-center gap-2 transition-colors",
              submitting && "opacity-80 cursor-not-allowed",
            )}
            style={{ color: "#ffffff" }}
          >
            {submitting ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                Signing in…
              </>
            ) : (
              <>
                <LogIn size={14} />
                Sign in to Edify
              </>
            )}
          </button>

          {/* Divider */}
          <div className="flex items-center gap-3 my-1">
            <span className="flex-1 h-px bg-[var(--color-edify-border)]" />
            <span className="text-[11px] muted font-semibold">or</span>
            <span className="flex-1 h-px bg-[var(--color-edify-border)]" />
          </div>

          {/* Google */}
          <button
            type="button"
            onClick={handleGoogleSignIn}
            className="w-full h-11 rounded-xl border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/60 text-[13.5px] font-bold inline-flex items-center justify-center gap-2"
          >
            <GoogleG />
            Sign in with Google
          </button>

          {/* Secure access notice */}
          <div className="mt-3 rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/60 px-3 py-2.5 flex items-start gap-2.5">
            <span className="w-7 h-7 rounded-md grid place-items-center bg-white text-[var(--color-edify-primary)] border border-[var(--color-edify-border)] shrink-0">
              <ShieldCheck size={14} />
            </span>
            <div className="leading-tight">
              <div className="text-body font-bold">Secure access</div>
              <div className="text-[11px] muted mt-0.5">
                Your data is encrypted and protected by enterprise-grade security.
              </div>
            </div>
          </div>
        </form>

        {/* Footer note */}
        <div className="mt-5 flex items-start gap-2 text-[11px] muted">
          <ShieldCheck size={11} className="mt-0.5 text-[var(--color-edify-primary)]" />
          <span>Protected access for country teams, CEOs, finance, and leadership.</span>
        </div>
      </div>
    </section>
  );
}

function GoogleG() {
  return (
    <svg viewBox="0 0 48 48" width="16" height="16" aria-hidden>
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.6 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.7 1.1 7.8 2.9l5.7-5.7C33.9 6 29.2 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20c11 0 19.5-7.9 19.5-20 0-1.2-.1-2.3-.4-3.5z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.8 16.4 19 13 24 13c3 0 5.7 1.1 7.8 2.9l5.7-5.7C33.9 6 29.2 4 24 4 16.5 4 9.9 8.4 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.1 0 9.7-1.9 13.2-5l-6.1-5.2C29.3 35.6 26.8 36.5 24 36.5c-5.3 0-9.7-3.4-11.3-8.1l-6.5 5C9.6 39.6 16.3 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.2 4.3-4.1 5.8l6.1 5.2C40.7 35.7 44 30.3 44 24c0-1.2-.1-2.3-.4-3.5z" />
    </svg>
  );
}
