// Shown while /my-plan streams in — mirrors the five-section list shape
// (Due Today · This Week · This Month · Waiting on Me · Needs Attention)
// so the layout never jumps.
export default function MyPlanLoading() {
  return (
    <>
      <header className="pl-16 pr-4 pt-5 lg:pl-6 lg:pr-6 pb-4">
        <h1 className="page-title">My Plan</h1>
        <p className="text-body muted mt-0.5">
          What&apos;s already scheduled for you — due today, this week, this
          month, what&apos;s waiting on you, and what keeps slipping.
        </p>
      </header>

      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6 space-y-4">
        {Array.from({ length: 5 }).map((_, s) => (
          <div key={s} className="space-y-1.5">
            <div className="h-3.5 w-44 rounded bg-[var(--color-edify-soft)]/70 animate-pulse" />
            {Array.from({ length: s < 3 ? 2 : 1 }).map((_, i) => (
              <div key={i} className="h-[58px] rounded-xl bg-[var(--color-edify-soft)]/50 animate-pulse" />
            ))}
          </div>
        ))}
      </div>
    </>
  );
}
