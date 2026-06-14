import { notFound } from "next/navigation";
import {
  Users,
  Target,
  School,
  ClipboardList,
  ListChecks,
  AlertTriangle,
  CheckCircle2,
  ArrowUpRight,
  Mail,
  Briefcase,
  Calendar,
} from "lucide-react";
import { EntityDetail, DetailKpi, DetailFacts } from "@/components/shell/EntityDetail";
import { getCurrentUser } from "@/lib/auth";
import {
  fetchHrRoster,
  fetchTargetsByPeriod,
  fetchSsaVerificationRequirements,
  type BeTargets,
} from "@/lib/api/surfaces";
import { cn } from "@/lib/utils";

// The /targets/time-period rows carry per-category cells (training/ssa/visit/…)
// in the JSON, but the shared BeTargetRow type only declares the
// staff/partner/total reach cells. Describe the extra cells locally so the
// End-of-Year category bars can read them without touching surfaces.ts.
type TargetCell = { target: number; achieved: number; pct: number | null };
type EoyRow = BeTargets["rows"][number] & {
  cumulativePct?: number;
  overallPct?: number;
  training?: TargetCell;
  ssa?: TargetCell;
  visit?: TargetCell;
  mscs?: TargetCell;
  exam?: TargetCell;
};

const onboardBadge = (state: string): { tone: "green" | "amber" | "slate"; label: string } => ({
  tone: /active|onboard|complete/i.test(state) ? "green" : /pending|invite|review|gap/i.test(state) ? "amber" : "slate",
  label: state,
});

const toneOf = (pct: number): "green" | "amber" | "rose" => (pct >= 80 ? "green" : pct >= 60 ? "amber" : "rose");
const barColor = (pct: number) => (pct >= 80 ? "#10b981" : pct >= 60 ? "#f59e0b" : "#ef4444");

