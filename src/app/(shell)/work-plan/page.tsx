import { permanentRedirect } from "next/navigation";

// Legacy URL. The CCEO Operating View now lives at /dashboards/cceo
// alongside every other role's primary dashboard. 308 keeps old
// bookmarks, deep links (incl. #service-package anchors), and search
// index entries working.
export default function WorkPlanRedirect() {
  permanentRedirect("/dashboards/cceo");
}
