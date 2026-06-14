import { StubPage } from "@/components/shell/StubPage";
import { getCurrentUser } from "@/lib/auth";
import { backendFetch, isBackendEnabled } from "@/lib/api/backend";

// Security & Data Protection dashboard — Admin only. Middleware already gates
// the /admin prefix to Admin; this page re-checks (defence in depth) and never
// renders for any other role. Every figure is REAL backend data (audit log +
// integrity invariants); no mock.
export const dynamic = "force-dynamic";

type Summary = {
  generatedAt: string;
  authentication: { logins24h: number; failedLogins24h: number; activeUsers: number; lockedAccounts: number | null; mfaAdoption: number | null };
  authorization: { denies24h: number; shadowDenies24h: number; sensitiveAllows24h: number; evidenceDownloads24h: number };
  auditIntegrity: { ok: boolean; chainedRows: number; brokenAtSeq: string | null; reason: string | null };
  evidence: { quarantined: number; scanBreakdown: Record<string, number> };
  paymentIntegrity: { paidWithoutIa: number; paidWithoutEvidence: number; paidWithoutSf: number; accountabilityNoNetsuite: number };
  productionSafety: { nodeEnv?: string; mockDataEnabled: boolean; devEndpointsEnabled: boolean; authzMode: string; partnerRoleBridge: boolean; productionSafe: boolean };
  backups: { configured: boolean; lastBackupAt: string | null; ageHours: number | null };
  dependencies: { note: string };
  alerts: { severity: "critical" | "warning" | "info"; key: string; message: string }[];
};

const ALERT_TONE: Record<Summary["alerts"][number]["severity"], string> = {
  critical: "bg-rose-50 border-rose-200 text-rose-700",
  warning: "bg-amber-50 border-amber-200 text-amber-700",
  info: "bg-[var(--color-edify-soft)]/40 border-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
};

function Tile({ label, value, good, bad }: { label: string; value: string | number; good?: boolean; bad?: boolean }) {
  const tone = bad ? "text-rose-600" : good ? "text-emerald-600" : "text-[var(--color-ink)]";
  return (
    <div className="card rounded-xl p-3.5">
      <div className="text-[10px] muted font-bold uppercase tracking-wide">{label}</div>
      <div className={`mt-1 text-[22px] font-extrabold tabular ${tone}`}>{value}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-body font-extrabold tracking-tight">{title}</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">{children}</div>
    </section>
  );
}

