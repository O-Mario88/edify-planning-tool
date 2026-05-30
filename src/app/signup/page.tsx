import Link from "next/link";
import Image from "next/image";
import { SignupForm } from "@/components/auth/SignupForm";

// Self-service signup is enabled in this build through /api/auth/signup,
// which writes the new user into the runtime user store and immediately
// sets a session cookie. In production swap the runtime store for a real
// DB and you don't need to touch this page.
export default function SignupPage() {
  return (
    <section className="flex h-screen items-center justify-center px-6 py-10 bg-[var(--color-page)]">
      <div className="w-full max-w-[460px] rounded-3xl border border-[var(--color-edify-border)] bg-white shadow-[0_24px_60px_rgba(15,23,32,0.10)] p-8">
        <div className="flex flex-col items-center text-center">
          <div className="inline-flex items-center gap-2">
            <div className="w-10 h-10 rounded-xl bg-[var(--color-edify-soft)] grid place-items-center">
              <Image src="/edify-logo.png" alt="Edify" width={26} height={11} className="object-contain" style={{ width: "auto", height: "auto" }} priority />
            </div>
            <span className="text-[28px] font-extrabold tracking-tight text-[var(--color-edify-primary)]">edify</span>
          </div>
          <h1 className="text-[22px] font-extrabold tracking-tight mt-4 leading-none">
            Create your account
          </h1>
          <p className="text-body muted mt-1.5 max-w-[340px]">
            Create your Edify account. Country admins can also provision accounts on your behalf.
          </p>
        </div>

        <SignupForm />

        <div className="mt-6 text-body text-center muted">
          Already have an account?{" "}
          <Link href="/login" className="font-semibold text-[var(--color-edify-primary)] hover:underline">
            Sign in
          </Link>
        </div>
      </div>
    </section>
  );
}
