import Link from "next/link";
import { ArrowLeft, History, TrendingDown, TrendingUp, Info } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import {
  monthlyPlanSubmissions,
  amendmentMetrics,
} from "@/lib/monthly-approval-mock";
import { formatUgxBig } from "@/lib/cost-settings-mock";
import { cn } from "@/lib/utils";
import { isMockAllowed } from "@/lib/mock-policy";
import { ProductiveEmptyState } from "@/components/ui/ProductiveEmptyState";

export default function AmendmentHistoryPage() {
  if (!isMockAllowed())
    return (
      <ProductiveEmptyState
        Icon={History}
        tone="info"
        title="Amendment history isn't connected to the live approval chain yet"
        description="Budget amendment roll-ups are withheld until they trace to live FundRequest records."
        actionLabel="Open Budget"
        actionHref="/budget"
        links={[{ label: "Fund requests", href: "/fund-requests" }]}
        note="No fabricated money figures are shown."
      />
    );
  const amendments = monthlyPlanSubmissions.flatMap((s) =>
    s.amendments.map((a) => ({ submission: s, amendment: a })),
  );
  const metrics = amendmentMetrics();

  return (
    <StubPage
      title="Budget Amendment History"
      subtitle="Every amendment is append-only. Originals are preserved permanently. This page rolls them up so leadership can see patterns."
    >
      <Link
        href="/approvals"
        className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline -mt-2"
      >
        <ArrowLeft size={11} />
        Back to Approvals
      </Link>

      {/* Aggregated metrics */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Total amendments"      value={String(metrics.totalAmendments)}                  tone="amber"  Icon={History} />
        <Kpi label="Total reduced"         value={formatUgxBig(metrics.totalAmountReduced)}        tone="rose"   Icon={TrendingDown} />
        <Kpi label="Total increased"       value={formatUgxBig(metrics.totalAmountIncreased)}      tone="green"  Icon={TrendingUp} />
        <Kpi label="Funding gap after amendments" value={formatUgxBig(metrics.fundingGapAfter)}    tone={metrics.fundingGapAfter > 0 ? "rose" : "green"} Icon={Info} />
      </section>

      {/* Pattern panels */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Panel title="Most common reason">
          {metrics.topReason === "—" ? (
            <div className="text-[11.5px] muted">No amendments yet.</div>
          ) : (
            <div className="text-[12px] leading-snug">{metrics.topReason}</div>
          )}
        </Panel>
        <Panel title="Activities most often reduced">
          {metrics.activitiesMostReduced.length === 0 ? (
            <div className="text-[11.5px] muted">—</div>
          ) : (
            <ul className="space-y-0.5 text-[11.5px]">
              {metrics.activitiesMostReduced.map((a) => (
                <li key={a.type} className="flex items-baseline justify-between gap-2">
                  <span>{a.type}</span>
                  <span className="font-extrabold tabular">{a.count}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel title="Regions most often amended">
          {metrics.regionsMostAmended.length === 0 ? (
            <div className="text-[11.5px] muted">—</div>
          ) : (
            <ul className="space-y-0.5 text-[11.5px]">
              {metrics.regionsMostAmended.map((r) => (
                <li key={r.region} className="flex items-baseline justify-between gap-2">
                  <span>{r.region}</span>
                  <span className="font-extrabold tabular">{r.count}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </section>

      {metrics.programLeadsMostReturned.length > 0 && (
        <section className="card p-3.5">
          <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Program Leads with returned plans</h2>
          <ul className="space-y-0.5 text-[12px]">
            {metrics.programLeadsMostReturned.map((pl) => (
              <li key={pl.name} className="flex items-baseline justify-between gap-2">
                <span>{pl.name}</span>
                <span className="font-extrabold tabular">{pl.count}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* All amendments */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
            <History size={14} className="text-amber-600" />
            All amendments (append-only)
          </h2>
          <span className="text-caption muted">{amendments.length} amendment(s)</span>
        </header>
        {amendments.length === 0 ? (
          <div className="text-[12px] muted">No amendments recorded yet.</div>
        ) : (
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {amendments.map(({ submission, amendment: a }) => (
              <li key={a.id} className="py-3">
                <div className="flex items-baseline justify-between gap-2">
                  <div className="text-body font-extrabold tracking-tight">
                    <Link href={`/budget/approvals/${submission.id}`} className="hover:text-[var(--color-edify-primary)]">
                      {submission.programLeadName} · {submission.monthLabel}
                    </Link>
                  </div>
                  <span className={cn(
                    "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap",
                    a.approvalStage === "Country Director Review" ? "bg-amber-100 text-amber-700" : "bg-violet-100 text-violet-700",
                  )}>{a.approvalStage}</span>
                </div>
                <div className="text-[11px] muted mt-0.5">By {a.amendedBy} ({a.amendedByRole}) · {a.amendedAt}</div>
                <div className="text-[11.5px] mt-1">
                  <span className="muted line-through">{formatUgxBig(a.originalAmount)}</span>
                  <span className="mx-2">→</span>
                  <span className="font-extrabold">{formatUgxBig(a.amendedAmount)}</span>
                  <span className={cn("ml-2 font-extrabold", a.difference < 0 ? "text-rose-700" : "text-emerald-700")}>
                    ({a.difference < 0 ? "" : "+"}{formatUgxBig(Math.abs(a.difference))})
                  </span>
                </div>
                <div className="text-[11.5px] muted leading-snug mt-1">{a.reason}</div>
                {a.comment && (
                  <div className="text-caption muted italic mt-1">&quot;{a.comment}&quot;</div>
                )}
                <div className="text-caption muted mt-1">
                  Affected activities: {a.affectedActivities.join(", ")}
                  {a.affectedDistricts && a.affectedDistricts.length > 0 && ` · Districts: ${a.affectedDistricts.join(", ")}`}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card p-3.5 text-[11.5px] muted">
        <span className="font-extrabold text-[var(--color-edify-text)]">Audit contract: </span>
        Every amendment stores original amount, amended amount, reason, amended by, role, date, affected
        activities, comments, and approval stage. Records are append-only — originals are never overwritten.
      </section>
    </StubPage>
  );
}

function Kpi({ label, value, tone, Icon }: { label: string; value: string; tone: "edify" | "green" | "amber" | "rose"; Icon: typeof History }) {
  const TONE = {
    edify: "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
    green: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100   text-amber-700",
    rose:  "bg-rose-100    text-rose-700",
  } as const;
  return (
    <div className="card p-3.5">
      <div className="flex items-center gap-2 mb-2">
        <span className={cn("h-9 w-9 rounded-full grid place-items-center", TONE[tone])}>
          <Icon size={14} />
        </span>
        <span className="text-[11.5px] muted font-semibold">{label}</span>
      </div>
      <div className="text-[22px] font-extrabold tabular leading-none">{value}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card p-3.5">
      <h3 className="text-body font-extrabold tracking-tight uppercase muted mb-2">{title}</h3>
      {children}
    </div>
  );
}
