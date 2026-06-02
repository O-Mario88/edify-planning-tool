import Link from "next/link";
import { Building2, Handshake, Lock, ArrowRight } from "lucide-react";
import { portfolioForStaffId } from "@/lib/portfolio/portfolio";
import { cn } from "@/lib/utils";

// Compact portfolio summary for a staff dashboard. Schools auto-appear here the
// moment they're uploaded with this person as the Account Owner — so the
// dashboard always reflects the live portfolio.
export function PortfolioSummaryCard({ staffId }: { staffId: string }) {
  const { counts } = portfolioForStaffId(staffId);

  return (
    <Link href="/portfolio" className="card p-3.5 block hover:bg-[var(--color-edify-soft)]/20 transition-colors">
      <div className="flex items-center justify-between gap-2 mb-2.5">
        <div className="flex items-center gap-1.5">
          <Building2 size={14} className="text-[var(--color-edify-primary)]" />
          <h3 className="text-[12.5px] font-extrabold tracking-tight">My School Portfolio</h3>
        </div>
        <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-edify-primary)]">
          View all <ArrowRight size={12} />
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        <Metric label="Schools owned"   value={counts.total}          tone="edify" />
        <Metric label="Client / Core"   value={`${counts.client}/${counts.core}`} tone="slate" />
        <Metric label="Awaiting SSA"    value={counts.missingSsa}     tone={counts.missingSsa > 0 ? "amber" : "green"} Icon={Lock} />
        <Metric label="Partner-delegated" value={counts.partnerAssigned} tone="sky" Icon={Handshake} />
      </div>
    </Link>
  );
}

const TONE: Record<string, string> = {
  edify: "text-[var(--color-edify-primary)]",
  slate: "text-slate-700",
  amber: "text-amber-700",
  green: "text-emerald-700",
  sky:   "text-sky-700",
};

function Metric({ label, value, tone, Icon }: { label: string; value: number | string; tone: string; Icon?: React.ComponentType<{ size?: number; className?: string }> }) {
  return (
    <div className="rounded-lg border border-[var(--color-edify-divider)] p-2">
      <div className="flex items-center gap-1">
        {Icon && <Icon size={11} className={cn("shrink-0", TONE[tone])} />}
        <span className="text-[10px] muted font-semibold truncate">{label}</span>
      </div>
      <div className={cn("text-[18px] font-extrabold tabular tracking-tight", TONE[tone])}>{value}</div>
    </div>
  );
}
