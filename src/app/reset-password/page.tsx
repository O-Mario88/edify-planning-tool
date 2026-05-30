"use client";

import { useState, type FormEvent, Suspense } from "react";
import Link from "next/link";
import Image from "next/image";
import { useSearchParams } from "next/navigation";
import {
  Lock,
  Eye,
  EyeOff,
  ArrowLeft,
  CheckCircle2,
  ShieldCheck,
} from "lucide-react";
import { fetchJson } from "@/lib/csrf-client";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

// Reset-password page. Mirrors forgot-password chrome (same card width,
// brand mark, footer link) so the two pages read as siblings. POSTs to
// /api/auth/reset-password with { token, password }; server validates the
// token and rotates the user's password.

function ResetPasswordInner() {
  const params = useSearchParams();
  const token = params.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    if (password.length < 6 || confirm.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    if (!token) {
      setError("Reset link is missing a token. Request a new link.");
      return;
    }

    setSubmitting(true);
    try {
      const { ok, data } = await fetchJson<{ message?: string }>(
        "/api/auth/reset-password",
        { body: { token, password } },
      );
      if (!ok) {
        setError(data?.message ?? "Reset failed. The link may be expired.");
        setSubmitting(false);
        return;
      }
      setSubmitting(false);
      setDone(true);
    } catch {
      setSubmitting(false);
      setError("Network error. Please try again.");
    }
  }

  return (
    <section className="flex h-screen items-center justify-center px-6 py-10 bg-[var(--color-page)]">
      <div className="w-full max-w-[440px] rounded-3xl border border-[var(--color-edify-border)] bg-white shadow-[0_24px_60px_rgba(15,23,32,0.10)] p-8">
        <div className="flex flex-col items-center text-center">
          <div className="inline-flex items-center gap-2">
            <div className="w-10 h-10 rounded-xl bg-[var(--color-edify-soft)] grid place-items-center">
              <Image src="/edify-logo.png" alt="Edify" width={26} height={11} className="object-contain" style={{ width: "auto", height: "auto" }} priority />
            </div>
            <span className="text-[28px] font-extrabold tracking-tight text-[var(--color-edify-primary)]">edify</span>
          </div>
          <h1 className="text-[22px] font-extrabold tracking-tight mt-4 leading-none">
            Set a new password
          </h1>
          <p className="text-body muted mt-1.5 max-w-[320px]">
            Enter and confirm your new password.
          </p>
        </div>

        {!done ? (
          <form onSubmit={handleSubmit} className="mt-6 space-y-3.5" noValidate>
            <Input
              id="new-password"
              label="New password"
              type={showPassword ? "text" : "password"}
              autoComplete="new-password"
              required
              minLength={6}
              inputSize="lg"
              leadingIcon={Lock}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 6 characters"
              trailingSlot={
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="h-7 w-7 grid place-items-center rounded-md text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/60"
                >
                  {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              }
            />

            <Input
              id="confirm-password"
              label="Confirm new password"
              type={showConfirm ? "text" : "password"}
              autoComplete="new-password"
              required
              minLength={6}
              inputSize="lg"
              leadingIcon={Lock}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="Re-enter password"
              error={error ?? undefined}
              trailingSlot={
                <button
                  type="button"
                  onClick={() => setShowConfirm((v) => !v)}
                  aria-label={showConfirm ? "Hide password" : "Show password"}
                  className="h-7 w-7 grid place-items-center rounded-md text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/60"
                >
                  {showConfirm ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              }
            />

            <Button
              type="submit"
              size="lg"
              fullWidth
              loading={submitting}
              Icon={ShieldCheck}
            >
              {submitting ? "Updating password…" : "Update password"}
            </Button>
          </form>
        ) : (
          <div className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-center">
            <CheckCircle2 size={28} className="text-emerald-600 mx-auto" />
            <h2 className="text-body-lg font-extrabold tracking-tight text-emerald-800 mt-2">
              Password updated
            </h2>
            <p className="text-[11.5px] text-emerald-700 mt-1 leading-snug">
              You can now sign in with your new password.
            </p>
            <Link
              href="/login"
              className="mt-3 inline-flex items-center gap-1.5 text-body font-semibold text-emerald-800 hover:underline"
            >
              <ArrowLeft size={12} />
              Back to sign in
            </Link>
          </div>
        )}

        <div className="mt-6 flex items-center justify-center text-body">
          <Link href="/login" className="inline-flex items-center gap-1.5 font-semibold text-[var(--color-edify-primary)] hover:underline">
            <ArrowLeft size={12} />
            Back to sign in
          </Link>
        </div>
      </div>
    </section>
  );
}

export default function ResetPasswordPage() {
  // useSearchParams must be used inside Suspense in app router to avoid
  // prerender bailout on the static export. Wrap so the entire form
  // suspends cleanly during build.
  return (
    <Suspense fallback={null}>
      <ResetPasswordInner />
    </Suspense>
  );
}
