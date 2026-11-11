/**
 * Where signing in lands, by role: the web's rule (apps/core/landing.py),
 * not a new one. Home for everyone, except the country readers, who start
 * on Country Oversight (owner, 2026-10-25) when they may open it. Whether
 * they may is the server's call: the page is in their menu only if so.
 */
import type { GetNavigationResponse } from './gen/edify/screens/v1/navigation_pb';

export const HOME_URL = '/home';
export const COUNTRY_OVERSIGHT_URL = '/country-planning-oversight/';

const COUNTRY_OVERSIGHT_ROLES = new Set(['ImpactAssessment', 'CountryDirector', 'RegionalVicePresident', 'RegionalProgramLead']);

const pathOf = (url: string) => url.split(/[?#]/)[0].replace(/\/+$/, '');

export function landingUrl(activeRole: string, navigation: GetNavigationResponse | null): string {
  if (!navigation || !COUNTRY_OVERSIGHT_ROLES.has(activeRole)) {
    return HOME_URL;
  }
  const items = [...navigation.bottom, ...navigation.sections.flatMap((section) => section.items)];
  const target = pathOf(COUNTRY_OVERSIGHT_URL);
  return items.some((item) => pathOf(item.url) === target) ? COUNTRY_OVERSIGHT_URL : HOME_URL;
}
