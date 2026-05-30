import { StubPage } from "@/components/shell/StubPage";

export default function TermsPage() {
  return (
    <StubPage
      title="Terms of Service"
      subtitle="Last updated May 11, 2026. By accessing Edify, you agree to these terms."
    >
      <article className="card rounded-2xl p-6 prose prose-sm max-w-none">
        <h2 className="text-[15px] font-extrabold tracking-tight">1. Use of the platform</h2>
        <p className="text-[12px] leading-relaxed muted">
          Edify is provided to staff and approved partners of the Edify program. Access is provisioned
          by a country administrator and tied to the email address of record. You agree not to share
          your credentials, attempt to bypass role-based access controls, or extract data outside the
          tools provided by Edify.
        </p>

        <h2 className="text-[15px] font-extrabold tracking-tight mt-4">2. Data we store</h2>
        <p className="text-[12px] leading-relaxed muted">
          Edify stores: account identity, role assignments, school + cluster + district records,
          activity logs (visits, trainings, debriefs), SSA assessments, fund-request records, leave
          requests, and audit logs. Personal information is limited to your name, email, role, and
          login activity.
        </p>

        <h2 className="text-[15px] font-extrabold tracking-tight mt-4">3. Verified work counts</h2>
        <p className="text-[12px] leading-relaxed muted">
          Targets and the verified-impact leaderboard count Salesforce-verified work only. Work
          without a verified Salesforce record is visible to you and your supervisor but does not
          accrue toward published targets. This rule applies uniformly across roles.
        </p>

        <h2 className="text-[15px] font-extrabold tracking-tight mt-4">4. Humane performance review</h2>
        <p className="text-[12px] leading-relaxed muted">
          Performance escalation (PIP) is gated by a documented support-review process. Mid-year
          below-40% triggers a support review; the support-review checklist must be completed before
          any escalation can be filed.
        </p>

        <h2 className="text-[15px] font-extrabold tracking-tight mt-4">5. Acceptable use</h2>
        <p className="text-[12px] leading-relaxed muted">
          You agree not to log false or misleading data, submit duplicate Salesforce IDs, or
          misrepresent the work of another staff member. Audit logs are retained for 365 days and
          may be reviewed by Country Directors and the Compliance team.
        </p>

        <h2 className="text-[15px] font-extrabold tracking-tight mt-4">6. Termination</h2>
        <p className="text-[12px] leading-relaxed muted">
          Access ends when your role ends, or as required by your country admin or Edify Compliance.
          Your activity history is retained for the audit retention window even after access ends.
        </p>

        <p className="text-[11px] muted mt-6">
          Questions about these terms? Contact{" "}
          <a href="mailto:support@edify.org" className="text-[var(--color-edify-primary)] font-semibold">
            support@edify.org
          </a>.
        </p>
      </article>
    </StubPage>
  );
}
