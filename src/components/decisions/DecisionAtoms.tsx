// Shared atoms for Decision cards.
//
// Keeping these in one file lets the hero card and the list card share
// the exact same visual language for rationale, confidence, cost, owner,
// and alternatives. The Decision Intelligence surface is *one* concept —
// the page just renders it at two sizes.

import Link from "next/link";
import {
  AlertCircle,
  ArrowRight,
  Building2,
  Check,
  ChevronRight,
  CircleDot,
  Coins,
  Compass,
  FileWarning,
  MapPin,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  User as UserIcon,
  Users,
  Wallet,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  Decision,
  DecisionAlternative,
  DecisionCategory,
  DecisionConfidence,
  DecisionSubject,
  OwnerRecommendation,
  RationaleNode,
  RationaleWeight,
} from "@/lib/decisions/decision-types";

// ────────── Tone helpers ──────────

const TONE_RAIL: Record<Decision["tone"], string> = {
  red:   "card-rail-rose",
  amber: "card-rail-amber",
  green: "card-rail-emerald",
};

const TONE_DOT: Record<NonNullable<RationaleNode["tone"]>, string> = {
  red:   "bg-rose-500",
  amber: "bg-amber-500",
  green: "bg-emerald-500",
};

const NODE_WEIGHT_LABEL: Record<RationaleWeight, string> = {
  primary:    "Primary",
  supporting: "Supporting",
  context:    "Context",
};

// ────────── Category → icon ──────────

const CATEGORY_ICON: Record<DecisionCategory, React.ComponentType<{ size?: number; className?: string }>> = {
  SchoolIntervention: Building2,
  WorkloadRebalance:  Users,
  FundReallocation:   Wallet,
  PartnerEscalation:  Users,
  EvidenceGap:        FileWarning,
  RiskMitigation:     AlertCircle,
  Recognition:        Sparkles,
  Approval:           ShieldCheck,
  Compliance:         ShieldCheck,
  CapacityBuilding:   TrendingUp,
  Strategic:          Compass,
};

export function CategoryIcon({ category, size = 14, className }: { category: DecisionCategory; size?: number; className?: string }) {
  const Icon = CATEGORY_ICON[category];
  return <Icon size={size} className={className} />;
}

// ────────── Subject ──────────

export function SubjectLine({ subject }: { subject: DecisionSubject }) {
  const subKindMeta: Record<DecisionSubject["kind"], { label: string; icon: React.ComponentType<{ size?: number; className?: string }> }> = {
    School:    { label: "School",    icon: Building2 },
    Staff:     { label: "Staff",     icon: UserIcon  },
    Partner:   { label: "Partner",   icon: Users     },
    Portfolio: { label: "Portfolio", icon: Users     },
    Budget:    { label: "Budget",    icon: Wallet    },
    District:  { label: "District",  icon: MapPin    },
    Country:   { label: "Country",   icon: MapPin    },
    Fund:      { label: "Fund",      icon: Coins     },
    System:    { label: "Queue",     icon: ShieldCheck },
  };
  const meta = subKindMeta[subject.kind];
  const Icon = meta.icon;
  const district = "district" in subject && subject.district ? ` · ${subject.district}` : "";
  return (
    <span className="inline-flex items-center gap-1.5 text-[11.5px] muted">
      <Icon size={12} className="text-[var(--color-edify-primary)]" />
      <span className="font-bold text-[var(--color-edify-text)]">{subject.label}</span>
      <span className="text-caption">· {meta.label}{district}</span>
    </span>
  );
}

// ────────── Confidence ──────────

const CONFIDENCE_TONE: Record<DecisionConfidence, { dot: string; text: string; bg: string }> = {
  High:   { dot: "bg-emerald-500", text: "text-emerald-800", bg: "bg-emerald-50 border-emerald-200" },
  Medium: { dot: "bg-amber-500",   text: "text-amber-800",   bg: "bg-amber-50 border-amber-200" },
  Low:    { dot: "bg-slate-400",   text: "text-slate-700",   bg: "bg-slate-50 border-slate-200" },
};

export function ConfidencePill({ level, why }: { level: DecisionConfidence; why?: string }) {
  const tone = CONFIDENCE_TONE[level];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-[3px] rounded-md border text-caption font-bold",
        tone.bg, tone.text,
      )}
      title={why ?? undefined}
    >
      <span className={cn("w-1.5 h-1.5 rounded-full", tone.dot)} />
      {level} confidence
    </span>
  );
}

