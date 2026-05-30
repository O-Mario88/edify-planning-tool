import Link from "next/link";
import { CalendarRange, ClipboardList, User } from "lucide-react";
import { cn } from "@/lib/utils";

// Three-pill cross-link strip for the plans family.
//
// The plans family is three functionally distinct surfaces — collapsing
// them harms UX. This strip makes them feel paired by giving each page
// the same one-line nav at the top:
//
//   /planning  → the Planning Tool (calendar / scheduling — where you DO)
//   /my-plan   → my scoped plan (role-aware current plan — where you SEE)
//   /plans     → the plan list (all items, with new + per-item drill-down)
//
// Pass `current` to highlight the active surface. The two non-current
// pills become discoverability shortcuts to the others.

type PlanSurface = "planning" | "my-plan" | "plans";

const SURFACES: Array<{
  key: PlanSurface;
  href: string;
  label: string;
  Icon: typeof CalendarRange;
}> = [
  { key: "planning", href: "/planning", label: "Planning Tool", Icon: CalendarRange },
  { key: "my-plan",  href: "/my-plan",  label: "My Plan",       Icon: User },
  { key: "plans",    href: "/plans",    label: "All Plans",     Icon: ClipboardList },
];

export function PlansFamilyNav({
  current,
  className,
}: {
  current: PlanSurface;
  /** Override the default padding/spacing when this nav is rendered
   * inside an already-padded container (e.g. inline with the planning
   * boards rather than as a top-of-page strip). */
  className?: string;
}) {
  return (
    <nav
      aria-label="Plans family"
      className={cn("flex items-center gap-1", className ?? "px-4 sm:px-5 md:px-6 pt-3")}
    >
      {SURFACES.map((s) => {
        const active = s.key === current;
        return (
          <Link
            key={s.key}
            href={s.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[11.5px] font-semibold transition-colors",
              active
                ? "bg-[var(--color-edify-primary)] text-white"
                : "bg-[var(--color-edify-soft)]/60 text-[var(--color-edify-dark)] hover:bg-[var(--color-edify-soft)]",
            )}
          >
            <s.Icon size={12} />
            {s.label}
          </Link>
        );
      })}
    </nav>
  );
}
