"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import Image from "next/image";
import { Mail, ArrowLeft, CheckCircle2, ShieldCheck } from "lucide-react";
import { fetchJson } from "@/lib/csrf-client";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

// Forgot-password mock. Production wires this to the identity provider's
// reset endpoint; here we just simulate the success state so the rest of
// the app can link to it without dead-ending.
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!email.trim()) {
      setError("Enter the email address you sign in with.");
      return;
    }
    setSubmitting(true);
    try {
      await fetchJson("/api/auth/forgot-password", {
        body: { email: email.trim().toLowerCase() },
      });
      setSubmitting(false);
      setSent(true);
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
            Reset your password
          </h1>
          <p className="text-body muted mt-1.5 max-w-[320px]">
            Enter the email address tied to your account and we&apos;ll send you a one-time reset link.
          </p>
        </div>

        {!sent ? (
          <form onSubmit={handleSubmit} className="mt-6 space-y-3.5" noValidate>
            <Input
              id="reset-email"
              label="Email address"
              type="email"
              autoComplete="email"
              required
              inputSize="lg"
              leadingIcon={Mail}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@edify.org"
              error={error ?? undefined}
            />

            <Button
              type="submit"
              size="lg"
              fullWidth
              loading={submitting}
              Icon={ShieldCheck}
            >
              {submitting ? "Sending reset link…" : "Send reset link"}
            </Button>
          </form>
        ) : (
          <div className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-center">
            <CheckCircle2 size={28} className="text-emerald-600 mx-auto" />
            <h2 className="text-body-lg font-extrabold tracking-tight text-emerald-800 mt-2">
              Check your inbox
            </h2>
            <p className="text-[11.5px] text-emerald-700 mt-1 leading-snug">
              If an Edify account exists for <span className="font-semibold">{email}</span>,
              you&apos;ll receive a reset link within a few minutes.
            </p>
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
