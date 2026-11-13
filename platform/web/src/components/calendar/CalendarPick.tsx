'use client';

/*
 * An activity's tick box on the calendar (partials/calendar/event.html). A
 * run over several days draws one box on each day, and they are one tick:
 * ticking any ticks them all. The page's bar (SelectionBar) reads every
 * ticked `data-pick` box once the change reaches the document, after this.
 */
export function CalendarPick({ id, label }: { id: string; label: string }) {
  return (
    <input
      type="checkbox"
      className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-[var(--edify-accent)]"
      data-pick={id}
      aria-label={label}
      onChange={(change) => {
        const checked = change.currentTarget.checked;
        document.querySelectorAll<HTMLInputElement>('input[data-pick]').forEach((box) => {
          if (box.dataset.pick === id) box.checked = checked;
        });
      }}
    />
  );
}

/** "Select all" on the month card: ticks or clears every activity's box on the page. */
export function CalendarSelectAll() {
  return (
    <label className="flex items-center gap-2 font-semibold">
      <input
        type="checkbox"
        className="h-4 w-4 accent-[var(--edify-accent)]"
        onChange={(change) => {
          const checked = change.currentTarget.checked;
          document.querySelectorAll<HTMLInputElement>('input[data-pick]').forEach((box) => {
            box.checked = checked;
          });
        }}
      />
      Select all
    </label>
  );
}
