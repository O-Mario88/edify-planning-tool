// Deprecated: canonical URL is /partner/planning.

import { permanentRedirect } from "next/navigation";

export default function DeprecatedDashboardPlanning() {
  permanentRedirect("/partner/planning");
}
