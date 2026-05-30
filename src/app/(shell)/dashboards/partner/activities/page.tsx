// Deprecated: canonical URL is /partner/activities.
// Moved into the /partner/* workflow namespace alongside today,
// schedule, evidence, corrections, schools, reports, etc.

import { permanentRedirect } from "next/navigation";

export default function DeprecatedDashboardActivities() {
  permanentRedirect("/partner/activities");
}
