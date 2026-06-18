import Link from "next/link";
import { GraduationCap, Lock, Unlock, AlertTriangle, CheckCircle2 } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { MetricStrip } from "@/components/ui/MetricStrip";
import {
  schoolFinancialYearSummaries,
  activeFinancialYear,
  calculatePlanningLockLevel,
  type GatewayStatus,
  type PlanningLockLevel,
} from "@/lib/fy-engine";
import { schoolsMock } from "@/lib/schools-mock";
import { isMockAllowed } from "@/lib/mock-policy";
import { ProductiveEmptyState } from "@/components/ui/ProductiveEmptyState";
import { cn } from "@/lib/utils";

const GATEWAY_TONE: Record<GatewayStatus, string> = {
  "Gateway Required":         "bg-rose-100    text-rose-700",
  "Gateway Scheduled":        "bg-sky-100     text-sky-700",
  "Gateway Completed":        "bg-emerald-100 text-emerald-700",
  "Gateway Missed":           "bg-rose-100    text-rose-700",
  "Gateway Catch-Up Required":"bg-amber-100   text-amber-700",
  "SSA Now Due":              "bg-violet-100  text-violet-700",
};

const LOCK_TONE: Record<PlanningLockLevel, string> = {
  "Gateway Required":      "bg-rose-100    text-rose-700",
  "Limited Planning Mode": "bg-amber-100   text-amber-700",
  "Full Planning Mode":    "bg-emerald-100 text-emerald-700",
};

