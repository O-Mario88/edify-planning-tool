import { type ReactNode } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { cn } from "@/lib/utils";

// Desktop-frame wrapper for mobile views that don't have a bespoke
// desktop variant. Renders the canonical <PageHeader> and centres the
// mobile-style content in a wider, desktop-friendly column.
//
// The (shell) route-group layout already mounts <EdifySidebarServer />
// and the <main> region once per page; this wrapper just adds chrome +
// gutters. Use ResponsiveDashboard at the page level so the real
// mobile shell still renders on phones; this shell only kicks in on
// tablet/desktop.

export function MobileViewDesktopShell({
  title,
  subtitle,
  asideRight,
  children,
  maxWidth = "lg",
}: {
  title:       string;
  subtitle?:   string;
  asideRight?: ReactNode;
  children:    ReactNode;
  maxWidth?:   "md" | "lg" | "xl";
}) {
  const maxClass =
    maxWidth === "md" ? "max-w-3xl" :
    maxWidth === "lg" ? "max-w-5xl" :
                        "max-w-7xl";
  return (
    <>
      <PageHeader title={title} subtitle={subtitle} />
      <div className={cn("mx-auto w-full px-4 sm:px-5 md:px-6 pb-10 md:pb-6", maxClass)}>
        {asideRight ? (
          <div className="grid grid-cols-12 gap-4 items-start">
            <div className="col-span-12 lg:col-span-8">{children}</div>
            <aside className="col-span-12 lg:col-span-4 lg:sticky lg:top-4 space-y-3">
              {asideRight}
            </aside>
          </div>
        ) : (
          children
        )}
      </div>
    </>
  );
}
