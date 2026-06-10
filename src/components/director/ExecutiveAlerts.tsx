import Link from "next/link";
import { AlertTriangle, ArrowRight, Siren, Eye } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  buildExecutiveAlerts,
  type ExecutiveAlert,
  type ExecutiveAlertInputs,
  type ExecutiveAlertSeverity,
} from "@/lib/director/executive-alerts";
import { cn } from "@/lib/utils";

// Today's Executive Alerts — the first content block on the CD dashboard.
// Each row answers four executive questions inline: what's wrong, why it
// matters, who is affected, and what to do — with one action button. The
// CD acts from here without dropping into operational pages.

const SEVERITY_META: Record<
  ExecutiveAlertSeverity,
  { label: string; chip: string; stripe: string }
> = {
  urgent: {
    label: "Urgent",
    chip: "bg-rose-50 text-rose-700 border-rose-200",
    stripe: "bg-rose-500",
  },
  warning: {
    label: "Attention",
    chip: "bg-amber-50 text-amber-700 border-amber-200",
    stripe: "bg-amber-400",
  },
  watch: {
    label: "Watch",
    chip: "bg-sky-50 text-sky-700 border-sky-200",
    stripe: "bg-sky-400",
  },
};

function AlertRow({ alert }: { alert: ExecutiveAlert }) {
  const meta = SEVERITY_META[alert.severity];
  return (
    <li className="relative flex flex-col sm:flex-row sm:items-start gap-2.5 sm:gap-4 py-3 pl-4 pr-3">
      <span className={cn("absolute left-0 top-2 bottom-2 w-[3px] rounded-full", meta.stripe)} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-extrabold uppercase tracking-wide",
              meta.chip,
            )}
          >
            {alert.severity === "urgent" ? <Siren size={10} /> : alert.severity === "watch" ? <Eye size={10} /> : <AlertTriangle size={10} />}
            {meta.label}
          </span>
          <span className="text-[11px] muted font-semibold">{alert.scope}</span>
        </div>
        <div className="mt-1 text-[13px] font-extrabold tracking-tight leading-snug">
          {alert.issue}
        </div>
        <p className="mt-0.5 text-[12px] muted leading-snug">{alert.why}</p>
        <p className="mt-1 text-[12px] leading-snug">
          <span className="font-bold">Recommended:</span> {alert.recommendedAction}
        </p>
      </div>
      <div className="shrink-0 sm:pt-1">
        <Link
          href={alert.actionHref}
          className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-edify-border)] px-3 py-1.5 text-[12px] font-bold hover:bg-[var(--color-edify-soft)]/40 whitespace-nowrap"
        >
          {alert.actionLabel}
          <ArrowRight size={12} />
        </Link>
      </div>
    </li>
  );
}

export function ExecutiveAlerts({ inputs }: { inputs?: ExecutiveAlertInputs }) {
  const alerts = buildExecutiveAlerts(inputs);
  const urgent = alerts.filter((a) => a.severity === "urgent").length;

  return (
    <SectionCard
      icon={<Siren size={13} />}
      title="Today's Executive Alerts"
      actions={
        <span className="text-[11.5px] muted font-semibold">
          {alerts.length} open · {urgent} urgent
        </span>
      }
    >
      {alerts.length === 0 ? (
        <p className="text-[12.5px] muted py-2">
          Nothing needs an executive decision today.
        </p>
      ) : (
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {alerts.map((a) => (
            <AlertRow key={a.id} alert={a} />
          ))}
        </ul>
      )}
    </SectionCard>
  );
}
