"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { LogOut, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchJson } from "@/lib/csrf-client";

// Reusable sign-out trigger.
// `variant="dark"`  → inside dark sidebars (white text on translucent bg)
// `variant="light"` → inside white headers / dropdowns (Edify primary text)
//
// Calls /api/auth/logout to clear the server session, then routes the user
// back to /login. Falls through to plain redirect if the API isn't reachable.
export function SignOutButton({
  variant = "dark",
  fullWidth = true,
  className,
}: {
  variant?: "dark" | "light";
  fullWidth?: boolean;
  className?: string;
}) {
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);

  async function handleSignOut() {
    if (signingOut) return;
    setSigningOut(true);
    try {
      await fetchJson("/api/auth/logout");
    } catch {
      // ignore — we still want to redirect locally
    }
    router.push("/login");
  }

  const dark =
    "border border-white/15 text-white/90 hover:bg-white/10 bg-white/[.04]";
  const light =
    "border border-[var(--color-edify-border)] text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60 bg-white";

  return (
    <button
      type="button"
      onClick={handleSignOut}
      disabled={signingOut}
      className={cn(
        "h-8 rounded-md text-[12px] font-semibold inline-flex items-center justify-center gap-1.5 transition-colors",
        fullWidth ? "w-full" : "px-3",
        variant === "dark" ? dark : light,
        signingOut && "opacity-70 cursor-not-allowed",
        className,
      )}
    >
      {signingOut ? <Loader2 size={11} className="animate-spin" /> : <LogOut size={11} />}
      {signingOut ? "Signing out…" : "Sign Out"}
    </button>
  );
}
