import { Lock, Handshake, Building2, GraduationCap } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { getCurrentUser } from "@/lib/auth";
import { portfolioForStaffId } from "@/lib/portfolio/portfolio";
import { activePartnerAssignmentsForSchool, schoolIdsWithActivePartner } from "@/lib/portfolio/partner-assignments";
import { PortfolioSchoolList } from "@/components/portfolio/PortfolioSchoolList";
import { TargetsByTimePeriodCard } from "@/components/portfolio/TargetsByTimePeriodCard";
import { SSA_INTERVENTION_AREAS, deriveQuarterFromDate } from "@/lib/intake/intake-core";
import { computePeriodTarget } from "@/lib/targets/period-target";
import { activeFinancialYear } from "@/lib/fy-engine";
import { engineNowIso } from "@/lib/clock";
import { cn } from "@/lib/utils";

const PARTNER_SUGGESTIONS = [
  "Hope Education Partners",
  "Bright Future Education Partners",
  "Literacy Training Uganda",
  "Numeracy First",
  "Northern Education Trust",
  "Mastercard Foundation",
];

export default async function MyPortfolioPage() {
  const me = await getCurrentUser();
  const portfolio = portfolioForStaffId(me.staffId);
  const c = portfolio.counts;

  // Targets by time period — cumulative against the portfolio (Q1 25% · Q2 50%
  // /Mid-Year · Q3 75% · Q4 100%). A school counts as "supported" once its first
  // SSA is done OR a partner is actively delivering there — so partner-supported
  // schools count toward the target while ownership stays with the staff.
  const fy = activeFinancialYear();
  const withPartner = schoolIdsWithActivePartner();
  const supported = portfolio.schools.filter(
    (s) => s.ssaStatus === "SSA Done" || withPartner.has(s.schoolId),
  ).length;
  const currentQuarter = deriveQuarterFromDate(engineNowIso());
  const periodTarget = computePeriodTarget({
    fyTarget: c.total,
    achieved: supported,
    selectedQuarter: currentQuarter,
  });

  return (
    <StubPage
      title="My School Portfolio"
      subtitle="Every school you own. Schools auto-appear here the moment they're uploaded with you as the Account Owner. Partner assignment only delegates delivery — your schools stay yours."
    >
      {/* Counts */}
      <section className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <Stat label="Total schools"      value={c.total}          tone="edify" Icon={Building2} />
        <Stat label="Client schools"     value={c.client}         tone="slate" />
        <Stat label="Core schools"       value={c.core}           tone="violet" Icon={GraduationCap} />
        <Stat label="Awaiting first SSA" value={c.missingSsa}     tone={c.missingSsa > 0 ? "amber" : "green"} Icon={Lock} />
        <Stat label="Partner-delegated"  value={c.partnerAssigned} tone="sky" Icon={Handshake} />
      </section>

      {portfolio.schools.length > 0 && (
        <TargetsByTimePeriodCard
          fyLabel={fy.label}
          fyTarget={c.total}
          achieved={supported}
          partnerSupported={c.partnerAssigned}
          currentQuarter={currentQuarter}
          expectedCumulative={periodTarget.expectedCumulative}
          paceStatus={periodTarget.paceStatus}
        />
      )}

      {portfolio.schools.length === 0 ? (
        <section className="card p-6 text-center">
          <Building2 className="mx-auto text-[var(--color-edify-muted)]" size={28} />
          <h2 className="text-[13px] font-extrabold tracking-tight mt-2">No schools in your portfolio yet</h2>
          <p className="text-[11.5px] muted max-w-md mx-auto mt-1">
            When Impact Assessment uploads a school with <span className="font-extrabold">{me.name}</span> as the
            Account Owner, it will appear here automatically — no extra step.
          </p>
        </section>
      ) : (
        <PortfolioSchoolList
          partnerOptions={PARTNER_SUGGESTIONS}
          interventionAreas={[...SSA_INTERVENTION_AREAS]}
          schools={portfolio.schools.map((s) => ({
            schoolId: s.schoolId,
            schoolName: s.schoolName,
            schoolType: s.schoolType,
            district: s.district,
            region: s.region,
            enrollment: s.enrollment,
            planningLocked: s.planningLocked,
            delegations: activePartnerAssignmentsForSchool(s.schoolId).map((p) => ({
              id: p.id, partnerName: p.partnerName, interventionArea: p.interventionArea,
            })),
          }))}
        />
      )}

      <section className="card p-3.5 text-[11.5px] muted">
        <span className="font-extrabold text-[var(--color-edify-text)]">How this works: </span>
        Your portfolio is the single source of truth for your schools across your dashboard, planning, and analytics.
        Impact Assessment owns upload, duplicate cleanup, and owner mapping. When a partner is assigned to one of your
        schools, they deliver the activity on your behalf — the school is never removed from your portfolio and
        ownership is never transferred.
      </section>
    </StubPage>
  );
}

const TONE: Record<string, string> = {
  edify:  "text-[var(--color-edify-primary)]",
  slate:  "text-slate-700",
  violet: "text-violet-700",
  amber:  "text-amber-700",
  green:  "text-emerald-700",
  sky:    "text-sky-700",
};

function Stat({ label, value, tone, Icon }: { label: string; value: number; tone: string; Icon?: React.ComponentType<{ size?: number; className?: string }> }) {
  return (
    <div className="card p-3">
      <div className="flex items-center gap-1.5">
        {Icon && <Icon size={13} className={cn("shrink-0", TONE[tone])} />}
        <span className="text-[10.5px] muted font-semibold truncate">{label}</span>
      </div>
      <div className={cn("text-[22px] font-extrabold tabular tracking-tight mt-0.5", TONE[tone])}>{value}</div>
    </div>
  );
}
