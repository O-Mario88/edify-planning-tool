"use client";

import type { ReactNode } from "react";

// A plain anchor that stops click propagation — for download / action links
// nested inside a clickable card or <Link>, so clicking them doesn't also
// trigger the parent's navigation. Owning the onClick in a client component
// keeps server-component pages from passing an event handler across the
// Server→Client boundary (which throws a runtime RSC error).
export function StopClickLink({
  href,
  className,
  ariaLabel,
  download,
  children,
}: {
  href: string;
  className?: string;
  ariaLabel?: string;
  download?: boolean;
  children: ReactNode;
}) {
  return (
    <a
      href={href}
      className={className}
      aria-label={ariaLabel}
      download={download}
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </a>
  );
}
