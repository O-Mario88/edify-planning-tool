import Link from "next/link";
import { Lock, CheckCircle2, Handshake, Building2, GraduationCap } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { getCurrentUser } from "@/lib/auth";
import { portfolioForStaffId } from "@/lib/portfolio/portfolio";
import { activePartnerAssignmentsForSchool } from "@/lib/portfolio/partner-assignments";
import { SchoolPartnerControl } from "@/components/portfolio/SchoolPartnerControl";
import { SSA_INTERVENTION_AREAS } from "@/lib/intake/intake-core";
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
        <section className="card p-0 overflow-hidden">
          <div className="flex items-center justify-between px-3.5 py-2.5 border-b border-[var(--color-edify-divider)]">
            <h2 className="text-[12.5px] font-extrabold tracking-tight">Schools you own ({portfolio.schools.length})</h2>
            <span className="text-[10.5px] muted">Ownership stays with you even when work is delegated.</span>
          </div>
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {portfolio.schools.map((s) => {
              const partners = activePartnerAssignmentsForSchool(s.schoolId);
              return (
                <li key={s.schoolId} className="px-3.5 py-3 flex items-center gap-3">
                  <span className="h-9 w-9 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0 text-[10px] font-extrabold">
                    {s.schoolType.slice(0, 2).toUpperCase()}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-body font-extrabold tracking-tight truncate">{s.schoolName}</div>
                    <div className="text-caption muted truncate">
                      {s.schoolId} · {s.district}, {s.region} · {s.schoolType}
                      {s.enrollment != null ? ` · ${s.enrollment} learners` : ""}
                    </div>
                    <div className="mt-1.5">
                      <SchoolPartnerControl
                        schoolId={s.schoolId}
                        schoolName={s.schoolName}
                        delegations={partners.map((p) => ({ id: p.id, partnerName: p.partnerName, interventionArea: p.interventionArea }))}
                        partnerOptions={PARTNER_SUGGESTIONS}
                        interventionAreas={[...SSA_INTERVENTION_AREAS]}
                      />
                    </div>
                  </div>
                  {s.planningLocked ? (
                    <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold bg-amber-100 text-amber-700 whitespace-nowrap">
                      <Lock size={10} /> SSA pending
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold bg-emerald-100 text-emerald-700 whitespace-nowrap">
                      <CheckCircle2 size={10} /> Planning open
                    </span>
                  )}
                  <Link href="/planning" className="text-[11px] font-semibold text-[var(--color-edify-primary)] hover:underline whitespace-nowrap">
                    Plan →
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
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
