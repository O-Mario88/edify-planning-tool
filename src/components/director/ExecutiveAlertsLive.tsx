import { getCurrentUser } from "@/lib/auth";
import {
  fetchFundRequests,
  fetchHrRoster,
  fetchLeadershipSummary,
  fetchPartners,
} from "@/lib/api/surfaces";
import { isMockAllowed } from "@/lib/mock-policy";
import { ExecutiveAlerts } from "./ExecutiveAlerts";
import { buildExecutiveAlertsLive } from "@/lib/director/executive-alerts-live";
import type { ExecutiveAlertInputs } from "@/lib/director/executive-alerts";
import { SectionCard } from "@/components/ui/primitives";
import { Siren } from "lucide-react";
import Link from "next/link";

export async function ExecutiveAlertsLive({ inputs }: { inputs?: ExecutiveAlertInputs }) {
  if (isMockAllowed()) return <ExecutiveAlerts inputs={inputs} />;

  const user = await getCurrentUser();
  const [funds, leadership, roster, partners] = await Promise.all([
    fetchFundRequests(user),
    fetchLeadershipSummary(user),
    fetchHrRoster(user),
    fetchPartners(user),
  ]);

  const alerts = buildExecutiveAlertsLive({
    ...inputs,
    fundRequests: funds.live ? funds.data : [],
    leadership: leadership.live ? leadership.data : null,
    staff: roster.live ? roster.data.staff : [],
    partners: partners.live ? partners.data : [],
  });

  const urgent = alerts.filter((a) => a.severity === "urgent").length;

  return (
    <SectionCard
      icon={<Siren size={13} />}
      title="Today's Executive Alerts"
      subtitle={urgent > 0 ? `${urgent} urgent — money, accountability, or people need a decision` : "No urgent items in your scope right now"}
    >
      {alerts.length === 0 ? (
        <p className="text-[12px] muted py-2">You&apos;re clear. The system will surface fund, accountability, and performance alerts here as they appear.</p>
      ) : (
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {alerts.map((alert) => (
            <li key={alert.id} className="py-3 flex flex-col sm:flex-row sm:items-start gap-2 sm:justify-between">
              <div className="min-w-0">
                <div className="text-[13px] font-extrabold">{alert.issue}</div>
                <p className="text-[12px] muted mt-0.5">{alert.why}</p>
                <p className="text-[11px] muted mt-1">{alert.scope}</p>
              </div>
              <Link
                href={alert.actionHref}
                className="shrink-0 inline-flex items-center rounded-md border border-[var(--color-edify-border)] px-3 py-1.5 text-[12px] font-bold hover:bg-[var(--color-edify-soft)]/40"
              >
                {alert.actionLabel}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}
