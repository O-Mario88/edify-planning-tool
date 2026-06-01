"use client";

// CollapsibleCard — a card surface whose body collapses to just its header.
//
// The lever for de-crowding dashboards: a heavy section (queue, table, board)
// folds to a single summary row, so the page reads as a calm stack of titles
// the user expands on demand instead of a long uniform scroll. Premium feel:
// the `meta` slot (counts / status) stays visible when collapsed, so a folded
// card still communicates at a glance.
//
// Drop-in for the common `<section className="card"><SectionHeader/>{body}</section>`
// pattern — it takes the same header props (tier/eyebrow/title/description/icon/meta)
// and renders the SectionHeader visuals, with the title row as the toggle.
//
// State persists per `id` in localStorage, so a card the user folded stays
// folded across navigations. Height animates via the grid-rows 0fr→1fr trick
// (no JS measurement); respects prefers-reduced-motion.

import { useEffect, useId, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

type Tier = "strategic" | "operational" | "micro";

const TIER_CLASS: Record<Tier, string> = {
  strategic: "section-h-strategic",
  operational: "section-h-operational",
  micro: "section-h-micro",
};

const STORAGE_PREFIX = "edify:collapse:";

export function CollapsibleCard({
  id,
  tier = "operational",
  eyebrow,
  title,
  description,
  icon,
  meta,
  defaultCollapsed = false,
  /** "card" wraps the section in card chrome (a standalone panel). "bare" is
   *  a chrome-less grouping lane — just the header + collapsible content, for
   *  dashboard sections that hold their own grid of cards. */
  surface = "card",
  className,
  bodyClassName,
  as: As = "h2",
  children,
}: {
  /** Stable id — persists collapsed state across navigations. Required so two
   *  cards don't share state; omit only for a transient, non-persisted card. */
  id?: string;
  tier?: Tier;
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  /** Right-aligned summary (count / status). Stays visible when collapsed. */
  meta?: ReactNode;
  defaultCollapsed?: boolean;
  surface?: "card" | "bare";
  className?: string;
  bodyClassName?: string;
  as?: "h1" | "h2" | "h3";
  children: ReactNode;
}) {
  // SSR renders with the default so server and first client render agree;
  // localStorage is read after mount (a folded card may flash open once).
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const [hydrated, setHydrated] = useState(false);
  const reactId = useId();
  const bodyId = `collapsible-${(id ?? reactId).replace(/[^a-zA-Z0-9_-]/g, "-")}`;

  useEffect(() => {
    if (!id) {
      setHydrated(true);
      return;
    }
    try {
      const stored = window.localStorage.getItem(STORAGE_PREFIX + id);
      if (stored !== null) setCollapsed(stored === "1");
    } catch {
      // localStorage unavailable (private mode / SSR edge) — keep default.
    }
    setHydrated(true);
  }, [id]);

  function toggle() {
    setCollapsed((prev) => {
      const next = !prev;
      if (id) {
        try {
          window.localStorage.setItem(STORAGE_PREFIX + id, next ? "1" : "0");
        } catch {
          /* ignore */
        }
      }
      return next;
    });
  }

  const open = !collapsed;
  const isCard = surface === "card";

  return (
    <section
      className={cn(isCard && "card p-3.5", className)}
      data-collapsed={collapsed}
    >
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-controls={bodyId}
        className={cn(
          "group/collapse w-full flex items-start gap-3 text-left rounded-lg",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-edify-primary)]/30",
        )}
      >
        {icon ? <span className="shrink-0 mt-0.5">{icon}</span> : null}
        <div className="flex-1 min-w-0">
          {eyebrow ? <p className="eyebrow mb-1">{eyebrow}</p> : null}
          <As className={TIER_CLASS[tier]}>{title}</As>
          {description ? (
            <p className="t-body text-secondary mt-1">{description}</p>
          ) : null}
        </div>
        {meta ? <span className="shrink-0 self-center mr-1">{meta}</span> : null}
        <ChevronDown
          size={18}
          aria-hidden
          className={cn(
            "shrink-0 self-center text-[var(--color-edify-muted)]",
            "transition-transform duration-300 ease-out motion-reduce:transition-none",
            open ? "rotate-0" : "-rotate-90",
          )}
        />
      </button>

      <div
        id={bodyId}
        className={cn(
          "grid transition-[grid-template-rows] duration-300 ease-out motion-reduce:transition-none",
          // Hide content fully when collapsed (and after mount, to avoid the
          // SSR-default flash) so collapsed cards take no vertical space.
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
          hydrated ? "" : "grid-rows-[1fr]",
        )}
      >
        <div
          className={cn(
            "overflow-hidden",
            // Pad the body open only when expanded so a collapsed section folds
            // flush to its header with no leftover gap. Card surfaces get a
            // little more breathing room than bare grouping lanes.
            open ? (isCard ? "mt-4" : "mt-3") : "mt-0",
            bodyClassName,
          )}
          aria-hidden={!open}
        >
          {children}
        </div>
      </div>
    </section>
  );
}
