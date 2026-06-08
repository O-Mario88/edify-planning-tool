"use client";

// Client error surface for the (server-rendered) School 360 page.
//
// When the backend is enabled and a school-detail request fails with a real
// backend error (not a 404 "no such school", which legitimately falls through
// to legacy id-space lookups), the server renders this instead of silently
// showing mock data — honouring the migration rule: "Backend failure = error.
// Never fake data." Retry triggers a server re-render via router.refresh().

import { useRouter } from "next/navigation";
import { CorePageHeader } from "@/components/core/CorePageHeader";
import { ErrorState } from "@/components/ui/DataStates";
import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";

export function SchoolDetailErrorState({ message }: { message?: string }) {
  const router = useRouter();
  return (
    <>
      <CorePageHeader icon="schools" title="School 360" subtitle="Live from the backend database (edify-api)." />
      <div className="px-3 sm:px-4 md:px-6 pb-24 lg:pb-6 pt-6">
        <ErrorState
          message={message ?? "Could not load this school from the backend."}
          onRetry={() => router.refresh()}
        />
      </div>
      <RoleBottomNav />
    </>
  );
}
