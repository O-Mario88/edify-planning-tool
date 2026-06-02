import Image from "next/image";
import Link from "next/link";
import { cn } from "@/lib/utils";

// SidebarBrand — the ONE brand block for every sidebar in the app.
//
// Renders the white Edify logo (transparent background, no surrounding box)
// with "Planning and Monitoring Tool" beneath it. There is exactly one brand
// component: every role sidebar (CCEO, PL, CD, RVP, IA, Accountant, HR,
// Partner, Admin, …) and the mobile drawer render this — no per-role logo,
// no role-specific title in the brand area.
//
// The sidebar background is dark in all themes (light, dark, glass), so the
// logo stays white and the subtitle a soft white everywhere — never recoloured
// per theme. The logo asset is a pre-baked transparent white PNG
// (edify-logo-white.png), so no theme-dependent filters are needed.

const SUBTITLE = "Planning and Monitoring Tool";

export function SidebarBrand({
  href,
  /** Collapsed rail — show only the compact logo, hide the subtitle. */
  compact = false,
  className,
}: {
  href?: string;
  compact?: boolean;
  className?: string;
}) {
  const logo = (
    <Image
      src="/edify-logo-white.png"
      alt="Edify"
      width={351}
      height={143}
      priority
      sizes="120px"
      className={cn(
        "w-auto object-contain select-none shrink-0",
        compact ? "h-[22px]" : "h-[26px]",
      )}
    />
  );

  // items-start stops the flex column from stretching the logo to the full
  // sidebar width (which would distort the wordmark).
  const inner = (
    <span className="flex flex-col items-start gap-1.5 min-w-0">
      {logo}
      {!compact && (
        <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-white/65 leading-tight truncate">
          {SUBTITLE}
        </span>
      )}
    </span>
  );

  const wrapper = cn(
    "block px-5 pt-4 lg:pt-5 pb-4 border-b border-white/10 lg:border-b-0",
    className,
  );

  return href ? (
    <Link href={href} className={wrapper} aria-label={`Edify — ${SUBTITLE}`} title={compact ? SUBTITLE : undefined}>
      {inner}
    </Link>
  ) : (
    <div className={wrapper} title={compact ? SUBTITLE : undefined}>
      {inner}
    </div>
  );
}