export default function GatewayPage() {
  const active = activeFinancialYear();
  if (!isMockAllowed()) {
    return (
      <StubPage title={`Gateway — FY ${active}`} subtitle="The school gateway register is not yet served from the backend.">
        <ProductiveEmptyState
          Icon={Lock}
          title="The FY gateway register isn't wired to live data yet"
          description="Per-school Gateway training and planning-lock levels are withheld until they trace to live source records."
          actionLabel="Open Planning"
          actionHref="/planning"
          links={[{ label: "Analytics", href: "/analytics" }]}
          note="No fabricated gateway statuses are shown."
        />
      </StubPage>
    );
  }
  const rows = schoolFinancialYearSummaries.map((s) => ({
    summary: s,
    school: schoolsMock.find((x) => x.schoolId === s.schoolId),
    lockLevel: calculatePlanningLockLevel(s),
  }));

  const counts = rows.reduce<Record<GatewayStatus, number>>((acc, r) => {
    acc[r.summary.gatewayStatus] = (acc[r.summary.gatewayStatus] ?? 0) + 1;
    return acc;
  }, { "Gateway Required": 0, "Gateway Scheduled": 0, "Gateway Completed": 0, "Gateway Missed": 0, "Gateway Catch-Up Required": 0, "SSA Now Due": 0 });

  const fullPlanning    = rows.filter((r) => r.lockLevel === "Full Planning Mode").length;
  const limitedPlanning = rows.filter((r) => r.lockLevel === "Limited Planning Mode").length;
  const gatewayBlocked  = rows.filter((r) => r.lockLevel === "Gateway Required").length;

  return (
    <StubPage
      title="School Improvement Training Gateway"
      subtitle={`Every active school must complete School Improvement Training before SSA becomes due. Active FY: ${active.label}. Staff can edit cluster name + cluster date only — the system calculates the rest.`}
    >
      {/* Gateway status distribution */}
      <MetricStrip
        columns="grid-cols-2 md:grid-cols-3 lg:grid-cols-6"
        metrics={(Object.keys(counts) as GatewayStatus[]).map((k) => ({
          key: k,
          label: k,
          value: counts[k],
        }))}
      />

      {/* Planning lock distribution */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-3">
          <h2 className="text-body-lg font-extrabold tracking-tight">Planning lock levels</h2>
          <Link href="/fy/ssa-comparison" className="text-[11.5px] font-semibold text-[var(--color-edify-primary)]">
            Open SSA Comparison →
          </Link>
        </header>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <Lock3 Icon={CheckCircle2}  count={fullPlanning}    total={rows.length} label="Full Planning Mode"   sub="Gateway done + SSA verified" tone="green" />
          <Lock3 Icon={Unlock}        count={limitedPlanning} total={rows.length} label="Limited Planning"     sub="Gateway done, SSA unverified" tone="amber" />
          <Lock3 Icon={Lock}          count={gatewayBlocked}  total={rows.length} label="Gateway Required"     sub="Plans blocked until gateway" tone="rose" />
        </div>
      </section>

      {/* School-by-school list */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="text-body-lg font-extrabold tracking-tight">Schools (active FY)</h2>
          <span className="text-caption muted">{rows.length} schools</span>
        </header>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                <th scope="col" className="py-2 pr-2">School</th>
                <th scope="col" className="py-2 px-2">District / Cluster</th>
                <th scope="col" className="py-2 px-2">Gateway</th>
                <th scope="col" className="py-2 px-2">SSA</th>
                <th scope="col" className="py-2 px-2">Planning lock</th>
                <th scope="col" className="py-2 pl-2 text-right">Visits / Trainings</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {rows.slice(0, 25).map((r) => (
                <tr key={r.summary.schoolId} className="hover:bg-[var(--color-edify-soft)]/30">
                  <td className="py-2 pr-2">
                    <Link href={`/schools/${r.summary.schoolId}`} className="text-[12px] font-extrabold tracking-tight text-[var(--color-edify-primary)] hover:underline">
                      {r.school?.schoolName ?? r.summary.schoolId}
                    </Link>
                    <div className="text-caption muted">{r.school?.segment ?? "—"}</div>
                  </td>
                  <td className="py-2 px-2 muted truncate">
                    {r.school?.district ?? "—"} · {r.school?.shippingAddress?.split(" Hub")[0] ?? "—"}
                  </td>
                  <td className="py-2 px-2">
                    <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", GATEWAY_TONE[r.summary.gatewayStatus])}>
                      {r.summary.gatewayStatus}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-[11px]">{r.summary.ssaStatus}</td>
                  <td className="py-2 px-2">
                    <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", LOCK_TONE[r.lockLevel])}>
                      {r.lockLevel}
                    </span>
                  </td>
                  <td className="py-2 pl-2 text-right tabular">
                    {r.summary.visitsCompleted} / {r.summary.trainingsCompleted}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {rows.length > 25 && (
          <div className="mt-2 text-caption muted">Showing 25 of {rows.length} schools.</div>
        )}
      </section>

      {/* Staff edit policy reminder */}
      <section className="card p-3.5 border-amber-200 bg-amber-50/40">
        <div className="flex items-start gap-3">
          <span className="h-9 w-9 rounded-md bg-amber-100 text-amber-700 grid place-items-center shrink-0">
            <AlertTriangle size={16} />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="text-[13px] font-extrabold tracking-tight">Staff editable fields (gateway training)</h3>
            <p className="text-[11.5px] muted leading-snug">
              For each cluster training, staff may only edit <span className="font-extrabold">Cluster_Name</span> and{" "}
              <span className="font-extrabold">Cluster_Date</span>. The system calculates schools in cluster, expected
              participants, meal cost, partner assignment, training cost, training target category, district, region,
              and assigned staff/supervisor. Do not let staff manually build the whole training plan from scratch.
            </p>
          </div>
        </div>
      </section>
    </StubPage>
  );
}

function Lock3({
  Icon, count, total, label, sub, tone,
}: {
  Icon: typeof GraduationCap; count: number; total: number; label: string; sub: string;
  tone: "green" | "amber" | "rose";
}) {
  const TONE = {
    green: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100   text-amber-700",
    rose:  "bg-rose-100    text-rose-700",
  } as const;
  const pct = total === 0 ? 0 : Math.round((count / total) * 100);
  return (
    <div className="rounded-xl border border-[var(--color-edify-border)] p-3">
      <div className="flex items-center gap-2 mb-2">
        <span className={cn("h-9 w-9 rounded-full grid place-items-center", TONE[tone])}>
          <Icon size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-body font-extrabold tracking-tight">{label}</div>
          <div className="text-caption muted">{sub}</div>
        </div>
      </div>
      <div className="text-[22px] font-extrabold tabular leading-none">{count}</div>
      <div className="text-caption muted mt-1">{pct}% of active schools</div>
    </div>
  );
}
