/**
 * Where signing in lands, by role: Home, every reader's own role home. The
 * country readers (Impact Assessment, the Country Director, the RVP and the
 * Regional Lead) used to start on Country Oversight (owner, 2026-10-25, the
 * web's apps/core/landing.py); in the redesign they land on their own Home
 * like everyone else (owner, 2026-11-19: "Own role home"), with their
 * oversight one tap away in Home's quick access. The menu is still asked,
 * so a later role landing can depend on what the reader may open.
 */
import type { GetNavigationResponse } from './gen/edify/screens/v1/navigation_pb';

export const HOME_URL = '/home';

export function landingUrl(_activeRole: string, _navigation: GetNavigationResponse | null): string {
  return HOME_URL;
}