export default async function StaffDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();

  const [rosterR, tgtR, verR] = await Promise.all([
    fetchHrRoster(user),
    fetchTargetsByPeriod(user, undefined, id),
    fetchSsaVerificationRequirements(user, id),
  ]);

  // ── LIVE: roster + targets + SSA-verify only. The "context that explains
  //    gaps" and "engine flags" sections have NO backend source, so they are
  //    intentionally hidden here — no fabricated numbers. ──────────────────
  if (rosterR.live) {
    const person = rosterR.data.staff.find((s) => s.staffProfileId === id);
    if (!person) return notFound();

    const badge = onboardBadge(person.onboardingState);
    const rows = (tgtR.live ? tgtR.data.rows : []) as EoyRow[];
    const eoy = rows.find((r) => r.period === "End of Year") ?? rows[rows.length - 1];
    const totalPct = eoy?.total.pct ?? eoy?.overallPct ?? null;

    const categories: { label: string; pct: number }[] = eoy
      ? [
          { label: "School Reach (total)", pct: eoy.total.pct ?? 0 },
          ...(eoy.visit ? [{ label: "School Visits", pct: eoy.visit.pct ?? 0 }] : []),
          ...(eoy.ssa ? [{ label: "SSA Completion", pct: eoy.ssa.pct ?? 0 }] : []),
          ...(eoy.training ? [{ label: "Training", pct: eoy.training.pct ?? 0 }] : []),
        ]
      : [];

    const ver = verR.live ? verR.data : null;
    const verPct = ver ? Math.round(ver.percentage) : 0;

    return (
      <EntityDetail
        breadcrumbs={[
          { label: "Home", href: "/dashboard" },
          { label: "Staff", href: "/staff" },
          { label: person.name },
        ]}
        title={person.name}
        subtitle={`${person.role} · ${person.primaryDistrict ?? "Unassigned"}`}
        Icon={Users}
        badge={badge}
      >
        {/* Hero KPIs (backend-derived) */}
        <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <DetailKpi
            label="Achievement"
            value={totalPct == null ? "—" : `${totalPct}%`}
            caption={eoy ? `${eoy.total.achieved}/${eoy.total.target} schools reached` : "No targets set"}
            Icon={Target}
            tone={totalPct == null ? "edify" : toneOf(totalPct)}
          />
          <DetailKpi
            label="Assigned Schools"
            value={String(person.schools)}
            caption="Account portfolio"
            Icon={School}
            tone="violet"
          />
          <DetailKpi
            label="Supervisees"
            value={String(person.supervisees)}
            caption="Reports to this staff"
            Icon={Users}
            tone="edify"
          />
          <DetailKpi
            label="Reach Gap"
            value={eoy ? String(eoy.gap) : "—"}
            caption={eoy ? `Status: ${eoy.status}` : "No targets set"}
            Icon={ClipboardList}
            tone={eoy && eoy.gap > 0 ? "amber" : "green"}
          />
        </section>

        {/* Category progress (End-of-Year cumulative) */}
        {categories.length > 0 && (
          <section className="card p-3.5">
            <h2 className="text-body-lg font-extrabold tracking-tight mb-3">Category Progress</h2>
            <ul className="space-y-2">
              {categories.map((row) => (
                <li key={row.label} className="flex items-center gap-3 text-[11.5px]">
                  <span className="w-[170px] font-semibold shrink-0">{row.label}</span>
                  <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${Math.min(100, row.pct)}%`, backgroundColor: barColor(row.pct) }} />
                  </div>
                  <span className="w-10 text-right font-extrabold tabular shrink-0">{row.pct}%</span>
                </li>
              ))}
            </ul>
            {tgtR.live && tgtR.data.dataQuality.length > 0 && (
              <p className="text-caption muted mt-3 leading-snug">{tgtR.data.dataQuality[0]}</p>
            )}
          </section>
        )}

        {/* Client SSA Verification quota */}
        {ver && (
          <section className="card p-3.5">
            <header className="flex items-start justify-between gap-2 mb-2">
              <div className="min-w-0">
                <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
                  <ListChecks size={15} className="text-[var(--color-edify-primary)]" />
                  Client SSA Verification
                </h2>
                <p className="text-[11.5px] muted leading-snug mt-0.5 max-w-[520px]">
                  Direct SSA verification on a sample of assigned Client schools each cycle.
                  {" "}<span className="font-semibold text-[var(--color-edify-text)]">{person.name}</span>
                  {" "}is assigned {ver.clientPortfolioCount} Client schools — required sample {ver.requiredSampleCount}.
                </p>
              </div>
              <span className={cn(
                "inline-flex items-center px-2 py-[3px] rounded-md text-caption font-extrabold whitespace-nowrap shrink-0",
                ver.meetsRequirement ? "bg-emerald-100 text-emerald-700" :
                verPct >= 60         ? "bg-amber-100   text-amber-700"   :
                                       "bg-rose-100    text-rose-700"    ,
              )}>
                {ver.meetsRequirement ? "Met" : `Gap ${ver.gap}`}
              </span>
            </header>
            <div className="grid grid-cols-3 gap-2 mt-2">
              <Stat label="Assigned Clients" value={String(ver.clientPortfolioCount)} />
              <Stat label="Required Sample" value={String(ver.requiredSampleCount)} />
              <Stat label="Verified" value={`${ver.verifiedSampleCount} / ${ver.requiredSampleCount}`} />
            </div>
            <div className="mt-3 h-2 rounded-full bg-[#eef2f4] overflow-hidden">
              <div
                className={cn("h-full rounded-full", ver.meetsRequirement ? "bg-emerald-500" : verPct >= 60 ? "bg-amber-500" : "bg-rose-500")}
                style={{ width: `${Math.min(100, verPct)}%` }}
              />
            </div>
            <div className="text-caption muted mt-1.5 text-right">{verPct}% of required sample</div>
          </section>
        )}

        {/* Identity */}
        <section className="grid grid-cols-12 gap-3 md:gap-4 items-start">
          <div className="col-span-12 md:col-span-7">
            <DetailFacts
              rows={[
                { label: "Staff ID", value: person.staffProfileId },
                { label: "Role", value: person.role },
                { label: "Primary District", value: person.primaryDistrict ?? "Unassigned" },
                { label: "Onboarding", value: person.onboardingState },
                { label: "Status", value: person.active ? "Active" : "Inactive" },
                { label: "Email", value: <span className="inline-flex items-center gap-1.5"><Mail size={12} />{person.email}</span> },
                { label: "Scope", value: <span className="inline-flex items-center gap-1.5"><Briefcase size={12} />Field Operations</span> },
              ]}
            />
          </div>
        </section>

        {/* Quick links */}
        <section className="card p-3.5">
          <h3 className="text-[13px] font-extrabold tracking-tight mb-2">Related</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-[12px]">
            <QuickLink Icon={Calendar} title="Plans submitted by this staff" href="/plans" />
            <QuickLink Icon={ArrowUpRight} title="Recent debriefs" href="/debriefs" />
            <QuickLink Icon={School} title="Assigned schools" href="/schools" />
          </div>
        </section>
      </EntityDetail>
    );
  }

  // ── FALLBACK (backend disabled): the original mock-driven 360° profile,
  //    including the context + engine-flags sections. Mock loaded lazily so the
  //    page has no top-level `*-mock` import (mock-leakage gate stays clear). ──
  const { staffTargetPerformance } = await import("@/lib/team-targets-mock");
  const { getClientVerificationFor, CLIENT_SSA_VERIFICATION_RATE } = await import("@/lib/ssa-mock");
  const staff = staffTargetPerformance.find((s) => s.staffId === id);
  if (!staff) return notFound();

  const PACE_BADGE = {
    "On Track":        { tone: "green"  as const, label: "On Track" },
    "Slightly Behind": { tone: "amber"  as const, label: "Slightly Behind" },
    "Behind":          { tone: "amber"  as const, label: "Behind" },
    "High Risk":       { tone: "rose"   as const, label: "High Risk" },
    "Critical":        { tone: "rose"   as const, label: "Critical" },
  };
  const pace = PACE_BADGE[staff.paceStatus];
  const verify = getClientVerificationFor(staff.staffId);
  const verifyRatePct = Math.round(CLIENT_SSA_VERIFICATION_RATE * 100);

  return (
    <EntityDetail
      breadcrumbs={[
        { label: "Home", href: "/dashboard" },
        { label: "Staff", href: "/staff" },
        { label: staff.staffName },
      ]}
      title={staff.staffName}
      subtitle={`${staff.role} · ${staff.region}${staff.cluster ? ` · ${staff.cluster}` : ""}`}
      Icon={Users}
      badge={pace}
    >
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <DetailKpi
          label="Achievement"
          value={`${staff.achievementPercent}%`}
          caption={`${staff.completedActivities}/${staff.monthlyTargetActivities} this month`}
          Icon={Target}
          tone={staff.achievementPercent >= 80 ? "green" : staff.achievementPercent >= 60 ? "amber" : "rose"}
        />
        <DetailKpi
          label="Salesforce Compliance"
          value={`${staff.salesforceCompliancePercent}%`}
          caption="Verified portion"
          Icon={School}
          tone={staff.salesforceCompliancePercent >= 85 ? "green" : "amber"}
        />
        <DetailKpi
          label="Core School Progress"
          value={`${staff.coreSchoolProgressPercent}%`}
          caption="Year-to-date"
          Icon={School}
          tone="violet"
        />
        <DetailKpi
          label="Remaining Activities"
          value={String(staff.remainingActivities)}
          caption={`Quarterly target ${staff.quarterlyTargetActivities}`}
          Icon={ClipboardList}
          tone="edify"
        />
      </section>

      <section className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-3">Category Progress</h2>
        <ul className="space-y-2">
          {(
            [
              { key: "trainingsCompleted", label: "Trainings Completed" },
              { key: "validVisits",        label: "Valid Visits" },
              { key: "ssaCompletion",      label: "SSA Completion" },
              { key: "salesforceLogging",  label: "Salesforce Logging" },
              { key: "coreSchoolTargets",  label: "Core School Targets" },
            ] as const
          ).map((row) => {
            const pct = staff.targetCategoryProgress[row.key];
            const color = pct >= 80 ? "#10b981" : pct >= 60 ? "#f59e0b" : "#ef4444";
            return (
              <li key={row.key} className="flex items-center gap-3 text-[11.5px]">
                <span className="w-[170px] font-semibold shrink-0">{row.label}</span>
                <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
                </div>
                <span className="w-10 text-right font-extrabold tabular shrink-0">{pct}%</span>
              </li>
            );
          })}
        </ul>
      </section>

      {verify && (
        <section className="card p-3.5">
          <header className="flex items-start justify-between gap-2 mb-2">
            <div className="min-w-0">
              <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
                Client SSA Verification ({verifyRatePct}% quota)
              </h2>
              <p className="text-[11.5px] muted leading-snug mt-0.5 max-w-[520px]">
                Every CCEO and Program Lead must directly verify SSA for at least {verifyRatePct}% of their
                assigned Client schools each cycle.
                {" "}<span className="font-semibold text-[var(--color-edify-text)]">{verify.staffName}</span>
                {" "}is assigned {verify.assignedClients} Client schools — target {verify.target} verifications.
              </p>
            </div>
            <span className={cn(
              "inline-flex items-center px-2 py-[3px] rounded-md text-caption font-extrabold whitespace-nowrap shrink-0",
              verify.status === "Met"      ? "bg-emerald-100 text-emerald-700" :
              verify.status === "On Track" ? "bg-sky-100     text-sky-700"     :
              verify.status === "At Risk"  ? "bg-amber-100   text-amber-700"   :
                                             "bg-rose-100    text-rose-700"    ,
            )}>
              {verify.status}
            </span>
          </header>
          <div className="grid grid-cols-3 gap-2 mt-2">
            <Stat label="Assigned Clients" value={String(verify.assignedClients)} />
            <Stat label="Cycle Target"     value={String(verify.target)} />
            <Stat label="Verified"         value={`${verify.verified} / ${verify.target}`} />
          </div>
          <div className="mt-3 h-2 rounded-full bg-[#eef2f4] overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full",
                verify.status === "Met"      ? "bg-emerald-500" :
                verify.status === "On Track" ? "bg-sky-500"     :
                verify.status === "At Risk"  ? "bg-amber-500"   :
                                                "bg-rose-500"   ,
              )}
              style={{ width: `${Math.min(100, verify.pct)}%` }}
            />
          </div>
          <div className="text-caption muted mt-1.5 text-right">{verify.pct}% of target</div>
        </section>
      )}

      <section className="grid grid-cols-12 gap-3 md:gap-4 items-start">
        <div className="col-span-12 md:col-span-7">
          <DetailFacts
            rows={[
              { label: "Staff ID",      value: staff.staffId },
              { label: "Role",          value: staff.role },
              { label: "Region",        value: staff.region },
              { label: "Supervisor",    value: staff.supervisorId },
              { label: "Email",         value: <span className="inline-flex items-center gap-1.5"><Mail size={12} />{staff.staffId.toLowerCase().replace(/-/g, ".")}@edify.org</span> },
              { label: "Scope",         value: <span className="inline-flex items-center gap-1.5"><Briefcase size={12} />Field Operations</span> },
            ]}
          />
        </div>
        <div className="col-span-12 md:col-span-5 card p-3.5 space-y-2.5">
          <h3 className="text-[13px] font-extrabold tracking-tight">Context that explains gaps</h3>
          <Context label="Approved leave"        value={`${staff.approvedLeaveDays} days`} />
          <Context label="Blocked planning"      value={`${staff.blockedPlanningDays} days`} />
          <Context label="Route difficulty"      value={`${staff.routeDifficultyIndex}/100`} />
          <Context label="Funding delay"         value={`${staff.fundingDelayDays} days`} />
          <Context label="Salesforce issues"     value={`${staff.unresolvedSalesforceIssues}`} />
          <Context label="Partner blocks"        value={`${staff.partnerDependencyBlocks}`} />
          <Context label="2-wk slippage"         value={staff.twoConsecutiveWeekSlippage ? "Yes" : "No"} />
        </div>
      </section>

      {(staff.earlyWarningTriggered || staff.midYearBelow40Triggered || staff.possiblePipReviewRequired) && (
        <section className="card p-3.5 border-amber-200 bg-amber-50/40">
          <div className="flex items-start gap-3">
            <span className="h-9 w-9 rounded-md bg-amber-100 text-amber-700 grid place-items-center shrink-0">
              <AlertTriangle size={16} />
            </span>
            <div className="min-w-0 flex-1">
              <h3 className="text-[13px] font-extrabold tracking-tight">Engine flags</h3>
              <ul className="mt-1.5 space-y-1 text-[11.5px]">
                {staff.earlyWarningTriggered && (
                  <li>• Early warning triggered — {staff.earlyWarningReasons.join(", ")}</li>
                )}
                {staff.midYearBelow40Triggered && <li>• Mid-year below 40% pace</li>}
                {staff.possiblePipReviewRequired && <li>• PIP review possible (gated by support review)</li>}
              </ul>
              {staff.recommendedSupportActions.length > 0 && (
                <>
                  <div className="text-[12px] font-extrabold tracking-tight mt-3">Recommended support</div>
                  <ul className="mt-1 space-y-1 text-[11.5px]">
                    {staff.recommendedSupportActions.map((a) => (
                      <li key={a} className="inline-flex items-start gap-1.5">
                        <CheckCircle2 size={12} className="text-emerald-600 mt-0.5 shrink-0" />
                        {a}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <div className="mt-2 text-caption muted inline-flex items-center gap-1">
                Support review status: <span className="font-extrabold">{staff.supportReviewStatus}</span>
              </div>
            </div>
          </div>
        </section>
      )}

      <section className="card p-3.5">
        <h3 className="text-[13px] font-extrabold tracking-tight mb-2">Related</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-[12px]">
          <QuickLink Icon={Calendar} title="Plans submitted by this staff" href="/plans" />
          <QuickLink Icon={ArrowUpRight} title="Recent debriefs" href="/debriefs" />
          <QuickLink Icon={School} title="Assigned schools" href="/schools" />
        </div>
      </section>
    </EntityDetail>
  );
}

function Context({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-[11.5px]">
      <span className="muted">{label}</span>
      <span className={cn("font-extrabold tabular")}>{value}</span>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-[var(--color-edify-soft)]/40 border border-[var(--color-edify-border)] p-2.5 text-center">
      <div className="text-caption muted font-bold uppercase tracking-wide leading-tight">{label}</div>
      <div className="text-[18px] font-extrabold tabular leading-none mt-1">{value}</div>
    </div>
  );
}

function QuickLink({ Icon, title, href }: { Icon: typeof Users; title: string; href: string }) {
  return (
    <a
      href={href}
      className="rounded-xl border border-[var(--color-edify-border)] p-3 flex items-center gap-2 hover:bg-[var(--color-edify-soft)]/40"
    >
      <Icon size={14} className="text-[var(--color-edify-muted)]" />
      <span className="font-semibold">{title}</span>
    </a>
  );
}
