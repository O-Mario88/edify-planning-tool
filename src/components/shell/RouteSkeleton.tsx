import { Skeleton } from "@/components/ui/Skeleton";

// RouteSkeleton — per-route loading placeholder.
//
// Used as the default for every page.tsx that doesn't ship its own
// loading.tsx. Renders inside the existing shell (sidebar / mobile top
// bar / role bottom nav stay mounted) so the user sees the right
// frame immediately — only the page body shimmers.
//
// Shape:
//   • Header bar (title + subtitle)
//   • 4-tile KPI strip
//   • Two-column body (8/4) — a wide content card and a smaller side
//     card. Matches the most common layout in this app, so the
//     shimmer roughly previews the real layout.
//
// `variant` lets specific routes pick a tighter shape:
//   • "default"   — header + KPIs + 8/4 body
//   • "list"      — header + 6-row list shimmer
//   • "detail"    — header + single full-width card
//   • "form"      — header + stacked input rows

export type RouteSkeletonVariant = "default" | "list" | "detail" | "form";

export function RouteSkeleton({ variant = "default" }: { variant?: RouteSkeletonVariant }) {
  return (
    <div className="px-4 sm:px-5 md:px-6 pt-4 pb-24 md:pb-6">
      {/* Header bar */}
      <header className="space-y-2 mb-4">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-3 w-72" />
      </header>

      {variant === "default" && <DefaultBody />}
      {variant === "list"    && <ListBody />}
      {variant === "detail"  && <DetailBody />}
      {variant === "form"    && <FormBody />}
    </div>
  );
}

function DefaultBody() {
  return (
    <div className="space-y-4">
      {/* KPI strip */}
      <section className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="card p-3.5 space-y-2">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-7 w-24" />
            <Skeleton className="h-3 w-28" />
          </div>
        ))}
      </section>
      {/* 8/4 body */}
      <section className="grid grid-cols-12 gap-3 lg:gap-4 items-start">
        <div className="col-span-12 lg:col-span-8 card p-3.5 space-y-3">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-11/12" />
          <Skeleton className="h-[200px] w-full" />
        </div>
        <div className="col-span-12 lg:col-span-4 card p-3.5 space-y-3">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-3/4" />
          <Skeleton className="h-[120px] w-full" />
        </div>
      </section>
    </div>
  );
}

function ListBody() {
  return (
    <section className="card p-3.5 space-y-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 py-2.5 border-b last:border-b-0 border-[var(--color-edify-divider)]">
          <Skeleton className="h-9 w-9 rounded-full shrink-0" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3.5 w-2/5" />
            <Skeleton className="h-3 w-3/4" />
          </div>
          <Skeleton className="h-3 w-16 shrink-0" />
        </div>
      ))}
    </section>
  );
}

function DetailBody() {
  return (
    <article className="card p-3.5 lg:p-6 space-y-4">
      <Skeleton className="h-6 w-3/5" />
      <div className="space-y-2">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-11/12" />
        <Skeleton className="h-3 w-10/12" />
        <Skeleton className="h-3 w-9/12" />
      </div>
      <Skeleton className="h-[180px] w-full" />
      <div className="space-y-2">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-11/12" />
        <Skeleton className="h-3 w-2/3" />
      </div>
    </article>
  );
}

function FormBody() {
  return (
    <section className="card p-3.5 lg:p-6 space-y-4 max-w-[640px]">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="space-y-1.5">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-10 w-full" />
        </div>
      ))}
      <div className="flex justify-end gap-2 pt-2">
        <Skeleton className="h-9 w-24" />
        <Skeleton className="h-9 w-32" />
      </div>
    </section>
  );
}
