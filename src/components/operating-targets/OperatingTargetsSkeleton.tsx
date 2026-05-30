// Skeleton mirror of OperatingTargetsView.
//
// Rendered while the server component resolves the current user and
// the page module loads. The visual shape matches the real page 1:1
// — header strip, 7 period donut tiles, 6 KPI cards, full-width
// targets table, and the 4 bottom cards — so the layout doesn't
// shift on hydration and the user reads "loading" without thinking
// "broken".

import { Skeleton } from "@/components/ui/Skeleton";

export function OperatingTargetsSkeleton() {
  return (
    <div className="px-4 sm:px-5 md:px-6 pt-5 pb-24 md:pb-6 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="space-y-2">
          <Skeleton className="h-6 w-44" />
          <Skeleton className="h-3 w-[420px] max-w-full" />
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Skeleton className="h-9 w-28" />
          <Skeleton className="h-9 w-36" />
          <Skeleton className="h-9 w-20" />
          <Skeleton className="h-9 w-28" />
        </div>
      </div>

      {/* 7 period donut tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-2">
        {Array.from({ length: 7 }).map((_, i) => (
          <div key={i} className="card rounded-2xl p-3 space-y-2">
            <div className="space-y-1.5">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-2.5 w-12" />
            </div>
            <div className="flex items-center gap-2.5">
              <Skeleton className="h-14 w-14 rounded-full" />
              <div className="space-y-1.5 flex-1">
                <Skeleton className="h-3 w-14" />
                <Skeleton className="h-2.5 w-16" />
              </div>
            </div>
            <Skeleton className="h-3.5 w-20" />
          </div>
        ))}
      </div>

      {/* 6 KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="card p-3.5 space-y-2.5">
            <div className="flex items-center gap-2">
              <Skeleton className="h-8 w-8 rounded-lg" />
              <Skeleton className="h-3 w-24 flex-1" />
            </div>
            <Skeleton className="h-5 w-28" />
            <Skeleton className="h-2.5 w-20" />
            <Skeleton className="h-8 w-full" />
          </div>
        ))}
      </div>

      {/* Targets table */}
      <div className="card p-3.5 space-y-3">
        <Skeleton className="h-4 w-44" />
        <div className="space-y-2">
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="grid grid-cols-8 gap-2">
              <Skeleton className="h-7 col-span-2" />
              {Array.from({ length: 6 }).map((__, j) => (
                <Skeleton key={j} className="h-7" />
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* 4 bottom cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="card p-3.5 space-y-3">
            <Skeleton className="h-4 w-36" />
            <Skeleton className="h-[180px] w-full" />
          </div>
        ))}
      </div>
    </div>
  );
}
