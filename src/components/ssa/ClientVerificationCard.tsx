import Link from "next/link";
import {
  ShieldCheck,
  Info,
  CheckCircle2,
  AlertTriangle,
  ChevronRight,
} from "lucide-react";
import {
  clientVerificationProgress,
  clientVerificationRollup,
  CLIENT_SSA_VERIFICATION_RATE,
  type ClientVerificationProgress,
} from "@/lib/ssa-mock";
import { cn } from "@/lib/utils";

// Surfaces the org-wide "10% of Client schools verified each cycle" rule.
//
//   • Headline donut shows team progress vs target
//   • Per-staff list shows individual progress + status
//   • Variant `compact` collapses to the headline only — useful for
//     embedding inside other cards (e.g. CPL Field Work card)

const STATUS_TONE: Record<ClientVerificationProgress["status"], string> = {
  "Met":      "bg-emerald-100 text-emerald-700",
  "On Track": "bg-sky-100     text-sky-700",
  "At Risk":  "bg-amber-100   text-amber-700",
  "Behind":   "bg-rose-100    text-rose-700",
};

const STATUS_BAR: Record<ClientVerificationProgress["status"], string> = {
  "Met":      "bg-emerald-500",
  "On Track": "bg-sky-500",
  "At Risk":  "bg-amber-500",
  "Behind":   "bg-rose-500",
};

export function ClientVerificationCard({
  rows = clientVerificationProgress,
  variant = "full",
  highlightStaffId,
}: {
  rows?: ClientVerificationProgress[];
  variant?: "full" | "compact";
  highlightStaffId?: string;
}) {
  const r = clientVerificationRollup(rows);
  const ratePct = Math.round(CLIENT_SSA_VERIFICATION_RATE * 100);

  return (
    <article className="card p-3.5 flex flex-col" id="client-verification">
      {/* Header */}
      <header className="flex items-start justify-between gap-2 mb-3">
        <div className="min-w-0">
          <h2 className="text-body-lg lg:text-[15px] font-extrabold tracking-tight inline-flex items-center gap-2">
            <ShieldCheck size={14} className="text-emerald-600" />
            Client SSA Verification
          </h2>
          <p className="text-[11.5px] muted leading-snug mt-0.5 max-w-[440px]">
            Every CCEO — and every Program Lead — must verify SSA for at least{" "}
            <span className="font-extrabold text-[var(--color-edify-text)]">{ratePct}%</span> of their
            assigned Client schools each cycle. Verifications are the gateway to Core onboarding.
          </p>
        </div>
        <Link
          href="/ssa/core-candidates"
          className="hidden md:inline-flex h-9 px-3 rounded-xl border border-[var(--color-edify-border)] text-[11.5px] font-semibold items-center gap-1.5 hover:bg-[var(--color-edify-soft)]/60 shrink-0"
        >
          Open Queue
          <ChevronRight size={12} />
        </Link>
      </header>

      {/* Headline metrics */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-2.5 mb-3">
        <Metric
          label="Cycle target"
          value={`${r.totalVerified} / ${r.totalTarget}`}
          caption={`${ratePct}% of ${r.totalAssignedClients} Client schools`}
          tone={r.pct >= 100 ? "green" : r.pct >= 60 ? "edify" : r.pct >= 40 ? "amber" : "rose"}
        />
        <Metric label="On Track"  value={String(r.onTrack)} caption="≥ 70% of target" tone="edify" />
        <Metric label="At Risk"   value={String(r.atRisk)}  caption="40–69%"          tone="amber" />
        <Metric label="Behind"    value={String(r.behind)}  caption="< 40%"           tone="rose"  />
      </section>

      {/* Compact variant ends here */}
      {variant === "compact" && (
        <div className="mt-1 inline-flex items-center gap-1.5 text-caption muted">
          <Info size={11} />
          {r.met} of {rows.length} staff have hit the {ratePct}% quota this cycle.
        </div>
      )}

      {/* Full variant: per-staff list */}
      {variant === "full" && (
        <ul className="mt-1 divide-y divide-[var(--color-edify-divider)]">
          {rows.map((row) => {
            const highlighted = row.staffId === highlightStaffId;
            const widthPct = Math.min(100, row.pct);
            return (
              <li
                key={row.staffId}
                className={cn(
                  "py-2.5 flex items-center gap-3",
                  highlighted && "bg-[var(--color-edify-soft)]/40 -mx-2 px-2 rounded-md",
                )}
              >
                <div className="h-9 w-9 rounded-full bg-[var(--color-edify-primary)] text-white text-[11px] font-extrabold grid place-items-center shrink-0">
                  {row.staffName.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline justify-between gap-2">
                    <Link href={`/staff/${row.staffId}`} className="text-body font-extrabold tracking-tight truncate hover:text-[var(--color-edify-primary)]">
                      {row.staffName}
                    </Link>
                    <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap shrink-0", STATUS_TONE[row.status])}>
                      {row.status === "Met" ? <CheckCircle2 size={9} className="mr-0.5" /> :
                        row.status === "Behind" || row.status === "At Risk" ? <AlertTriangle size={9} className="mr-0.5" /> :
                        null}
                      {row.status}
                    </span>
                  </div>
                  <div className="text-caption muted truncate">
                    {row.role} · {row.assignedClients} Client schools · target {row.target}
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                      <div className={cn("h-full rounded-full", STATUS_BAR[row.status])} style={{ width: `${widthPct}%` }} />
                    </div>
                    <span className="text-caption font-extrabold tabular shrink-0 w-[64px] text-right">
                      {row.verified} / {row.target}
                    </span>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </article>
  );
}

function Metric({
  label,
  value,
  caption,
  tone,
}: {
  label: string;
  value: string;
  caption: string;
  tone: "edify" | "green" | "amber" | "rose";
}) {
  const t =
    tone === "green"  ? "border-emerald-200 bg-emerald-50 text-emerald-700" :
    tone === "amber"  ? "border-amber-200  bg-amber-50  text-amber-700"  :
    tone === "rose"   ? "border-rose-200   bg-rose-50   text-rose-700"   :
                        "border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 text-[var(--color-edify-primary)]";
  return (
    <div className={cn("rounded-xl border p-2.5", t)}>
      <div className="text-caption muted font-semibold leading-tight">{label}</div>
      <div className="text-[18px] font-extrabold tabular leading-none mt-1 text-[var(--color-edify-text)]">{value}</div>
      <div className="text-[10px] muted mt-0.5 truncate">{caption}</div>
    </div>
  );
}
