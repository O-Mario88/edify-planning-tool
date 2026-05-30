import { cn } from "@/lib/utils";

// ─────────────────── Skeleton system (3 tiers) ────────────────────
//
// Pick the right primitive for the scope you're loading:
//
//   ┌── Tier ─────┬── Component ──────────────────────┬── Use when ─────────────────────────────┐
//   │  atom       │  <Skeleton/>                      │  Composing a custom shimmer inside a    │
//   │             │  (this file)                      │  card. Width / height via className.    │
//   ├─────────────┼───────────────────────────────────┼─────────────────────────────────────────┤
//   │  chart      │  <ChartSkeleton variant=".."/>    │  Lazy-loaded chart fallback. Has        │
//   │             │  @/components/ui/ChartSkeleton    │  bar / line / donut / spark variants.   │
//   ├─────────────┼───────────────────────────────────┼─────────────────────────────────────────┤
//   │  page       │  <RouteSkeleton variant=".."/>    │  Default export from a route's          │
//   │             │  @/components/shell/RouteSkeleton │  loading.tsx. Renders header + KPIs +   │
//   │             │                                   │  body shimmer. Variants: default /      │
//   │             │                                   │  list / detail / form.                  │
//   └─────────────┴───────────────────────────────────┴─────────────────────────────────────────┘
//
// Atomic Skeleton is the building block — both higher tiers compose
// it internally. Do NOT add a 4th tier; if a new shape is needed,
// add it as a `variant` on RouteSkeleton or ChartSkeleton.

// Shimmering placeholder block. Width / height controlled by parent
// classes — `<Skeleton className="h-4 w-32" />`.
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn(
        "rounded-md bg-[var(--color-edify-soft)] animate-pulse",
        className,
      )}
    />
  );
}
