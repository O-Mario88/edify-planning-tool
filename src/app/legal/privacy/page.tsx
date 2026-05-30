import { StubPage } from "@/components/shell/StubPage";

export default function PrivacyPage() {
  return (
    <StubPage
      title="Privacy"
      subtitle="Last updated May 11, 2026. What we collect, why, and how to access or delete your data."
    >
      <article className="card rounded-2xl p-6">
        <h2 className="text-[15px] font-extrabold tracking-tight">What we collect</h2>
        <p className="text-[12px] leading-relaxed muted mt-1">
          Your name, work email, role assignment, country, and the activity you log (visits,
          trainings, daily debriefs, fund requests, leave requests, SSA submissions). We collect
          sign-in metadata (timestamp, IP, browser) for security.
        </p>

        <h2 className="text-[15px] font-extrabold tracking-tight mt-4">Why we collect it</h2>
        <ul className="text-[12px] leading-relaxed muted mt-1 list-disc pl-5 space-y-1">
          <li>To operate role-based dashboards and ensure each user only sees what their role permits.</li>
          <li>To compute targets, verified achievement, and the leaderboard.</li>
          <li>To audit privileged actions (approvals, role changes, fund disbursement).</li>
          <li>To send you operational notifications about plans, requests, and debriefs.</li>
        </ul>

        <h2 className="text-[15px] font-extrabold tracking-tight mt-4">Data residency</h2>
        <p className="text-[12px] leading-relaxed muted mt-1">
          Edify data is hosted in East Africa Community jurisdictions. School and staff PII is not
          transferred outside the EAC except where required by Salesforce sync or audit by Edify
          Compliance.
        </p>

        <h2 className="text-[15px] font-extrabold tracking-tight mt-4">Your rights</h2>
        <p className="text-[12px] leading-relaxed muted mt-1">
          You can request an export of your account data or its deletion by contacting your country
          admin or emailing{" "}
          <a href="mailto:privacy@edify.org" className="text-[var(--color-edify-primary)] font-semibold">
            privacy@edify.org
          </a>
          . Audit log entries are retained for 365 days regardless of account state.
        </p>

        <h2 className="text-[15px] font-extrabold tracking-tight mt-4">Third-party processors</h2>
        <ul className="text-[12px] leading-relaxed muted mt-1 list-disc pl-5 space-y-1">
          <li>Salesforce — system of record for visits, trainings, verifications.</li>
          <li>Email provider — operational notifications + password reset.</li>
          <li>Identity provider — sign-in.</li>
        </ul>
      </article>
    </StubPage>
  );
}
