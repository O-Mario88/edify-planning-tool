// Pure presentational primitives extracted from PlanBuilderDesktopView.
// None hold state or close over parent values — safe to import anywhere.

import { AlertTriangle, CheckCircle2, Info, Users, type LucideIcon } from "lucide-react";
import type { PartnerCapacityProfile, PlanningWarning } from "@/lib/plan-builder-engine";
import { cn } from "@/lib/utils";

// ────────── Number formatting ──────────

export function formatM(value: number): string {
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K`;
  return `${value}`;
}

// Compress long intervention names so the stat cell never overflows.
const INTERVENTION_SHORT: Record<string, string> = {
  "Christ-like Behavior":        "Christ-like",
  "Exposure to the Word of God": "Word of God",
  "Fees / Budget / Accounts":    "Fees / Budget",
  "Government Requirements":     "Government",
  "Leadership Best Practice":    "Leadership",
  "Learning Environment":        "Learning Env.",
  "Teaching Environment":        "Teaching Env.",
  "Enrollment":                  "Enrollment",
};

export function shortIntervention(i: string): string {
  return INTERVENTION_SHORT[i] ?? i;
}

// ────────── Tab button ──────────

export function TabButton({
  active,
  onClick,
  Icon,
  label,
  count,
  hasDraft,
}: {
  active: boolean;
  onClick: () => void;
  Icon: LucideIcon;
  label: string;
  count: number;
  hasDraft?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "h-10 px-3 rounded-lg text-body font-extrabold tracking-tight inline-flex items-center gap-2 flex-1 justify-center whitespace-nowrap relative",
        active
          ? "bg-[var(--color-edify-primary)] text-white"
          : "text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/40",
      )}
    >
      <Icon size={13} />
      <span className="hidden sm:inline">{label}</span>
      {count > 0 && (
        <span
          className={cn(
            "inline-flex items-center justify-center min-w-[22px] h-5 px-1.5 rounded-md text-caption font-extrabold tabular",
            active ? "bg-white/20" : "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
          )}
        >
          {count}
        </span>
      )}
      {hasDraft && (
        <span
          title="Draft saved"
          className="inline-flex items-center justify-center min-w-[22px] h-5 px-1.5 rounded-md text-[10px] font-extrabold uppercase tracking-wide bg-amber-100 text-amber-700"
        >
          Draft
        </span>
      )}
    </button>
  );
}

// ────────── Summary KPI ──────────

export type SummaryTone = "edify" | "green" | "amber" | "rose" | "violet" | "sky";

const SUMMARY_TONE: Record<SummaryTone, string> = {
  edify:  "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
  green:  "bg-emerald-100 text-emerald-700",
  amber:  "bg-amber-100   text-amber-700",
  rose:   "bg-rose-100    text-rose-700",
  violet: "bg-violet-100  text-violet-700",
  sky:    "bg-sky-100     text-sky-700",
};

export function Summary({
  Icon,
  label,
  value,
  sub,
  tone,
  wide,
}: {
  Icon: LucideIcon;
  label: string;
  value: number | string;
  sub?: string;
  tone: SummaryTone;
  wide?: boolean;
}) {
  if (wide) {
    return (
      <div className="card p-3.5 flex items-center gap-3">
        <span className={cn("h-11 w-11 rounded-xl grid place-items-center shrink-0", SUMMARY_TONE[tone])}>
          <Icon size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-caption muted font-semibold uppercase tracking-wide">{label}</div>
          <div className="text-[22px] font-extrabold tabular leading-tight truncate">{value}</div>
          {sub && <div className="text-caption muted truncate">{sub}</div>}
        </div>
      </div>
    );
  }
  return (
    <div className="card rounded-2xl p-3">
      <div className="flex items-center gap-2 mb-1.5">
        <span className={cn("h-8 w-8 rounded-md grid place-items-center shrink-0", SUMMARY_TONE[tone])}>
          <Icon size={13} />
        </span>
        <span className="text-caption muted font-semibold leading-tight truncate">{label}</span>
      </div>
      <div className="text-[20px] font-extrabold tabular leading-none">{value}</div>
      {sub && <div className="text-[10px] muted mt-1 truncate">{sub}</div>}
    </div>
  );
}

// ────────── Mini stat tile ──────────

const MINI_TONE = {
  sky: "bg-sky-100 text-sky-700",
  violet: "bg-violet-100 text-violet-700",
  amber: "bg-amber-100 text-amber-700",
  rose: "bg-rose-100 text-rose-700",
} as const;

export function Mini({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "sky" | "violet" | "amber" | "rose";
}) {
  return (
    <div className={cn("rounded-xl p-2.5", MINI_TONE[tone])}>
      <div className="text-[10px] font-bold uppercase tracking-wide leading-tight opacity-90">{label}</div>
      <div className="text-[18px] font-extrabold tabular leading-none mt-1">{value}</div>
    </div>
  );
}

// ────────── Fact list row ──────────

const FACT_TONE_TEXT = {
  rose: "text-rose-700",
  green: "text-emerald-700",
  edify: "text-[var(--color-edify-primary)]",
} as const;

export function Fact({
  label,
  value,
  bold,
  tone,
}: {
  label: string;
  value: string;
  bold?: boolean;
  tone?: "rose" | "green" | "edify";
}) {
  return (
    <li className="flex items-baseline justify-between gap-2">
      <span className="muted">{label}</span>
      <span className={cn("tabular", bold && "font-extrabold", tone && FACT_TONE_TEXT[tone])}>{value}</span>
    </li>
  );
}

// ────────── Definition row ──────────

export function Row({
  label,
  value,
  tone,
  mono,
}: {
  label: string;
  value: string;
  tone?: "rose" | "edify";
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="muted text-caption uppercase font-bold tracking-wide">{label}</span>
      <span
        className={cn(
          "text-[11.5px] font-extrabold",
          mono && "font-mono tabular",
          tone === "rose" && "text-rose-700",
          tone === "edify" && "text-[var(--color-edify-text)]",
        )}
      >
        {value}
      </span>
    </div>
  );
}

// ────────── Segmented toggle ──────────

export function SegToggle({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="rounded-xl bg-[var(--color-edify-soft)]/40 border border-[var(--color-edify-border)] px-3 py-2 flex items-center gap-3">
      <div className="text-[10px] muted font-bold uppercase tracking-wide shrink-0">{label}</div>
      <div className="flex items-center gap-1 flex-1 min-w-0">
        {options.map((o) => (
          <button
            key={o}
            type="button"
            onClick={() => onChange(o)}
            className={cn(
              "h-8 px-3 rounded-md text-[11.5px] font-extrabold whitespace-nowrap flex-1",
              value === o
                ? "bg-[var(--color-edify-primary)] text-white"
                : "bg-white border border-[var(--color-edify-border)] text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/50",
            )}
          >
            {o.replace(" Visit", "")}
          </button>
        ))}
      </div>
    </div>
  );
}

// ────────── Number input ──────────

export function NumInput({
  label,
  value,
  min,
  max,
  onChange,
  disabled,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (n: number) => void;
  disabled?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl bg-[var(--color-edify-soft)]/40 border border-[var(--color-edify-border)] px-2.5 py-2",
        disabled && "opacity-50",
      )}
    >
      <div className="text-[10px] muted font-bold uppercase">{label}</div>
      <input
        type="number"
        aria-label={label}
        disabled={disabled}
        value={value}
        min={min}
        max={max}
        onChange={(e) => {
          const n = Math.max(min, Math.min(max, Number(e.target.value) || min));
          onChange(n);
        }}
        className="w-full mt-1 h-7 rounded-md border border-[var(--color-edify-border)] bg-white text-[13px] px-2 font-extrabold tabular text-right"
      />
    </div>
  );
}

// ────────── Boolean toggle button ──────────

export function Toggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      className={cn(
        "rounded-xl border px-2.5 py-2 text-left transition-colors",
        value ? "border-emerald-300 bg-emerald-50/60" : "border-[var(--color-edify-border)] bg-white",
      )}
    >
      <div className="text-[10px] muted font-bold uppercase">{label}</div>
      <div
        className={cn(
          "text-[13px] font-extrabold mt-1",
          value ? "text-emerald-700" : "text-[var(--color-edify-muted)]",
        )}
      >
        {value ? "Included" : "Excluded"}
      </div>
    </button>
  );
}

// ────────── Cost badge ──────────

export function CostBadge({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl bg-[var(--color-edify-primary)]/10 border border-[var(--color-edify-primary)]/30 px-2.5 py-2">
      <div className="text-[10px] muted font-bold uppercase">{label}</div>
      <div className="text-body-lg font-extrabold tabular text-[var(--color-edify-primary)] mt-1">
        UGX {value.toLocaleString()}
      </div>
    </div>
  );
}

// ────────── Stat label/value ──────────

export function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[9.5px] muted font-bold uppercase tracking-wide leading-tight">{label}</div>
      <div className="text-[11px] font-extrabold leading-tight truncate" title={value}>
        {value}
      </div>
    </div>
  );
}

// ────────── Partner capacity card ──────────

export function PartnerCapacityCard({
  profile,
  selected,
}: {
  profile: PartnerCapacityProfile;
  selected: number;
}) {
  const overCapacity = selected > profile.availableCapacity;
  return (
    <div className={cn("card p-3.5", overCapacity && "border-rose-200 bg-rose-50/40")}>
      <h3 className="text-body font-extrabold tracking-tight uppercase muted mb-2 inline-flex items-center gap-2">
        <Users size={11} />
        Partner capacity
      </h3>
      <div className="text-body font-extrabold tracking-tight">{profile.partnerName}</div>
      <div className="text-caption muted">
        {profile.activeFieldStaff} field staff · {profile.certifiedInterventions.join(", ")} ·{" "}
        <span className={cn("font-extrabold", profile.certified ? "text-emerald-700" : "text-amber-700")}>
          {profile.certified ? "Certified" : "Non-Certified"}
        </span>
      </div>
      <ul className="text-[11.5px] space-y-1 mt-2">
        <Fact label="Monthly capacity" value={`${profile.monthlyCapacity}`} bold />
        <Fact label="Already assigned" value={`${profile.currentAssignedThisMonth}`} />
        <Fact
          label="Available"
          value={`${profile.availableCapacity}`}
          bold
          tone={profile.availableCapacity === 0 ? "rose" : "green"}
        />
        <Fact label="You selected" value={`${selected}`} bold tone={overCapacity ? "rose" : "edify"} />
      </ul>
      {overCapacity && (
        <div className="mt-2 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-2 text-[11px] text-rose-800 inline-flex items-start gap-1.5">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          <span>Capacity Exceeded — remove {selected - profile.availableCapacity}.</span>
        </div>
      )}
    </div>
  );
}

// ────────── Warnings panel ──────────

export function WarningsPanel({ warnings }: { warnings: PlanningWarning[] }) {
  if (warnings.length === 0) {
    return (
      <div className="card p-3.5 border-emerald-200 bg-emerald-50/40">
        <div className="flex items-start gap-2">
          <CheckCircle2 size={14} className="text-emerald-600 mt-0.5" />
          <div className="text-[12px] text-emerald-800">
            <div className="font-extrabold tracking-tight">No planning warnings</div>
            <div className="text-caption muted">All capacity, certification, and day-rules satisfied.</div>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="card p-3.5">
      <h3 className="text-body font-extrabold tracking-tight uppercase muted mb-2 inline-flex items-center gap-2">
        <AlertTriangle size={11} className="text-amber-600" />
        Planning warnings
      </h3>
      <ul className="space-y-2">
        {warnings.map((w) => (
          <li
            key={w.id}
            className={cn(
              "rounded-lg border px-3 py-2 text-[11.5px] flex items-start gap-2",
              w.level === "error" && "border-rose-200  bg-rose-50  text-rose-800",
              w.level === "warning" && "border-amber-200 bg-amber-50 text-amber-800",
              w.level === "info" && "border-sky-200   bg-sky-50   text-sky-800",
            )}
          >
            {w.level === "info" ? (
              <Info size={12} className="mt-0.5 shrink-0" />
            ) : (
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            )}
            <span className="leading-snug">{w.message}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
