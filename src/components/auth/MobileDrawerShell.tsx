"use client";

import { useEffect, useState } from "react";
import { Menu, X } from "lucide-react";

// Drawer wrapper for the sidebar.
//
// Three viewport tiers (Desktop → Tablet → Mobile):
//   • <md   (mobile, <768px) — sidebar lives off-screen as a slide-in drawer
//     and the mobile branch of ResponsiveDashboard takes over.
//   • md to <lg (tablet, 768–1023px) — desktop branch shows, but the sidebar
//     stays drawered behind a hamburger so the dashboard content uses the
//     full viewport width.
//   • ≥lg   (desktop, ≥1024px) — sidebar pins persistently to the left edge.
//
// Each sidebar imports useMobileDrawer() to get { open, setOpen, asideClassName,
// hamburger, backdrop, closeButton } — drop them in and the responsive
// behavior is wired with no per-sidebar boilerplate.

export function useMobileDrawer() {
  const [open, setOpen] = useState(false);

  // Lock body scroll while the drawer is open
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const asideClassName = [
    "fixed inset-y-0 left-0 z-40 transform transition-transform duration-200",
    "lg:relative lg:translate-x-0 lg:transition-none",
    open ? "translate-x-0 shadow-2xl" : "-translate-x-full",
  ].join(" ");

  const hamburger = (
    <button
      type="button"
      aria-label="Open menu"
      onClick={() => setOpen(true)}
      className="lg:hidden fixed top-3 left-3 z-30 h-10 w-10 rounded-xl border border-white/15 bg-[var(--color-edify-deep)] text-white grid place-items-center shadow-lg"
    >
      <Menu size={18} />
    </button>
  );

  const backdrop = open ? (
    <div
      role="presentation"
      onClick={() => setOpen(false)}
      className="lg:hidden fixed inset-0 bg-black/55 backdrop-blur-sm z-40"
    />
  ) : null;

  const closeButton = (
    <button
      type="button"
      aria-label="Close menu"
      onClick={() => setOpen(false)}
      className="lg:hidden absolute top-3 right-3 z-10 h-7 w-7 rounded-md border border-white/15 grid place-items-center text-white/85"
    >
      <X size={14} />
    </button>
  );

  return { open, setOpen, asideClassName, hamburger, backdrop, closeButton };
}
