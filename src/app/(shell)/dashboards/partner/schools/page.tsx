// Deprecated: canonical URL is /partner/schools.
//
// This file existed when partner sub-pages were split between
// /dashboards/partner/* (overview-like surfaces) and /partner/*
// (workflow surfaces). The two implementations were byte-for-byte
// identical except for the page title. We picked /partner/schools as
// canonical because it sits inside the partner workflow namespace
// (today, schedule, evidence, corrections…) — schools is a workflow
// surface, not a dashboard widget.

import { redirect, permanentRedirect } from "next/navigation";

export default function DeprecatedPartnerDashboardSchools() {
  permanentRedirect("/partner/schools");
  // Unreachable; satisfies the TS return type if permanentRedirect's
  // `never` inference is ever weakened by a future Next.js release.
  redirect("/partner/schools");
}
