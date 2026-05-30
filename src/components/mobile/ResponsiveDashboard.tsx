"use client";

import { useEffect, useState, type ReactNode } from "react";

// Canonical mobile/desktop abstraction.
//
// New pages do NOT create a separate /m/* route to support mobile. They
// render <ResponsiveDashboard desktop={…} mobile={…}> at the same URL
// the desktop user visits. The legacy /m/* tree is a redirect catch-all
// for old bookmarks and is being phased out — do not extend it.
// See src/app/(shell)/CONVENTIONS.md → Rule 5.
//
// Renders only the branch that matches the current viewport. Saves the
// SSR + hydration cost of building both trees (and the Recharts
// `width(-1)` warnings that come from rendering charts into hidden
// containers).
//
// First paint is the desktop branch (matches `@media (min-width: 768px)`
// SSR — most marketing browsers + bots). Once the client mounts we read
// the actual viewport with matchMedia and switch.
export function ResponsiveDashboard({
  desktop,
  mobile,
}: {
  desktop: ReactNode;
  mobile: ReactNode;
}) {
  const [view, setView] = useState<"desktop" | "mobile">("desktop");

  useEffect(() => {
    const mql = window.matchMedia("(max-width: 767.98px)");
    const apply = () => setView(mql.matches ? "mobile" : "desktop");
    apply();
    mql.addEventListener("change", apply);
    return () => mql.removeEventListener("change", apply);
  }, []);

  // When a page hands the SAME tree to both props (Director, CPL — the
  // child components already handle their own breakpoints), render it
  // once. No per-viewport swap, no post-mount remount, no duplicated DOM.
  if (desktop === mobile) return <>{desktop}</>;

  return view === "mobile" ? <>{mobile}</> : <>{desktop}</>;
}
