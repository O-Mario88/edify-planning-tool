import { StubPage } from "@/components/shell/StubPage";
import { LiveBudgetReport } from "@/components/budget/LiveBudgetReport";

// Monthly Funding Plan — LIVE. Annual → quarterly → monthly, generated only
// from scheduled, costed activities (backend /api/budget/from-schedule).
// Busy/slow months fall straight out of the schedule. No mock.
export default function MonthlyFundingPlanPage() {
  return (
    <StubPage
      title="Monthly Funding Plan"
      subtitle="Annual → Quarterly → Monthly. Only scheduled, auto-costed activities generate funding — busy and slow months are detected automatically."
    >
      <LiveBudgetReport view="monthly" />
    </StubPage>
  );
}
