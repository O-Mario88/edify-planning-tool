// PartnerHealthCard — single number, single band, transparent breakdown.

import { Activity } from "lucide-react";
import type { PartnerHealthResult, PartnerHealthBand } from "@/lib/partner/partner-types";

const BAND_STYLE: Record<PartnerHealthBand, { bg: string; fg: string; label: string }> = {
  Excellent:  { bg: "bg-emerald-100", fg: "text-emerald-800", label: "Excellent"  },
  Healthy:    { bg: "bg-sky-100",     fg: "text-sky-800",     label: "Healthy"    },
  Watch:      { bg: "bg-amber-100",   fg: "text-amber-800",   label: "Watch"      },
  AtRisk:     { bg: "bg-rose-100",    fg: "text-rose-800",    label: "At Risk"    },
  Suspended:  { bg: "bg-slate-200",   fg: "text-slate-800",   label: "Suspended"  },
};

export function PartnerHealthCard({ health }: { health: PartnerHealthResult | undefined }) {
  if (!health) return null;
  const style = BAND_STYLE[health.band];
  const b = health.breakdown;
  return (
    <section className="card p-3.5">
      <header className="flex items-center gap-2 mb-3">
        <span className="w-6 h-6 rounded-md bg-[var(--color-edify-soft)]/60 text-[var(--color-edify-primary)] grid place-items-center">
          <Activity size={13} />
        </span>
        <h3 className="text-[13px] font-extrabold tracking-tight">Partner health</h3>
        <span className={`ml-auto inline-flex items-center gap-1 px-2 py-[2px] rounded-md text-caption font-extrabold uppercase tracking-wide ${style.bg} ${style.fg}`}>
          {style.label}
        </span>
      </header>
      <div className="flex items-end gap-3">
        <div className="text-[32px] font-extrabold tabular num-hero text-[var(--color-edify-text)] leading-none">{health.score}</div>
        <div className="text-[11px] muted pb-1">/ 100</div>
      </div>
      <p className="text-[11.5px] muted leading-snug mt-1.5">
        Verified delivery + evidence quality + timeliness + school improvement + collaboration + reporting accuracy.
        Overdue + returned-correction penalties apply.
      </p>
      <ul className="mt-3 space-y-1 text-[11.5px]">
        <Row label="Verified delivery"     value={b.verifiedDelivery} />
        <Row label="Evidence quality"      value={b.evidenceQuality} />
        <Row label="Timeliness"            value={b.timeliness} />
        <Row label="School improvement"    value={b.schoolImprovement} />
        <Row label="Staff collaboration"   value={b.staffCollaboration} />
        <Row label="Reporting accuracy"    value={b.reportingAccuracy} />
        <Row label="Overdue penalty"       value={-b.overduePenalty} negative />
        <Row label="Returned-correction penalty" value={-b.returnedCorrectionPenalty} negative />
      </ul>
    </section>
  );
}

function Row({ label, value, negative }: { label: string; value: number; negative?: boolean }) {
  return (
    <li className="flex items-center justify-between gap-2">
      <span className="text-[var(--color-edify-text)]">{label}</span>
      <span className={`tabular font-extrabold ${negative ? "text-rose-700" : "text-[var(--color-edify-text)]"}`}>
        {value > 0 ? "+" : ""}{value.toFixed(1)}
      </span>
    </li>
  );
}
