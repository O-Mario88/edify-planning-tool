/**
 * Page numbers around the current page, gaps as null: Django's
 * Paginator.get_elided_page_range(number, on_each_side=1, on_ends=1), which
 * the existing pages draw their pagers with (apps.core.pagination
 * .elided_page_numbers). Presentation only: which pages exist is the
 * gateway's answer.
 */
export function elidedPageNumbers(current: number, totalPages: number, onEachSide = 1, onEnds = 1): (number | null)[] {
  const range = (from: number, to: number): number[] =>
    Array.from({ length: Math.max(0, to - from) }, (_, index) => from + index);
  const number = Math.min(Math.max(1, current), Math.max(1, totalPages));
  if (totalPages <= (onEachSide + onEnds) * 2) return range(1, totalPages + 1);
  const pages: (number | null)[] = [];
  if (number > 1 + onEachSide + onEnds + 1) {
    pages.push(...range(1, onEnds + 1), null, ...range(number - onEachSide, number + 1));
  } else {
    pages.push(...range(1, number + 1));
  }
  if (number < totalPages - onEachSide - onEnds - 1) {
    pages.push(...range(number + 1, number + onEachSide + 1), null, ...range(totalPages - onEnds + 1, totalPages + 1));
  } else {
    pages.push(...range(number + 1, totalPages + 1));
  }
  return pages;
}

/** "Showing 51 to 100 of 699 schools", as the existing pager words it. */
export function showingSummary(page: number, pageSize: number, total: number, noun: string): string {
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);
  return `Showing ${start} to ${end} of ${total} ${noun}`;
}

/** The query with one key set (or removed when empty), as a relative href. */
export function hrefWith(path: string, query: Readonly<Record<string, string>>, changes: Readonly<Record<string, string>>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries({ ...query, ...changes })) {
    if (value) params.set(key, value);
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}
