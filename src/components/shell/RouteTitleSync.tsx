"use client";

// RouteTitleSync — auto-stamps the MobileTopBar title from the URL.
//
// Mounted once at the shell layout level. Watches `usePathname()`
// and writes the default title for that route into PageTitleContext.
// Per-page calls to `useSetPageTitle()` still win because they run
// after this default (later effect = later setState) — so a page
// can override the generic default with a richer one (entity name,
// period label, etc.) without coordinating.
//
// Why this lives at the layout rather than per page:
//   • One source of truth for every route's default title
//   • Adding a new page = no new wiring; the route map covers it
//   • Pages can stay focused on their content, not chrome wiring

import { usePathname } from "next/navigation";
import { useSetPageTitle } from "@/components/shell/PageTitleContext";
import { resolveRouteTitle } from "@/lib/route-titles";

export function RouteTitleSync() {
  const pathname = usePathname();
  const { title, dateLabel } = resolveRouteTitle(pathname);
  useSetPageTitle(title, dateLabel);
  return null;
}
