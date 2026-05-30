import { notFound } from "next/navigation";
import {
  Users,
  Target,
  Cloud,
  ClipboardList,
  School,
  AlertTriangle,
  CheckCircle2,
  ArrowUpRight,
  Mail,
  Briefcase,
  Calendar,
} from "lucide-react";
import { EntityDetail, DetailKpi, DetailFacts } from "@/components/shell/EntityDetail";
import { staffTargetPerformance, type StaffTargetRow } from "@/lib/team-targets-mock";
import { getClientVerificationFor, CLIENT_SSA_VERIFICATION_RATE } from "@/lib/ssa-mock";
import { cn } from "@/lib/utils";

const PACE_BADGE: Record<StaffTargetRow["paceStatus"], { tone: "edify" | "green" | "amber" | "rose"; label: string }> = {
  "On Track":        { tone: "green",  label: "On Track" },
  "Slightly Behind": { tone: "amber",  label: "Slightly Behind" },
  "Behind":          { tone: "amber",  label: "Behind" },
  "High Risk":       { tone: "rose",   label: "High Risk" },
  "Critical":        { tone: "rose",   label: "Critical" },
};

export default async function StaffDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const staff = staffTargetPerformance.find((s) => s.staffId === id);
  if (!staff) return notFound();

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
      {/* Hero KPIs */}
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
          Icon={Cloud}
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

      {/* Category progress */}
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

      {/* Client SSA Verification quota (10% per cycle) */}
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

      {/* Identity + Risk context */}
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

      {/* Engine flags */}
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
