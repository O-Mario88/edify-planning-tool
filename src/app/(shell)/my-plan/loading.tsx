import { MyPlanCardSkeleton } from "@/components/planning/MyPlanCard";

// Shown while /my-plan streams in — mirrors the page shape so the layout
// never jumps.
export default function MyPlanLoading() {
  return (
    <>
      <header className="pl-16 pr-4 pt-5 lg:pl-6 lg:pr-6 pb-4">
        <h1 className="page-title">
          My Plan
        </h1>
        <p className="text-body muted mt-0.5">
          Your Plan across every horizon, and the activities scheduled for the
          current month.
        </p>
      </header>

      <div className="px-4 sm:px-5 md:px-6 pb-10 md:pb-6 space-y-3">
        <MyPlanCardSkeleton />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-[70px] rounded-xl bg-[var(--color-edify-soft)]/60 animate-pulse"
            />
          ))}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="h-[66px] rounded-2xl bg-[var(--color-edify-soft)]/50 animate-pulse"
            />
          ))}
        </div>
      </div>
    </>
  );
}