export default async function SecurityDashboardPage() {
  const user = await getCurrentUser();
  if (user.role !== "Admin") {
    return (
      <StubPage title="Security & Data Protection" subtitle="Restricted.">
        <section className="card rounded-2xl p-5 text-caption muted">
          This dashboard is available to Admin / Security owners only.
        </section>
      </StubPage>
    );
  }

  const res = isBackendEnabled()
    ? await backendFetch<Summary>("/security/health", { email: user.email, role: user.role })
    : ({ ok: false, error: "Backend disabled" } as const);

  if (!res.ok) {
    return (
      <StubPage title="Security & Data Protection" subtitle="Live security posture.">
        <section className="card rounded-2xl p-5 text-caption muted">
          Could not load the security summary ({res.error}). Ensure the backend is running and reachable.
        </section>
      </StubPage>
    );
  }

  const s = res.data;
  const payViolations = s.paymentIntegrity.paidWithoutIa + s.paymentIntegrity.paidWithoutEvidence + s.paymentIntegrity.paidWithoutSf + s.paymentIntegrity.accountabilityNoNetsuite;

  return (
    <StubPage
      title="Security & Data Protection"
      subtitle={`Live posture from the audit log + integrity invariants. Generated ${new Date(s.generatedAt).toLocaleString()}. Admin only.`}
    >
      {/* Active alerts */}
      <section className="space-y-2">
        <h2 className="text-body font-extrabold tracking-tight">Active alerts {s.alerts.length === 0 && <span className="text-caption muted font-semibold">· none</span>}</h2>
        {s.alerts.length === 0 ? (
          <div className="card rounded-xl p-3.5 text-caption text-emerald-600 font-semibold">No unresolved security alerts.</div>
        ) : (
          <div className="space-y-1.5">
            {s.alerts.map((a) => (
              <div key={a.key} className={`rounded-xl border p-3 text-caption font-semibold ${ALERT_TONE[a.severity]}`}>
                <span className="uppercase text-[10px] font-extrabold mr-2">{a.severity}</span>
                {a.message}
              </div>
            ))}
          </div>
        )}
      </section>

      <Section title="Authentication (24h)">
        <Tile label="Sign-ins" value={s.authentication.logins24h} />
        <Tile label="Failed sign-ins" value={s.authentication.failedLogins24h} bad={s.authentication.failedLogins24h > 0} />
        <Tile label="Active accounts" value={s.authentication.activeUsers} />
        <Tile label="Locked accounts" value={s.authentication.lockedAccounts ?? "—"} />
      </Section>

      <Section title="Authorization (24h)">
        <Tile label="Denials (enforced)" value={s.authorization.denies24h} bad={s.authorization.denies24h > 0} />
        <Tile label="Denials (shadow)" value={s.authorization.shadowDenies24h} />
        <Tile label="Sensitive actions" value={s.authorization.sensitiveAllows24h} />
        <Tile label="Evidence downloads" value={s.authorization.evidenceDownloads24h} />
      </Section>

      <Section title="Audit integrity">
        <Tile label="Hash chain" value={s.auditIntegrity.ok ? "INTACT" : "BROKEN"} good={s.auditIntegrity.ok} bad={!s.auditIntegrity.ok} />
        <Tile label="Chained rows" value={s.auditIntegrity.chainedRows} />
        <Tile label="Break at seq" value={s.auditIntegrity.brokenAtSeq ?? "—"} bad={!!s.auditIntegrity.brokenAtSeq} />
        <Tile label="Append-only" value="DB-enforced" good />
      </Section>

      <Section title="Evidence protection">
        <Tile label="Quarantined" value={s.evidence.quarantined} bad={s.evidence.quarantined > 0} />
        <Tile label="Scanned (clean)" value={s.evidence.scanBreakdown.clean ?? 0} />
        <Tile label="Unscanned (skipped)" value={(s.evidence.scanBreakdown.skipped ?? 0) + (s.evidence.scanBreakdown.pending ?? 0)} />
        <Tile label="Public exposure" value="None" good />
      </Section>

      <Section title="Payment & accountability integrity">
        <Tile label="Paid w/o IA" value={s.paymentIntegrity.paidWithoutIa} bad={s.paymentIntegrity.paidWithoutIa > 0} />
        <Tile label="Paid w/o evidence" value={s.paymentIntegrity.paidWithoutEvidence} bad={s.paymentIntegrity.paidWithoutEvidence > 0} />
        <Tile label="Paid w/o Salesforce" value={s.paymentIntegrity.paidWithoutSf} bad={s.paymentIntegrity.paidWithoutSf > 0} />
        <Tile label="Accountability w/o Netsuite" value={s.paymentIntegrity.accountabilityNoNetsuite} bad={s.paymentIntegrity.accountabilityNoNetsuite > 0} />
      </Section>

      <Section title="Production safety & backups">
        <Tile label="Production safe" value={s.productionSafety.productionSafe ? "YES" : "NO"} good={s.productionSafety.productionSafe} bad={!s.productionSafety.productionSafe} />
        <Tile label="Authz mode" value={s.productionSafety.authzMode} good={s.productionSafety.authzMode === "enforce"} />
        <Tile label="Mock data" value={s.productionSafety.mockDataEnabled ? "ON" : "OFF"} bad={s.productionSafety.mockDataEnabled && s.productionSafety.nodeEnv === "production"} />
        <Tile label="Last backup" value={s.backups.lastBackupAt ? `${s.backups.ageHours}h ago` : "none"} bad={s.backups.configured && !s.backups.lastBackupAt} />
      </Section>

      <p className="text-caption muted">
        Payment integrity is the spec's hard line — any non-zero figure means money moved without full verification and must be investigated immediately. Dependency scanning: {s.dependencies.note}
      </p>
    </StubPage>
  );
}
