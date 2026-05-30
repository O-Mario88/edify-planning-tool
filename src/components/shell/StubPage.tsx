import { type ReactNode } from "react";
import { PageHeader } from "@/components/ui/PageHeader";

// Lightweight scaffold for "exists, but coming soon" routes.
//
// Delegates to the canonical <PageHeader>, so every StubPage inherits
// the premium full-width chrome (title, subtitle, back button, filter
// pills, desktop identity cluster) without re-rolling. Top-level role
// landing pages opt out via `noBack`.
export function StubPage({
  title,
  subtitle,
  children,
  noBack = false,
  backFallbackHref,
}: {
  title: string;
  subtitle: string;
  children?: ReactNode;
  /** Opt out of the leading back button. */
  noBack?: boolean;
  /** Structural parent to navigate to if browser history is empty. */
  backFallbackHref?: string;
}) {
  return (
    <>
      <PageHeader
        title={title}
        subtitle={subtitle}
        noBack={noBack}
        backFallbackHref={backFallbackHref}
      />
      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
        {children}
      </div>
    </>
  );
}
