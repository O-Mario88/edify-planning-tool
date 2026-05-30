"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  Mail,
  User,
  Lock,
  Eye,
  EyeOff,
  ShieldCheck,
  Loader2,
  type LucideIcon,
} from "lucide-react";
import { fetchJson } from "@/lib/csrf-client";

// Client-side signup form. POSTs to /api/auth/signup, which writes a new
// user into the runtime store, hashes the password (placeholder), and
// sets the HTTP-only session cookies — so on success we just route to
// the returned dashboard URL.
export function SignupForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!name.trim() || !email.trim() || password.length < 6) {
      setError("Please enter your name, a valid email, and a password of at least 6 characters.");
      return;
    }
    setSubmitting(true);
    try {
      const { ok, data } = await fetchJson<{ ok?: boolean; message?: string; redirect?: string }>(
        "/api/auth/signup",
        { body: { name: name.trim(), email: email.trim().toLowerCase(), password } },
      );
      if (!ok || !data?.ok) {
        setSubmitting(false);
        setError(data?.message ?? "We couldn't create your account.");
        return;
      }
      router.push(data.redirect ?? "/dashboard");
    } catch {
      setSubmitting(false);
      setError("Network error. Please try again.");
    }
  }

  return (
    <form className="mt-6 space-y-3.5" onSubmit={onSubmit} noValidate>
      <Field id="name" label="Full name" Icon={User} placeholder="Jane Adwong" value={name} onChange={setName} autoComplete="name" />
      <Field id="email" label="Work email" Icon={Mail} placeholder="jane@partner.org" type="email" value={email} onChange={setEmail} autoComplete="email" />

      <div>
        <label htmlFor="signup-pwd" className="text-[12px] font-bold">Password</label>
        <div className="relative mt-1">
          <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)] pointer-events-none" />
          <input
            id="signup-pwd"
            type={showPwd ? "text" : "password"}
            required
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="At least 6 characters"
            autoComplete="new-password"
            className="w-full h-11 pl-9 pr-10 rounded-xl border border-[var(--color-edify-border)] bg-white text-[13.5px] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          />
          <button
            type="button"
            onClick={() => setShowPwd((v) => !v)}
            aria-label={showPwd ? "Hide password" : "Show password"}
            className="absolute right-2 top-1/2 -translate-y-1/2 h-7 w-7 rounded-md grid place-items-center text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/60"
          >
            {showPwd ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="rounded-md border border-rose-200 bg-rose-50 text-rose-700 px-3 py-2 text-[12px]">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="w-full h-11 rounded-xl bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white font-bold text-body-lg inline-flex items-center justify-center gap-2 disabled:opacity-60"
      >
        {submitting ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
        {submitting ? "Creating account…" : "Create account"}
      </button>
    </form>
  );
}

function Field({
  id,
  label,
  Icon,
  placeholder,
  type = "text",
  value,
  onChange,
  autoComplete,
}: {
  id: string;
  label: string;
  Icon: LucideIcon;
  placeholder: string;
  type?: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete?: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="text-[12px] font-bold">{label}</label>
      <div className="relative mt-1">
        <Icon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)] pointer-events-none" />
        <input
          id={id}
          type={type}
          required
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          autoComplete={autoComplete}
          className="w-full h-11 pl-9 pr-3 rounded-xl border border-[var(--color-edify-border)] bg-white text-[13.5px] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
        />
      </div>
    </div>
  );
}
