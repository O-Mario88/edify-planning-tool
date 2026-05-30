import type { ReactNode } from "react";

// Wraps every /m/* page so they share the same phone-shaped frame.
// On desktop the content stays in a 480px column for parity with the
// reference shots; on mobile it fills the viewport.
export function MobileShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-[var(--color-page)] flex flex-col items-center">
      <div className="w-full max-w-[480px] flex-1 flex flex-col bg-[var(--color-page)] md:my-6 md:rounded-3xl md:overflow-hidden md:shadow-[0_24px_60px_rgba(15,23,32,0.08)]">
        {children}
      </div>
    </div>
  );
}
