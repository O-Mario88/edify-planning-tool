import { StubPage } from "@/components/shell/StubPage";
import { NotificationsList } from "@/components/notifications/NotificationsList";

// Notifications inbox — the full-page view of the same live feed that powers
// the bell badge + drawer. The list renders client-side from the
// notifications-store (backed by /api/notifications), so every row links to
// the backend-provided targetRoute (n.href) and marks itself read on click.
// No mock data: an empty database shows an empty state, never fabricated rows.

export const dynamic = "force-dynamic";

export default function NotificationsPage() {
  return (
    <StubPage
      title="Notifications"
      subtitle="Red alerts and what to do next, plus updates on evidence, payments, approvals, and field work — drawn from the same engines that power your dashboards."
    >
      <NotificationsList />
    </StubPage>
  );
}
