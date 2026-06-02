import Link from "next/link";
import {
  FileSpreadsheet,
  Upload,
  ListChecks,
  ShieldCheck,
  ChevronRight,
  CheckCircle2,
  AlertTriangle,
  ShieldAlert,
} from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import {
  dataTemplates,
  dataImportBatches,
  planningDataReadiness,
} from "@/lib/data-intake-mock";
import { activeFinancialYear } from "@/lib/fy-engine";
import { getCurrentUser } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { IaIntakeActions } from "@/components/intake/IaIntakeActions";
import { OwnerMappingQueue } from "@/components/intake/OwnerMappingQueue";
import { intakeSchools } from "@/lib/intake/intake-mock";
import { ownerDistribution, unmatchedOwners } from "@/lib/portfolio/portfolio";
import { ORG_STAFF } from "@/lib/org/supervision";
import { openDuplicateCandidates } from "@/lib/intake/duplicate-candidates-mock";

export default async function DataIntakeHubPage() {
  const me   = await getCurrentUser();
  const fy   = activeFinancialYear();
  const r    = planningDataReadiness();

  // Role gate — data intake (school + SSA master data) is the Impact
  // Assessment + Admin job. Country Director sets cost/price only, not master
  // data, so CD (and everyone else) lands on a polite "no access" panel.
  const allowed = ["ImpactAssessment", "Admin"].includes(me.role);

  // School-ownership distribution + the IA owner-mapping queue (unmatched owners).
  const ownership = ownerDistribution();
  const unmatchedOwnerList = unmatchedOwners();
  // Account owners are field staff (CCEO) and program leads who hold portfolios.
  const mappableStaff = ORG_STAFF
    .filter((s) => s.role === "CCEO" || s.role === "CountryProgramLead")
    .map((s) => ({ staffId: s.staffId, name: s.name, role: s.role }));

  const openDuplicates = openDuplicateCandidates();

  const pendingBatches = dataImportBatches.filter((b) => b.status !== "Imported" && b.status !== "Rejected").length;
  const importedCount  = dataImportBatches.filter((b) => b.status === "Imported").length;
  const blockedAreas   = r.rows.filter((x) => x.status === "Blocked").length;
  const attentionAreas = r.rows.filter((x) => x.status === "Needs Attention").length;

  return (
    <StubPage
      title="Data Intake & Readiness Engine"
      subtitle={`The platform does not blindly use random uploads. Templates are system-generated. Files are validated. Only approved data enters the planning engine. ${fy.label}.`}
    >
      {!allowed && (
        <section className="card p-3.5 border-amber-200 bg-amber-50/60">
          <h2 className="text-[13px] font-extrabold tracking-tight">Master data upload is restricted</h2>
          <p className="text-[11.5px] muted">
            Only Impact Assessment and Admin upload master data (schools + SSA performance). The Country Director sets
            cost / price, not master data; CCEOs and field staff submit Salesforce IDs + evidence via the regular
            activity flow.
          </p>
        </section>
      )}

      {allowed && (
        <IaIntakeActions
          existingIds={intakeSchools.map((s) => s.schoolId)}
          schools={intakeSchools.map((s) => ({
            schoolId: s.schoolId,
            schoolName: s.schoolName,
            district: s.district,
            region: s.region,
            schoolType: s.schoolType,
            ssaStatus: s.ssaStatus,
            planningLocked: s.planningLocked,
            dateAdded: s.dateAdded,
            addedBy: s.addedBy,
            subCounty: s.subCounty,
            enrollment: s.enrollment,
            assignedCceo: s.assignedCceo,
            cluster: s.cluster,
            phone: s.phone,
            primaryContact: s.primaryContact,
            shippingAddress: s.shippingAddress,
            lastEnrollmentDate: s.lastEnrollmentDate,
          }))}
        />
      )}

      {allowed && (
        <>
          {/* School ownership distribution — auto-distribution health. */}
          <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Kpi label="Owners with schools" value={String(ownership.owners)}     sub="Registered account owners" />
            <Kpi label="Schools matched"     value={String(ownership.matched)}    sub="Auto-distributed to portfolios" tone="green" />
            <Kpi label="Owner unmatched"     value={String(ownership.unmatched)}  sub="Need IA mapping"  tone={ownership.unmatched > 0 ? "amber" : "green"} />
            <Kpi label="No owner set"        value={String(ownership.unassigned)} sub="Awaiting assignment" tone={ownership.unassigned > 0 ? "rose" : "green"} />
          </section>

          {openDuplicates.length > 0 && (
            <Link href="/data-intake/duplicates"
              className="flex items-center gap-3 card p-3.5 border-amber-200 bg-amber-50/60 hover:bg-amber-50 transition-colors">
              <ShieldAlert size={18} className="text-amber-600 shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-[12.5px] font-extrabold tracking-tight">
                  {openDuplicates.length} possible duplicate{openDuplicates.length === 1 ? "" : "s"} to review
                </div>
                <div className="text-[11px] muted">
                  Schools were flagged on upload as look-alikes — review and confirm or dismiss. Nothing is blocked.
                </div>
              </div>
              <ChevronRight size={16} className="text-amber-600 shrink-0" />
            </Link>
          )}

          <OwnerMappingQueue
            unmatched={unmatchedOwnerList.map((u) => ({
              name: u.name,
              count: u.count,
              schoolNames: u.schools.map((s) => `${s.schoolName} (${s.schoolId})`),
            }))}
            staff={mappableStaff}
          />
        </>
      )}

      {/* KPIs */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi label="Templates available" value={String(dataTemplates.length)} sub="System-generated" />
        <Kpi label="Batches imported"    value={String(importedCount)}        sub="Live in the planning engine" tone="green" />
        <Kpi label="Pending review"      value={String(pendingBatches)}       sub="Validation queue + reviews"  tone={pendingBatches > 0 ? "amber" : "edify"} />
        <Kpi label="Readiness areas blocked" value={String(blockedAreas)}     sub={`${attentionAreas} need attention`} tone={blockedAreas > 0 ? "rose" : "green"} />
      </section>

      {/* Readiness verdict */}
      <section className={cn(
        "card p-3.5 flex items-start gap-3",
        r.overall === "Ready"           && "border-emerald-200 bg-emerald-50",
        r.overall === "Needs Attention" && "border-amber-200 bg-amber-50",
        r.overall === "Blocked"         && "border-rose-200 bg-rose-50",
      )}>
        <span className={cn(
          "h-10 w-10 rounded-xl grid place-items-center shrink-0",
          r.overall === "Ready"           && "bg-emerald-100 text-emerald-700",
          r.overall === "Needs Attention" && "bg-amber-100   text-amber-700",
          r.overall === "Blocked"         && "bg-rose-100    text-rose-700",
        )}>
          {r.overall === "Ready" ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
        </span>
        <div className="flex-1 min-w-0">
          <h2 className="text-[14.5px] font-extrabold tracking-tight">Planning data readiness: {r.overall}</h2>
          <p className="text-[11.5px] muted">
            The Annual Operating Cycle checks readiness before opening a new FY, generating Gateway training,
            producing SSA-informed recommendations, building annual budgets, or activating monthly funding plans.
          </p>
          <Link href="/data-intake/readiness" className="text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline mt-1 inline-block">
            Open Planning Data Readiness →
          </Link>
        </div>
      </section>

      {/* Section nav */}
      <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        <Tile href="/data-intake/templates" Icon={FileSpreadsheet} title="Template Builder"        body="Three consolidated upload templates — school, SSA, and activity." />
        <Tile href="/data-intake/upload"    Icon={Upload}          title="Upload Center"           body="Download a template, upload, validate, correct, submit." />
        <Tile href="/data-intake/queue"     Icon={ListChecks}      title="Validation Queue"        body="Per-batch error / warning counts, review actions." />
        <Tile href="/data-intake/readiness" Icon={ShieldCheck}     title="Planning Data Readiness" body="Traffic-light gate the planning engine reads." />
        <Tile href="/data-intake/quality"   Icon={ShieldAlert}     title="Data Quality Center"     body="Integrity scan: missing region, enrollment, unassessed schools." />
      </section>

      {/* Recent batches */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="text-body-lg font-extrabold tracking-tight">Recent import batches</h2>
          <Link href="/data-intake/queue" className="text-[11.5px] font-semibold text-[var(--color-edify-primary)]">
            Open Queue →
          </Link>
        </header>
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {dataImportBatches.slice(0, 6).map((b) => (
            <li key={b.id} className="py-2.5 flex items-center gap-3">
              <span className="h-9 w-9 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                <FileSpreadsheet size={14} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-body font-extrabold tracking-tight truncate">{b.sourceFileName}</div>
                <div className="text-caption muted truncate">
                  {b.dataType} · {b.totalRows} rows · {b.uploadedBy} · {b.uploadedAt}
                </div>
              </div>
              <span className={cn(
                "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap",
                b.status === "Imported"           && "bg-emerald-100 text-emerald-700",
                b.status === "Ready for Review"   && "bg-sky-100     text-sky-700",
                b.status === "Validated"          && "bg-violet-100  text-violet-700",
                b.status === "Needs Correction"   && "bg-rose-100    text-rose-700",
                b.status === "Uploaded"           && "bg-slate-100   text-slate-700",
                b.status === "Approved for Import"&& "bg-emerald-100 text-emerald-700",
                b.status === "Rejected"           && "bg-rose-100    text-rose-700",
              )}>{b.status}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="card p-3.5 text-[11.5px] muted">
        <span className="font-extrabold text-[var(--color-edify-text)]">Contract: </span>
        Uploaded → Validated → Needs Correction / Ready for Review → Approved for Import → Imported → Available
        to Planning Engine. Unapproved data does not feed dashboards, recommendations, budgets, targets,
        leaderboards, or reports.
      </section>
    </StubPage>
  );
}

function Kpi({ label, value, sub, tone = "edify" }: { label: string; value: string; sub: string; tone?: "edify" | "green" | "amber" | "rose" }) {
  const TONE = {
    edify: "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
    green: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100   text-amber-700",
    rose:  "bg-rose-100    text-rose-700",
  } as const;
  return (
    <div className="card p-3.5">
      <div className={cn("text-[11.5px] font-semibold inline-flex items-center px-2 py-[2px] rounded-md", TONE[tone])}>{label}</div>
      <div className="text-[24px] font-extrabold tabular leading-none mt-2">{value}</div>
      <div className="text-caption muted mt-1">{sub}</div>
    </div>
  );
}

function Tile({ href, Icon, title, body }: { href: string; Icon: typeof FileSpreadsheet; title: string; body: string }) {
  return (
    <Link href={href} className="card p-3.5 flex items-start gap-3 hover:bg-[var(--color-edify-soft)]/40 transition-colors">
      <span className="h-10 w-10 rounded-xl bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
        <Icon size={18} />
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-[13.5px] font-extrabold tracking-tight">{title}</h3>
          <ChevronRight size={13} className="text-[var(--color-edify-muted)]" />
        </div>
        <p className="text-[11.5px] muted leading-snug mt-0.5">{body}</p>
      </div>
    </Link>
  );
}
