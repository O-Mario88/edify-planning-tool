import { StubPage } from "@/components/shell/StubPage";
import { CompletedActivitiesLive } from "@/components/activities/CompletedActivitiesLive";

// Completed Activities Log — historical/closed work, kept out of the active
// Planning and My Plan views (but never deleted). Backend-driven.
export const dynamic = "force-dynamic";

export default function CompletedActivitiesPage() {
  return (
    <StubPage
      title="Completed Activities Log"
      subtitle="Verified, paid, and closed work — the full history. Active task views stay focused on what still needs action."
    >
      <CompletedActivitiesLive />
    </StubPage>
  );
}
