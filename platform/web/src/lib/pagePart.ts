/**
 * The parts a page loads once something on it opens (PageRecord.details_path:
 * a cluster card's schools). Only these paths are asked of the gateway
 * through /page-parts; anything else is refused before the gateway is asked.
 */
const PAGE_PARTS: readonly RegExp[] = [/^\/partials\/clusters\/[A-Za-z0-9_-]{1,64}\/schools$/];

export function isPagePart(path: string): boolean {
  return PAGE_PARTS.some((pattern) => pattern.test(path));
}

/** This app's address for a part: the route that asks the gateway as the reader. */
export function pagePartUrl(path: string): string {
  return `/page-parts?${new URLSearchParams({ path }).toString()}`;
}
