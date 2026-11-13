/** The most a top-bar badge spells out; past it the badge reads "99+". */
const MOST_SHOWN = 99;

/**
 * A count as the top bar's badges show it (frontend_filters.badge_count, and
 * shell.html draws no badge for none): an 18px pill cannot hold "138".
 */
export function badgeCount(count: number): string {
  if (count <= 0) return '';
  return count > MOST_SHOWN ? `${MOST_SHOWN}+` : String(count);
}
