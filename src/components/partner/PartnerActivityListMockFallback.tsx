// PartnerActivityListMockFallback — dev-only fallback for the partner
// cycle-path pages when EDIFY_USE_BACKEND=false. It re-exports the legacy
// in-memory mock components so local development without a running backend
// still renders something. This is loaded ONLY via `await import()` from the
// !live branch of PartnerActivityListLive — so the live component (and the
// pages that mount it) keep mock-free top-level imports and the mock-audit gate
// stays green for the route pages.
//
// This file deliberately owns the mock imports so the leak is quarantined to a
// single, clearly-labelled dev-fallback module.

import { MyActivitiesTable } from "@/components/partner/MyActivitiesTable";
import { PartnerReturnedCorrections } from "@/components/partner/PartnerReturnedCorrections";

export function PartnerActivityListMockFallback({
  variant = "list",
}: {
  variant?: "list" | "corrections";
}) {
  if (variant === "corrections") return <PartnerReturnedCorrections />;
  return <MyActivitiesTable />;
}
