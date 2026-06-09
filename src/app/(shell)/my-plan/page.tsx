import { StubPage } from "@/components/shell/StubPage";
import { MyPlanLive } from "@/components/planning/MyPlanLive";

// My Plan — what is ALREADY scheduled for me. Separate from the Planning Tool
// (which decides what still needs scheduling) and from the Completed Log (history).
// Shows active/scheduled work only.
export const dynamic = "force-dynamic";

export default function MyPlanPage() {
  return (
    <StubPage
      title="My Plan"
      subtitle="What's already scheduled for you — this week, this month, due today, and what's waiting on you."
    >
      <MyPlanLive />
    </StubPage>
  );
}
