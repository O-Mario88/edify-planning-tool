// Plan-derived cards — the field plan, seen downstream.
//
//   AccountantPlanCard → Accountant console: budget auto-derived from plans
//   IaPlanCard         → Impact Assessment dashboard: verification plan
//                        auto-derived from plans
//
// Both read from lib/plan-cascade so the budget the Accountant sees and
// the verification load the IA sees can never drift from the field plan.
// (The interactive "My Plan" card lives in ./MyPlanCard.)

import Link from "next/link";
import {
  Wallet,
  ClipboardCheck,
  ArrowRight,
  CornerDownRight,
  Sparkles,
} from "lucide-react";
import { accountantDerivedPlan, iaDerivedPlan } from "@/lib/plan-cascade";
import { cn } from "@/lib/utils";

const ugx = (n: number) => `UGX ${n.toLocaleString()}`;

// ────────── shared shell ──────────

function CardShell({
  icon,
  title,
  subtitle,
  badge,
  link,
  children,
  className,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  badge?: string;
  link?: { href: string; label: string };
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("card p-3.5 space-y-3", className)}>
      <header className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <h3 className="text-[15px] font-extrabold tracking-tight inline-flex items-center gap-2">
            {icon}
            {title}
            {badge && (
              <span className="inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-1.5 py-[2px] text-[9px] font-extrabold uppercase tracking-wide text-emerald-700">
                <Sparkles size={9} />
                {badge}
              </span>
            )}
          </h3>
          <p className="text-caption muted mt-0.5">{subtitle}</p>
        </div>
        {link && (
          <Link
            href={link.href}
            className="text-[11px] font-extrabold text-[var(--color-edify-primary)] inline-flex items-center gap-1 hover:underline shrink-0"
          >
            {link.label} <ArrowRight size={11} />
          </Link>
        )}
      </header>
      {children}
    </section>
  );
}

function StatTile({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "edify";
}) {
  return (
    <div className="rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/30 px-3 py-2.5">
      <div className="text-[9.5px] muted font-bold uppercase tracking-wide leading-tight">
        {label}
      </div>
      <div
        className={cn(
          "text-[17px] font-extrabold tabular leading-none mt-1 tracking-tight",
          tone === "edify" && "text-[var(--color-edify-primary)]",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function MeterRow({
  label,
  meta,
  pct,
  barClass,
}: {
  label: string;
  meta: string;
  pct: number;
  barClass: string;
}) {
  return (
    <li>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11.5px] font-semibold truncate">{label}</span>
        <span className="text-[11px] muted tabular shrink-0">{meta}</span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
        <div
          className={cn("h-full rounded-full", barClass)}
          style={{ width: `${Math.max(3, pct)}%` }}
        />
      </div>
    </li>
  );
}

// ────────── Accountant — plan-derived budget ──────────

export function AccountantPlanCard() {
  const plan = accountantDerivedPlan();
  return (
    <CardShell
      icon={<Wallet size={15} className="text-[var(--color-edify-primary)]" />}
      title="Plan-derived budget"
      subtitle="Auto-generated from CCEO + Program Lead field plans — every planned activity is a budget line."
      badge="Auto-generated"
      link={{ href: "/budget", label: "Open budget" }}
    >
      <div className="grid grid-cols-3 gap-2">
        <StatTile label="Total budget" value={ugx(plan.totalBudget)} tone="edify" />
        <StatTile label="Source activities" value={`${plan.sourceActivities}`} />
        <StatTile label="Schools" value={`${plan.schoolsCovered}`} />
      </div>

      <div>
        <div className="text-[11px] font-bold mb-1.5">Budget by delivery mode</div>
        <ul className="space-y-2">
          {plan.lines.map((l) => (
            <MeterRow
              key={l.category}
              label={l.category}
              meta={`${ugx(l.amount)} · ${l.pct}%`}
              pct={l.pct}
              barClass="bg-emerald-500"
            />
          ))}
        </ul>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2">
          <div className="text-[10px] font-bold text-amber-800 uppercase tracking-wide">
            Awaiting approval
          </div>
          <div className="text-[13px] font-extrabold tabular text-amber-900 mt-0.5">
            {plan.awaitingApprovalCount} · {ugx(plan.awaitingApprovalAmount)}
          </div>
        </div>
        <div className="rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/30 px-2.5 py-2">
          <div className="text-[10px] font-bold muted uppercase tracking-wide">
            Still in draft
          </div>
          <div className="text-[13px] font-extrabold tabular mt-0.5">
            {plan.draftCount} · {ugx(plan.draftAmount)}
          </div>
        </div>
      </div>
    </CardShell>
  );
}

// ────────── Impact Assessment — plan-derived verification plan ──────────

export function IaPlanCard() {
  const plan = iaDerivedPlan();
  const maxRecords = Math.max(...plan.byIntervention.map((v) => v.records), 1);
  return (
    <CardShell
      icon={<ClipboardCheck size={15} className="text-[var(--color-edify-primary)]" />}
      title="Plan-derived verification plan"
      subtitle="Auto-generated from field plans — every planned activity becomes a Salesforce record to verify."
      badge="Auto-generated"
      link={{ href: "/data-verification", label: "Verification Queue" }}
    >
      <div className="grid grid-cols-3 gap-2">
        <StatTile
          label="Records expected"
          value={`${plan.recordsExpected}`}
          tone="edify"
        />
        <StatTile label="Schools to verify" value={`${plan.schoolsToVerify}`} />
        <StatTile label="High priority" value={`${plan.highPriorityRecords}`} />
      </div>

      <div>
        <div className="text-[11px] font-bold mb-1.5">
          Salesforce records by intervention
        </div>
        <ul className="space-y-2">
          {plan.byIntervention.map((v) => (
            <MeterRow
              key={v.intervention}
              label={v.intervention}
              meta={`${v.records} rec · ${v.schools} sch`}
              pct={Math.round((v.records / maxRecords) * 100)}
              barClass="bg-violet-500"
            />
          ))}
        </ul>
      </div>

      <div className="rounded-lg border border-violet-200 bg-violet-50 px-2.5 py-2 text-caption text-violet-800 flex items-start gap-1.5">
        <CornerDownRight size={12} className="mt-[1px] shrink-0" />
        <span>
          {plan.partnerDeliveredRecords} partner-delivered records need
          independent verification before they count toward impact.
        </span>
      </div>
    </CardShell>
  );
}
