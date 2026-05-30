import { getCurrentUser } from "@/lib/auth";
import { heroContentForRole, type HeroRole } from "@/lib/dashboard-hero-mock";
import { DashboardHero } from "./DashboardHero";

// Server-component wrapper. Each dashboard drops in
// <DashboardHeroServer roleOverride="…" /> and we resolve the
// signed-in user from the session cookie + the matching hero content
// from the role map. The greeting is always personalised; the rest of
// the hero (title, quote, chips, CTAs) is role-specific.
//
// Pass `roleOverride` for shared dashboards where the role isn't the
// user's primary role — e.g., Admins land on the Director view, so
// the director page passes "CountryDirector" explicitly.

export async function DashboardHeroServer({
  roleOverride,
  notificationsCount = 12,
}: {
  roleOverride?:      HeroRole;
  notificationsCount?: number;
} = {}) {
  const user = await getCurrentUser();
  const role: HeroRole = roleOverride ?? (user.role as HeroRole);
  const content = heroContentForRole(role);
  return (
    <DashboardHero
      content={content}
      user={{
        name:     user.name,
        initials: user.initials,
        role:     content.pillLabel.replace(" View", "") || role,
        online:   true,
      }}
      notificationsCount={notificationsCount}
    />
  );
}
