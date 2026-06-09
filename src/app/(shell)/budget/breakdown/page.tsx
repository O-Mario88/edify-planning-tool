import { StubPage } from "@/components/shell/StubPage";
import { LiveBudgetReport } from "@/components/budget/LiveBudgetReport";

// Annual Budget Breakdown — LIVE. Every line is the caller's scheduled,
// auto-costed activities (backend /api/budget/from-schedule), so each figure
// traces straight back to a real activity type and the CD rate card. No mock.
export default function AnnualBudgetBreakdownPage() {
  return (
    <StubPage
      title="Annual Budget Breakdown"
      subtitle="Every line traces to the plan — your scheduled activities, auto-costed from the CD rate card. Split by activity type and staff/partner delivery."
    >
      <LiveBudgetReport view="breakdown" />
    </StubPage>
  );
}