// ────────── Rationale chain ──────────

export function RationaleChain({
  rationale,
  triggeredBecause,
  compact = false,
}: {
  rationale: RationaleNode[];
  triggeredBecause?: string;
  compact?: boolean;
}) {
  // In compact mode show only primary signals; full mode shows all,
  // grouped by weight.
  const visible = compact ? rationale.filter((r) => r.weight === "primary") : rationale;
  return (
    <div className="space-y-2">
      {triggeredBecause && (
        <div className="rounded-lg bg-[var(--color-edify-soft)]/70 border border-[var(--color-edify-border)] px-3 py-2">
          <div className="text-[10px] font-extrabold uppercase tracking-wider text-[var(--color-edify-primary)] mb-0.5">Why now</div>
          <div className="text-[12px] leading-snug">{triggeredBecause}</div>
        </div>
      )}
      <ul className="space-y-1.5">
        {visible.map((r, i) => (
          <li key={i} className="flex items-start gap-2 text-[12px] leading-snug">
            <span
              className={cn(
                "mt-1.5 w-1.5 h-1.5 rounded-full shrink-0",
                r.tone ? TONE_DOT[r.tone] : "bg-slate-300",
              )}
              aria-hidden
            />
            <span className="min-w-0 flex-1">
              <span className={cn(r.weight === "primary" ? "font-semibold" : "")}>{r.signal}</span>
              {!compact && (
                <span className="ml-1.5 text-[10px] muted">
                  · {NODE_WEIGHT_LABEL[r.weight]} · {r.source}
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
      {compact && rationale.length > visible.length && (
        <div className="text-caption muted">
          + {rationale.length - visible.length} supporting signal{rationale.length - visible.length === 1 ? "" : "s"}
        </div>
      )}
    </div>
  );
}

// ────────── Owner ──────────

export function OwnerChip({ owner }: { owner: OwnerRecommendation }) {
  return (
    <div className="rounded-lg border border-[var(--color-edify-border)] bg-white px-3 py-2">
      <div className="flex items-center gap-2">
        <UserIcon size={12} className="text-[var(--color-edify-primary)] shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="text-caption muted font-bold uppercase tracking-wide">Recommended owner</div>
          <div className="text-body font-extrabold truncate">{owner.name} <span className="text-caption muted font-semibold">· {owner.role}</span></div>
        </div>
        {owner.fairnessAdjusted && (
          <span className="text-[10px] font-bold px-1.5 py-[2px] rounded-md bg-violet-100 text-violet-700 shrink-0" title="Owner selected after fairness check">
            fairness-checked
          </span>
        )}
      </div>
      <div className="text-[11.5px] muted leading-snug mt-1">{owner.reasoning}</div>
    </div>
  );
}

// ────────── Cost ──────────

const ugxFormatter = new Intl.NumberFormat("en-UG", { maximumFractionDigits: 0 });

export function formatUgx(amount: number): string {
  return `UGX ${ugxFormatter.format(amount)}`;
}

export function CostStrip({ totalUgx, breakdown }: { totalUgx: number; breakdown?: { label: string; amountUgx: number; note?: string }[] }) {
  return (
    <div className="rounded-lg border border-[var(--color-edify-border)] bg-white px-3 py-2">
      <div className="flex items-baseline justify-between gap-3">
        <div className="text-caption muted font-bold uppercase tracking-wide">Estimated cost</div>
        <div className="text-[15px] font-extrabold tabular num-hero">{formatUgx(totalUgx)}</div>
      </div>
      {breakdown && breakdown.length > 0 && (
        <ul className="mt-1.5 space-y-0.5">
          {breakdown.map((line, i) => (
            <li key={i} className="flex items-baseline justify-between gap-2 text-[11.5px]">
              <span className="muted">
                {line.label}
                {line.note && <span className="text-caption ml-1 italic">— {line.note}</span>}
              </span>
              <span className="tabular font-semibold">{formatUgx(line.amountUgx)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ────────── Projected impact ──────────

export function ProjectedImpact({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-emerald-200 bg-emerald-50/70 px-3 py-2">
      <div className="flex items-center gap-1.5 text-caption font-bold uppercase tracking-wide text-emerald-800">
        <TrendingUp size={11} />
        Projected impact
      </div>
      <div className="text-[12px] text-emerald-900 leading-snug mt-0.5">{text}</div>
    </div>
  );
}

// ────────── Alternatives ──────────

const IMPACT_TONE: Record<DecisionAlternative["expectedImpact"], string> = {
  High:   "text-emerald-700",
  Medium: "text-amber-700",
  Low:    "text-slate-600",
};

const RISK_TONE: Record<DecisionAlternative["risk"], string> = {
  High:   "text-rose-700",
  Medium: "text-amber-700",
  Low:    "text-emerald-700",
};

export function AlternativesStrip({ alternatives }: { alternatives: DecisionAlternative[] }) {
  return (
    <div className="space-y-2">
      <div className="text-caption muted font-bold uppercase tracking-wide">Compare options</div>
      <div className="grid sm:grid-cols-2 gap-2">
        {alternatives.map((alt, i) => (
          <div
            key={i}
            className={cn(
              "rounded-lg border bg-white p-3 space-y-1.5",
              alt.recommended ? "border-emerald-300 ring-2 ring-emerald-100" : "border-[var(--color-edify-border)]",
            )}
          >
            <div className="flex items-baseline justify-between gap-2">
              <div className="text-body font-extrabold tracking-tight">{alt.label}</div>
              {alt.recommended && (
                <span className="inline-flex items-center gap-1 text-[10px] font-bold px-1.5 py-[2px] rounded-md bg-emerald-100 text-emerald-800 shrink-0">
                  <Check size={10} /> Recommended
                </span>
              )}
            </div>
            <div className="flex items-baseline gap-3 text-[11px]">
              <span className="tabular font-bold">{formatUgx(alt.costUgx)}</span>
              <span className={cn("font-semibold", IMPACT_TONE[alt.expectedImpact])}>Impact: {alt.expectedImpact}</span>
              <span className={cn("font-semibold", RISK_TONE[alt.risk])}>Risk: {alt.risk}</span>
            </div>
            <div className="text-[11.5px] muted leading-snug">{alt.projectedOutcome}</div>
            <div className="text-caption muted italic leading-snug">— {alt.reasoning}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ────────── Source / urgency meta row ──────────

const URGENCY_TONE: Record<Decision["urgency"], string> = {
  Today:       "text-rose-700 bg-rose-50 border-rose-200",
  ThisWeek:    "text-amber-700 bg-amber-50 border-amber-200",
  ThisMonth:   "text-sky-700 bg-sky-50 border-sky-200",
  ThisQuarter: "text-slate-700 bg-slate-50 border-slate-200",
};

const URGENCY_LABEL: Record<Decision["urgency"], string> = {
  Today:       "Decide today",
  ThisWeek:    "Decide this week",
  ThisMonth:   "Decide this month",
  ThisQuarter: "Decide this quarter",
};

export function MetaRow({
  urgency,
  decideBy,
  confidence,
  confidenceWhy,
}: {
  urgency: Decision["urgency"];
  decideBy?: string;
  confidence: DecisionConfidence;
  confidenceWhy?: string;
}) {
  const tone = URGENCY_TONE[urgency];
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className={cn("inline-flex items-center gap-1 px-2 py-[3px] rounded-md border text-caption font-bold", tone)}>
        <CircleDot size={10} /> {URGENCY_LABEL[urgency]}
        {decideBy && <span className="muted font-semibold">· by {formatDateShort(decideBy)}</span>}
      </span>
      <ConfidencePill level={confidence} why={confidenceWhy} />
    </div>
  );
}

function formatDateShort(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ────────── Action buttons ──────────

export function DecisionActions({
  primary,
  secondary,
  size = "default",
}: {
  primary: { label: string; href: string };
  secondary?: { label: string; href: string };
  size?: "default" | "compact";
}) {
  const primaryBtn = cn(
    "btn btn-primary",
    size === "compact" && "btn-sm",
  );
  const secondaryBtn = cn(
    "btn",
    size === "compact" && "btn-sm",
  );
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <Link href={primary.href} className={primaryBtn}>
        {primary.label}
        <ArrowRight size={size === "compact" ? 12 : 14} />
      </Link>
      {secondary && (
        <Link href={secondary.href} className={secondaryBtn}>
          {secondary.label}
          <ChevronRight size={size === "compact" ? 12 : 14} />
        </Link>
      )}
    </div>
  );
}

// ────────── Tone rail (card border accent) ──────────

export function toneRailClass(tone: Decision["tone"]): string {
  return TONE_RAIL[tone];
}
