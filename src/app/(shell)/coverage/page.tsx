import Link from "next/link";
import {
  Building2,
  Users,
  Briefcase,
  ShieldCheck,
  AlertTriangle,
  ChevronRight,
  Handshake,
  Sparkles,
} from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import {
  cceoCoverageRows,
  plCoverageRows,
  partnerCoverageRows,
  coverageKpis,
  generatePartnerAssignmentRecommendations,
  CCEO_ANNUAL_TARGET,
  PL_ANNUAL_TARGET,
  MIN_DAILY_VISITS,
  MAX_DAILY_GROUP_TRAININGS,
  COVERAGE_FY,
  type CovPaceStatus,
  type PartnerCertification,
} from "@/lib/coverage-mock";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<CovPaceStatus, string> = {
  "Ahead":     "bg-emerald-100 text-emerald-700",
  "On Track":  "bg-emerald-100 text-emerald-700",
  "Behind":    "bg-amber-100   text-amber-700",
  "High Risk": "bg-rose-100    text-rose-700",
  "Critical":  "bg-rose-100    text-rose-700",
};

const CERT_TONE: Record<PartnerCertification, string> = {
  "Certified":     "bg-emerald-100 text-emerald-700",
  "Probationary":  "bg-amber-100   text-amber-700",
  "Suspended":     "bg-rose-100    text-rose-700",
};

