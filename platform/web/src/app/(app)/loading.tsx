/*
 * What a page shows the moment it is asked for, while Go answers: a still
 * outline of a page (its title, a figure strip, a card of rows), as the
 * app's pages load (PageSkeleton.tsx), instead of the last page staying on
 * screen with no sign anything is happening (2026-11-20 review). Nothing
 * moves, for a reader who asked for reduced motion.
 */
const TILES = 4;
const ROWS = 5;

function Bar({ className }: { className: string }) {
  return <span aria-hidden="true" className={`block rounded-[6px] bg-[var(--edify-surface-muted)] ${className}`} />;
}

export default function Loading() {
  return (
    <div role="status" aria-label="Loading" className="mx-auto max-w-[1500px] space-y-4 px-4 pt-5 sm:px-6" data-block="loading">
      <div className="space-y-2">
        <Bar className="h-3 w-24" />
        <Bar className="h-6 w-56" />
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: TILES }, (_, i) => (
          <div key={i} className="card space-y-2 p-4">
            <Bar className="h-5 w-12" />
            <Bar className="h-3 w-28" />
          </div>
        ))}
      </div>
      <div className="card overflow-hidden">
        <div className="p-4">
          <Bar className="h-4 w-40" />
        </div>
        {Array.from({ length: ROWS }, (_, i) => (
          <div key={i} className="space-y-2 border-t border-[var(--edify-border)] px-4 py-3">
            <Bar className="h-3 w-3/4" />
            <Bar className="h-3 w-1/2" />
          </div>
        ))}
      </div>
    </div>
  );
}
