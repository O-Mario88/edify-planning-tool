import Link from "next/link";
import { ArrowUpRight, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

// DashboardToolsFooter — the canonical "page tools" rail.
//
// Replaces every role's hand-rolled 6-tile "Quick Actions" card. The
// old grid was visual noise pretending to be a primary action surface;
// most tiles duplicated affordances that already exist higher on the
// page (KPI cards, inboxes, hero CTAs). This rail demotes utilities to
// the footer-chip tier so the page's strategic content reads first.
//
// Use it for genuine "no other home" utilities — Upload, Export,
// Generate Report, Activity Log, Settings. If the action exists in
// context elsewhere (verify, approve, view issues), don't add it here.
//
//   <DashboardToolsFooter
//     items={[
//       { label: "Upload data", href: "/data-intake/upload", icon: Upload },
//       { label: "Generate report", href: "/reports", icon: FileText },
//     ]}
//   />

export type DashboardToolItem = {
  key?:   string;
  label:  string;
  href:   string;
  icon:   LucideIcon;
  badge?: number;
};

export function DashboardToolsFooter({
  items,
  label = "Tools",
  className,
}: {
  items:      DashboardToolItem[];
  /** Eyebrow prefix; default is "Tools" but can be e.g. "Page tools",
   *  "Quick utilities", "Admin" for context-specific framing. */
  label?:     string;
  className?: string;
}) {
  if (items.length === 0) return null;
  return (
    <section
      aria-label={label}
      className={cn("flex flex-wrap items-center gap-2 pt-2", className)}
    >
      <span className="eyebrow mr-1">{label}</span>
      {items.map((a) => {
        const Icon = a.icon;
        return (
          <Link
            key={a.key ?? a.label}
            href={a.href}
            className={cn(
              "group inline-flex items-center gap-1.5 h-8 px-3 rounded-full",
              "border border-[var(--color-edify-border)] bg-[var(--surface-1)]",
              "t-caption font-bold text-[var(--text-primary)]",
              "hover:bg-[var(--surface-hover)] hover:border-[var(--border-strong)] transition-colors",
              "relative",
            )}
          >
            <Icon size={11} className="text-[var(--text-secondary)] group-hover:text-[var(--color-edify-primary)]" />
            {a.label}
            <ArrowUpRight size={10} className="text-[var(--text-muted)] opacity-0 -ml-0.5 group-hover:opacity-100 group-hover:ml-0 transition-all" />
            {a.badge != null && a.badge > 0 ? (
              <span className="absolute -top-1.5 -right-1.5 bg-[var(--color-danger)] text-white text-[9px] font-bold rounded-full px-1.5 py-0.5 leading-none">
                {a.badge}
              </span>
            ) : null}
          </Link>
        );
      })}
    </section>
  );
}
