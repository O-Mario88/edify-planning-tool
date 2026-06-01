import { permanentRedirect } from "next/navigation";

// The engine-backed analytics now live at /analytics (the route every
// dashboard links to). This standalone route was the Phase-1 reference and
// is retired — redirect so old links keep working.
export default function FieldAnalyticsRedirect() {
  permanentRedirect("/analytics");
}