export default function ClientSchoolCoveragePage() {
  const k = coverageKpis();
  const recs = generatePartnerAssignmentRecommendations();
  const topRec = recs[0];

  return (
    <StubPage
      title="Client School Coverage"
      subtitle={`${COVERAGE_FY.label}. Every CCEO must visit ${CCEO_ANNUAL_TARGET} client schools/yr. Every Program Lead must visit ${PL_ANNUAL_TARGET}. Schools beyond staff capacity are assigned to certified partners — never left unassigned.`}
    >
      {/* Headline KPIs */}
      <section className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <Kpi label="Total client schools"  value={k.totalClientSchools.toLocaleString()} sub={`${COVERAGE_FY.label}`}   tone="edify" />
        <Kpi label="Assigned to CCEOs"      value={k.assignedToCceos.toLocaleString()}    sub={`${k.cceoCoveragePct}% of total`} tone="green" />
        <Kpi label="Assigned to Program Leads" value={k.assignedToPls.toLocaleString()}  sub="Supervisory visits"        tone="amber" />
        <Kpi label="Assigned to Partners"   value={k.assignedToPartners.toLocaleString()} sub={`${k.partnerCoveragePct}% of total`} tone="violet" />
        <Kpi label="Unassigned"             value={k.unassigned.toLocaleString()}         sub={k.unassigned === 0 ? "Full coverage" : "Needs partner match"} tone={k.unassigned === 0 ? "green" : "rose"} />
        <Kpi label="High-risk schools covered" value={k.highRiskCovered.toLocaleString()} sub="Routed to certified partners" tone="rose" />
        <Kpi label="Schools below SSA threshold" value={k.schoolsBelowSsaThreshold.toLocaleString()} sub="Current FY SSA < 5" tone="amber" />
        <Kpi label="CCEO coverage"         value={`${k.cceoCoveragePct}%`}                sub="Of all client schools"        tone="green" />
        <Kpi label="Partner coverage"      value={`${k.partnerCoveragePct}%`}             sub="Of all client schools"        tone="violet" />
        <Kpi label="Daily min visits"      value={`${MIN_DAILY_VISITS}`}                  sub={`Max ${MAX_DAILY_GROUP_TRAININGS} group training/day`} tone="edify" />
      </section>

      {/* Smart recommendation banner */}
      {topRec && (
        <section className="card p-3.5 border-violet-200 bg-violet-50/40">
          <div className="flex items-start gap-3">
            <span className="h-10 w-10 rounded-xl bg-violet-100 text-violet-700 grid place-items-center shrink-0">
              <Sparkles size={16} />
            </span>
            <div className="flex-1 min-w-0">
              <h2 className="text-body-lg font-extrabold tracking-tight">Smart partner assignment</h2>
              <p className="text-[11.5px] muted leading-snug mt-0.5">
                Assign <span className="font-extrabold text-[var(--color-edify-text)]">{topRec.recommendedPartner.partnerName}</span> to{" "}
                <span className="font-extrabold text-[var(--color-edify-text)]">{topRec.schoolBatch}</span>:
                they are {topRec.recommendedPartner.certification}, have {topRec.recommendedPartner.capacityPct}% capacity, and specialise in {topRec.recommendedPartner.specialization}.
              </p>
              <Link href="/coverage/recommendations" className="inline-flex items-center gap-1 mt-2 text-[11.5px] font-semibold text-violet-700 hover:underline">
                Open all {recs.length} recommendation{recs.length === 1 ? "" : "s"}
                <ChevronRight size={11} />
              </Link>
            </div>
          </div>
        </section>
      )}

      {/* CCEO coverage table */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
            <Briefcase size={14} className="text-[var(--color-edify-primary)]" />
            CCEO coverage
          </h2>
          <span className="text-caption muted">{cceoCoverageRows.length} CCEOs · target {CCEO_ANNUAL_TARGET} schools/FY</span>
        </header>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px] min-w-[760px]">
            <thead>
              <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                <th scope="col" className="py-2 pr-2">CCEO</th>
                <th scope="col" className="py-2 px-2">District / Cluster</th>
                <th scope="col" className="py-2 px-2 text-right">Assigned</th>
                <th scope="col" className="py-2 px-2 text-right">Completed</th>
                <th scope="col" className="py-2 px-2 text-right">Remaining</th>
                <th scope="col" className="py-2 px-2 text-right">Pace</th>
                <th scope="col" className="py-2 px-2 text-right">Avg/day · Compliance</th>
                <th scope="col" className="py-2 pl-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {cceoCoverageRows.map((r) => (
                <tr key={r.staffId} className="hover:bg-[var(--color-edify-soft)]/30">
                  <td className="py-2.5 pr-2">
                    <Link href={`/staff/${r.staffId}`} className="text-body font-extrabold tracking-tight hover:text-[var(--color-edify-primary)]">
                      {r.staffName}
                    </Link>
                    <div className="text-caption muted">{r.region}</div>
                  </td>
                  <td className="py-2.5 px-2 muted">{r.district}{r.cluster ? ` · ${r.cluster}` : ""}</td>
                  <td className="py-2.5 px-2 text-right tabular">{r.assignedSchools}</td>
                  <td className="py-2.5 px-2 text-right tabular font-extrabold">{r.completedVisits}</td>
                  <td className="py-2.5 px-2 text-right tabular">{r.remainingVisits}</td>
                  <td className="py-2.5 px-2 text-right tabular font-extrabold">{r.monthlyPacePct}%</td>
                  <td className="py-2.5 px-2 text-right tabular">
                    <span className={r.dailyAvgLast14 >= MIN_DAILY_VISITS ? "text-emerald-700" : "text-rose-700"}>
                      {r.dailyAvgLast14.toFixed(1)}/day
                    </span>
                    <span className="muted ml-1">· {r.dailyCompliancePct}%</span>
                  </td>
                  <td className="py-2.5 pl-2">
                    <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", STATUS_TONE[r.status])}>
                      {r.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-[var(--color-edify-border)]">
                <td colSpan={2} className="py-2 pr-2 text-right font-extrabold">Totals</td>
                <td className="py-2 px-2 text-right tabular font-extrabold">{cceoCoverageRows.reduce((a, r) => a + r.assignedSchools, 0).toLocaleString()}</td>
                <td className="py-2 px-2 text-right tabular font-extrabold">{cceoCoverageRows.reduce((a, r) => a + r.completedVisits, 0).toLocaleString()}</td>
                <td className="py-2 px-2 text-right tabular">{cceoCoverageRows.reduce((a, r) => a + r.remainingVisits, 0).toLocaleString()}</td>
                <td colSpan={3} />
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      {/* Program Lead coverage table */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
            <Users size={14} className="text-[var(--color-edify-primary)]" />
            Program Lead coverage
          </h2>
          <span className="text-caption muted">{plCoverageRows.length} PLs · target {PL_ANNUAL_TARGET} supervisory visits/FY</span>
        </header>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px] min-w-[760px]">
            <thead>
              <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                <th scope="col" className="py-2 pr-2">Program Lead</th>
                <th scope="col" className="py-2 px-2">Team / Region</th>
                <th scope="col" className="py-2 px-2 text-right">Target</th>
                <th scope="col" className="py-2 px-2 text-right">Completed</th>
                <th scope="col" className="py-2 px-2 text-right">Remaining</th>
                <th scope="col" className="py-2 px-2 text-right">Coverage %</th>
                <th scope="col" className="py-2 px-2 text-right">Schools / Districts</th>
                <th scope="col" className="py-2 pl-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {plCoverageRows.map((r) => (
                <tr key={r.staffId} className="hover:bg-[var(--color-edify-soft)]/30">
                  <td className="py-2.5 pr-2">
                    <span className="text-body font-extrabold tracking-tight">{r.staffName}</span>
                    <div className="text-caption muted">{r.staffId}</div>
                  </td>
                  <td className="py-2.5 px-2 muted">{r.team} · {r.region}</td>
                  <td className="py-2.5 px-2 text-right tabular">{r.annualTarget}</td>
                  <td className="py-2.5 px-2 text-right tabular font-extrabold">{r.completedVisits}</td>
                  <td className="py-2.5 px-2 text-right tabular">{r.remainingVisits}</td>
                  <td className="py-2.5 px-2 text-right tabular font-extrabold">{r.coveragePct}%</td>
                  <td className="py-2.5 px-2 text-right tabular">{r.schoolsVisited} / {r.districtCoverage}</td>
                  <td className="py-2.5 pl-2">
                    <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", STATUS_TONE[r.status])}>
                      {r.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Partner coverage table */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
            <Handshake size={14} className="text-[var(--color-edify-primary)]" />
            Partner coverage
          </h2>
          <span className="text-caption muted">{partnerCoverageRows.length} partners</span>
        </header>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px] min-w-[760px]">
            <thead>
              <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                <th scope="col" className="py-2 pr-2">Partner</th>
                <th scope="col" className="py-2 px-2">Cert.</th>
                <th scope="col" className="py-2 px-2">Region / Districts</th>
                <th scope="col" className="py-2 px-2">Specialization</th>
                <th scope="col" className="py-2 px-2 text-right">Assigned</th>
                <th scope="col" className="py-2 px-2 text-right">High-risk</th>
                <th scope="col" className="py-2 px-2 text-right">Verified</th>
                <th scope="col" className="py-2 px-2 text-right">Capacity</th>
                <th scope="col" className="py-2 px-2 text-right">Pass / SF</th>
                <th scope="col" className="py-2 pl-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {partnerCoverageRows.map((r) => (
                <tr key={r.partnerId} className="hover:bg-[var(--color-edify-soft)]/30">
                  <td className="py-2.5 pr-2">
                    <Link href={`/partners/${r.partnerId}`} className="text-body font-extrabold tracking-tight hover:text-[var(--color-edify-primary)]">
                      {r.partnerName}
                    </Link>
                    <div className="text-caption muted">{r.partnerId}</div>
                  </td>
                  <td className="py-2.5 px-2">
                    <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", CERT_TONE[r.certification])}>
                      <ShieldCheck size={9} className="mr-0.5" />
                      {r.certification}
                    </span>
                  </td>
                  <td className="py-2.5 px-2 muted truncate max-w-[200px]">{r.region} · {r.districts.join(", ")}</td>
                  <td className="py-2.5 px-2 muted">{r.specialization}</td>
                  <td className="py-2.5 px-2 text-right tabular">{r.assignedSchools}</td>
                  <td className="py-2.5 px-2 text-right tabular text-rose-700 font-extrabold">{r.highRiskAssignments}</td>
                  <td className="py-2.5 px-2 text-right tabular font-extrabold">{r.verifiedVisits}</td>
                  <td className="py-2.5 px-2 text-right tabular">{r.capacityPct}%</td>
                  <td className="py-2.5 px-2 text-right tabular muted">
                    {r.verificationPassRate}% / {r.salesforceCompliancePct}%
                  </td>
                  <td className="py-2.5 pl-2">
                    <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", STATUS_TONE[r.status])}>
                      {r.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Planning rules contract */}
      <section className="card p-3.5 text-[11.5px] muted">
        <span className="font-extrabold text-[var(--color-edify-text)]">Planning rules: </span>
        Every CCEO covers ≥ {CCEO_ANNUAL_TARGET} client schools per FY. Every Program Lead covers ≥ {PL_ANNUAL_TARGET}.
        Minimum {MIN_DAILY_VISITS} client visits per CCEO per day. Maximum {MAX_DAILY_GROUP_TRAININGS} group training per staff/partner per day.
        Schools beyond staff capacity are assigned to certified partners — never left unassigned. Only verified visits count toward coverage. Non-certified partner visits do not count.
      </section>
    </StubPage>
  );
}

type KpiTone = "edify" | "green" | "amber" | "rose" | "violet";
const TONE: Record<KpiTone, string> = {
  edify:  "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
  green:  "bg-emerald-100 text-emerald-700",
  amber:  "bg-amber-100   text-amber-700",
  rose:   "bg-rose-100    text-rose-700",
  violet: "bg-violet-100  text-violet-700",
};

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub: string; tone: KpiTone }) {
  return (
    <div className="card p-3.5">
      <div className={cn("text-caption font-semibold inline-flex items-center px-1.5 py-[2px] rounded-md", TONE[tone])}>{label}</div>
      <div className="text-[22px] font-extrabold tabular leading-none mt-2">{value}</div>
      <div className="text-caption muted mt-1">{sub}</div>
    </div>
  );
}

// Imports below are used by lucide; keep referenced.
export const _icons = { Building2, AlertTriangle };
