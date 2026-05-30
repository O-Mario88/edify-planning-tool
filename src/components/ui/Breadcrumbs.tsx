"use client";

// Breadcrumbs — auto-built from the current path + route-titles map.
//
// On every page with path depth > 1, render breadcrumb chips above
// the title: `Partners › Amref Health Africa`. This anchors the user
// on deep / detail routes where the back button alone doesn't make
// the hierarchy obvious.
//
// Self-resolving: walks the path segments, resolves each prefix
// against `resolveRouteTitle`, and renders the path leading up to
// the current page. The current page itself is rendered as plain
// text (it's the "you are here" — not a link).
//
// Pages can override the trailing crumb's label by passing
// `trailingLabel` (e.g. an entity name resolved server-side). That's
// the multi-billion polish — "Schools › St. Mary's Primary School"
// reads infinitely better than "Schools › School".

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight, Home } from "lucide-react";
import { resolveRouteTitle } from "@/lib/route-titles";

export type BreadcrumbsProps = {
  /** Override the final crumb's label (typically with the actual
   *  entity name, resolved on the server). */
  trailingLabel?: string;
  className?: string;
};

export function Breadcrumbs({ trailingLabel, className }: BreadcrumbsProps) {
  const pathname = usePathname();
  const crumbs   = buildCrumbs(pathname, trailingLabel);
  if (crumbs.length < 2) return null;

  return (
    <nav aria-label="Breadcrumb" className={className}>
      <ol className="flex items-center gap-1 text-[11.5px] text-[var(--color-edify-muted)] flex-wrap">
        {crumbs.map((c, i) => {
          const isLast = i === crumbs.length - 1;
          return (
            <li key={`${c.href}-${i}`} className="inline-flex items-center gap-1">
              {i > 0 && <ChevronRight size={11} className="opacity-50 shrink-0" />}
              {isLast ? (
                <span className="font-semibold text-[#0f1720] truncate max-w-[240px]">{c.label}</span>
              ) : (
                <Link
                  href={c.href}
                  className="hover:text-[#0f1720] hover:underline truncate max-w-[180px] inline-flex items-center gap-1"
                >
                  {i === 0 && <Home size={11} className="opacity-70" />}
                  {c.label}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

// ────────── Path → crumbs ──────────

type Crumb = { label: string; href: string };

function buildCrumbs(pathname: string, trailingLabel?: string): Crumb[] {
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length === 0) return [];

  const crumbs: Crumb[] = [];
  let acc = "";
  for (const seg of segments) {
    acc += "/" + seg;
    const resolved = resolveRouteTitle(acc);
    // Skip generic "Edify" placeholder — that's the no-match fallback.
    if (resolved.title === "Edify") continue;
    crumbs.push({ label: resolved.title, href: acc });
  }

  // Override the final crumb with a richer label if provided.
  if (trailingLabel && crumbs.length > 0) {
    crumbs[crumbs.length - 1] = {
      ...crumbs[crumbs.length - 1],
      label: trailingLabel,
    };
  }

  return crumbs;
}
