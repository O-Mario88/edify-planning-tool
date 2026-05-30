import { EdifySidebarServer } from "@/components/shell/EdifySidebarServer";
import { Skeleton } from "@/components/ui/Skeleton";

// Global loading skeleton. Next.js renders this while the route segment
// suspends (server data resolution / lazy chart imports). Mirrors the
// shell layout so the user sees the right shape immediately.
export default function GlobalLoading() {
  return (
    <div className="flex min-h-screen w-full bg-[var(--color-page)]">
      <EdifySidebarServer />
      <main className="flex-1 min-w-0">
        <header className="pl-16 pr-4 pt-5 lg:pl-6 lg:pr-6 pb-4 space-y-2">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-3 w-72" />
        </header>
        <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6 space-y-4">
          {/* KPI strip */}
          <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="card p-3.5 space-y-2">
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-7 w-24" />
                <Skeleton className="h-3 w-28" />
              </div>
            ))}
          </section>
          {/* Two-column body */}
          <section className="grid grid-cols-12 gap-4 items-start">
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
      </main>
    </div>
  );
}
