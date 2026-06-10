"use client";

// HeaderChrome — the canonical right-edge header cluster (global search
// affordance + message/notification bells) for headers that can't mount
// the full <PageHeader> (e.g. the server-rendered EntityDetail scaffold).
// Mirrors PageHeader's fallback search button exactly so detail pages and
// index pages read identically. Desktop-only by convention: pass
// `className="hidden lg:flex"` — on mobile/tablet the dark MobileTopBar
// already carries the bells.

import { Search } from "lucide-react";
import { IdentityCluster } from "@/components/shell/IdentityCluster";
import { cn } from "@/lib/utils";

export function HeaderChrome({ className }: { className?: string }) {
  return (
    <div className={cn("items-center gap-2 shrink-0", className)}>
      <button
        type="button"
        aria-label="Open command palette"
        onClick={() => window.dispatchEvent(new CustomEvent("edify:open-command-palette"))}
        className="relative h-10 w-[220px] pl-9 pr-12 rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-card)] text-body text-left text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30 shadow-[0_1px_2px_rgba(15,23,32,0.04)] transition-colors flex items-center"
      >
        <Search
          size={13}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)] pointer-events-none"
        />
        Search everything…
        <kbd className="absolute right-2 top-1/2 -translate-y-1/2 hidden md:inline-flex items-center gap-0.5 h-5 px-1.5 rounded border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)] text-[10px] font-bold text-[var(--color-edify-muted)]">
          ⌘K
        </kbd>
      </button>
      <IdentityCluster variant="default" />
    </div>
  );
}
