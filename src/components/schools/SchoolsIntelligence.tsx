"use client";

// SchoolsIntelligence — the new Schools Directory hero.
//
// Three purpose-driven tabs answer the questions CD / PL / IA / CCEO
// open this page to ask:
//
//   1. Priority Schools — which schools need urgent action now?
//   2. Most Improved    — which schools are improving?
//   3. Struggling       — which schools are struggling by intervention?
//
// All ranking comes from lib/schools-intelligence.ts so the scoring
// contract is one file, one source of truth. The page reads, ranks,
// renders — nothing here mutates state.
//
// Layout: token-driven cards on a responsive grid. Mobile stacks to
// 1-up; tablet+ shows 2-up so a CCEO can compare a few at a glance.

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertOctagon,
  TrendingUp,
  AlertTriangle,
  MapPin,
  ChevronRight,
  ArrowUp,
  ArrowDown,
  Minus,
  Search,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  type SchoolRow,
  type Priority,
} from "@/lib/schools-mock";
import {
  type Intervention,
  type InterventionStatus,
  type ImprovementBand,
  INTERVENTIONS,
  priorityAssessmentFor,
  improvementFor,
  improvementBand,
  weakestInterventionFor,
  recommendedActionFor,
  strugglingInterventionsFor,
  isStruggling,
  rankForPriority,
  rankForImprovement,
  rankForStruggleIn,
  shortInterventionName,
  interventionScoresFor,
  statusForInterventionScore,
} from "@/lib/schools-intelligence";

// ─────────────────────────── Tab nav ────────────────────────────

type TabKey = "priority" | "improved" | "struggling";

const TABS: Array<{ key: TabKey; label: string; sub: string; Icon: LucideIcon }> = [
  { key: "priority",   label: "Priority Schools", sub: "Urgent action needed", Icon: AlertOctagon },
  { key: "improved",   label: "Most Improved",    sub: "SSA growth this cycle", Icon: TrendingUp },
  { key: "struggling", label: "Struggling",       sub: "By intervention area",  Icon: AlertTriangle },
];

export function SchoolsIntelligence({
  schools,
}: {
  schools: SchoolRow[];
}) {
  const [tab, setTab] = useState<TabKey>("priority");
  const [query, setQuery] = useState("");
  const [intervention, setIntervention] = useState<Intervention | "ALL">("ALL");

  // Free-text filter — narrows by school name / district / hub.
  const searched = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return schools;
    return schools.filter((s) =>
      s.schoolName.toLowerCase().includes(q) ||
      s.district.toLowerCase().includes(q) ||
      s.shippingAddress.toLowerCase().includes(q),
    );
  }, [schools, query]);

  return (
    <section className="space-y-3">
      {/* Top — search + tabs */}
      <div className="space-y-2.5">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by school, district, hub…"
            className="premium-input pl-9"
            aria-label="Search schools"
          />
        </div>

        {/* Tab strip — phone uses a native select for one-tap switch;
            tablet+ shows the full segmented row. */}
        <div className="md:hidden">
          <label className="block relative">
            <span className="sr-only">Schools intelligence tab</span>
            <select
              value={tab}
              onChange={(e) => setTab(e.target.value as TabKey)}
              className="premium-select font-extrabold"
            >
              {TABS.map((t) => (
                <option key={t.key} value={t.key}>{t.label}</option>
              ))}
            </select>
          </label>
        </div>
        <nav
          role="tablist"
          aria-label="Schools intelligence tabs"
          className="hidden md:grid grid-cols-3 gap-1.5 p-1 rounded-2xl bg-[var(--surface-2)] border border-[var(--border-card)]"
        >
          {TABS.map((t) => {
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setTab(t.key)}
                className={cn(
                  "flex items-center gap-2.5 px-3 py-2 rounded-xl text-left transition-all",
                  active
                    ? "bg-[var(--surface-1)] border border-[var(--border-card)] shadow-[0_2px_8px_-2px_var(--shadow-card-mid),inset_0_1px_0_var(--color-card-highlight)]"
                    : "text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--button-hover)] border border-transparent active:scale-[0.99]",
                )}
              >
                <span className={cn(
                  "grid place-items-center h-8 w-8 rounded-lg shrink-0 transition-colors",
                  active
                    ? "bg-[var(--color-edify-soft)] text-[var(--brand-primary)]"
                    : "bg-transparent text-[var(--text-muted)]",
                )}>
                  <t.Icon size={15} />
                </span>
                <span className="min-w-0">
                  <span className="block text-body font-extrabold tracking-tight text-[var(--text-primary)] truncate">
                    {t.label}
                  </span>
                  <span className="block text-caption text-[var(--text-muted)] truncate">
                    {t.sub}
                  </span>
                </span>
              </button>
            );
          })}
        </nav>
      </div>

      {/* Tab content */}
      {tab === "priority"   && <PriorityTab   schools={searched} />}
      {tab === "improved"   && <ImprovedTab   schools={searched} />}
      {tab === "struggling" && (
        <StrugglingTab
          schools={searched}
          intervention={intervention}
          onChangeIntervention={setIntervention}
        />
      )}
    </section>
  );
}

// ─────────────────────── Priority Schools ───────────────────────

function PriorityTab({ schools }: { schools: SchoolRow[] }) {
  const ranked = useMemo(() => {
    return [...schools]
      .map((s) => ({ school: s, assessment: priorityAssessmentFor(s) }))
      .sort((a, b) => b.assessment.score - a.assessment.score)
      .slice(0, 40);
  }, [schools]);

  // Headline strip — quick counts per band so the user sees the
  // priority distribution before scrolling.
  const counts: Record<Priority, number> = { Critical: 0, High: 0, Medium: 0, Low: 0 };
  ranked.forEach((r) => { counts[r.assessment.band]++; });

  return (
    <div className="space-y-3">
      <BandStrip
        items={[
          { label: "Critical", value: counts.Critical, tone: "danger"  },
          { label: "High",     value: counts.High,     tone: "warning" },
          { label: "Medium",   value: counts.Medium,   tone: "info"    },
          { label: "Low",      value: counts.Low,      tone: "neutral" },
        ]}
      />
      {ranked.length === 0 ? (
        <EmptyState label="No schools match this filter." />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {ranked.map((r) => (
            <PriorityCard key={r.school.schoolId} school={r.school} assessment={r.assessment} />
          ))}
        </div>
      )}
    </div>
  );
}

function PriorityCard({
  school,
  assessment,
}: {
  school: SchoolRow;
  assessment: ReturnType<typeof priorityAssessmentFor>;
}) {
  const weak = weakestInterventionFor(school);
  const recommended = recommendedActionFor(school);
  return (
    <article className="premium-card p-4 flex flex-col gap-3">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-body-lg font-extrabold tracking-tight text-[var(--text-primary)] leading-tight">
            {school.schoolName}
          </h3>
          <p className="text-[11px] text-[var(--text-muted)] mt-0.5 inline-flex items-center gap-1.5">
            <MapPin size={10} />
            {school.district} · {school.shippingAddress}
            <span className="px-1.5 py-0.5 rounded-md bg-[var(--surface-2)] text-[var(--text-secondary)] text-[10px] font-bold uppercase tracking-wide ml-1">
              {school.segment}
            </span>
          </p>
        </div>
        <PriorityPill band={assessment.band} />
      </header>

      {assessment.factorLabels.length > 0 && (
        <ul className="space-y-1 text-[11.5px] text-[var(--text-secondary)] leading-snug">
          {assessment.factorLabels.slice(0, 4).map((f) => (
            <li key={f} className="flex items-start gap-1.5">
              <span className="w-1 h-1 rounded-full bg-[var(--brand-danger)] mt-1.5 shrink-0" />
              {f}
            </li>
          ))}
        </ul>
      )}

      <div className="grid grid-cols-2 gap-2.5 pt-1">
        <Metric
          label="Weakest area"
          value={weak.shortName}
          sub={`${weak.score.toFixed(1)}/10 · ${weak.status}`}
          tone={weak.status === "Critical" ? "danger" : weak.status === "Needs Support" ? "warning" : "neutral"}
        />
        <Metric
          label="Current SSA"
          value={`${(school.ssaScore / 10).toFixed(1)}/10`}
          sub={school.ssaStatus}
          tone={school.ssaScore < 60 ? "danger" : school.ssaScore < 75 ? "warning" : "success"}
        />
      </div>

      <div className="rounded-xl bg-[var(--surface-2)] border border-[var(--border-subtle)] p-2.5 text-[11.5px] text-[var(--text-secondary)] leading-snug">
        <span className="font-extrabold text-[var(--text-primary)]">Recommended:</span>{" "}
        {recommended.copy}
      </div>

      <footer className="flex items-center gap-2 mt-1">
        <CardLink href={`/schools/${school.schoolId}`} primary>View School</CardLink>
        <CardLink href={`/schools/${school.schoolId}?view=ssa`}>View SSA</CardLink>
        <CardLink href={`/schools/${school.schoolId}?view=plan`}>Plan Action</CardLink>
      </footer>
    </article>
  );
}

// ───────────────────────── Most Improved ─────────────────────────

function ImprovedTab({ schools }: { schools: SchoolRow[] }) {
  const ranked = useMemo(() => {
    return [...schools]
      .map((s) => ({ school: s, improvement: improvementFor(s) }))
      .filter((r) => r.improvement.delta > 0)
      .sort((a, b) => rankForImprovement(a.school, b.school))
      .slice(0, 40);
  }, [schools]);

  const counts: Record<ImprovementBand, number> = {
    "Strong Improvement": 0,
    "Meaningful Improvement": 0,
    "Small Improvement": 0,
    "No Change": 0,
    "Declined": 0,
  };
  for (const s of schools) counts[improvementBand(improvementFor(s).delta)]++;

  return (
    <div className="space-y-3">
      <BandStrip
        items={[
          { label: "Strong",     value: counts["Strong Improvement"],     tone: "success" },
          { label: "Meaningful", value: counts["Meaningful Improvement"], tone: "success" },
          { label: "Small",      value: counts["Small Improvement"],      tone: "info"    },
          { label: "Declined",   value: counts.Declined,                  tone: "danger"  },
        ]}
      />
      {ranked.length === 0 ? (
        <EmptyState label="No schools have improved in this filter." />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {ranked.map((r) => (
            <ImprovedCard key={r.school.schoolId} school={r.school} improvement={r.improvement} />
          ))}
        </div>
      )}
    </div>
  );
}

function ImprovedCard({
  school,
  improvement,
}: {
  school: SchoolRow;
  improvement: ReturnType<typeof improvementFor>;
}) {
  const sign = improvement.delta >= 0 ? "+" : "";
  return (
    <article className="premium-card p-4 flex flex-col gap-3">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-body-lg font-extrabold tracking-tight text-[var(--text-primary)] leading-tight">
            {school.schoolName}
          </h3>
          <p className="text-[11px] text-[var(--text-muted)] mt-0.5 inline-flex items-center gap-1.5">
            <MapPin size={10} />
            {school.district} · {school.shippingAddress}
          </p>
        </div>
        <ImprovementPill band={improvement.band} delta={improvement.delta} />
      </header>

      <div className="grid grid-cols-3 gap-2">
        <Metric label="Previous"  value={`${improvement.previousAvg.toFixed(1)}`} sub="SSA avg" />
        <Metric label="Current"   value={`${improvement.currentAvg.toFixed(1)}`}  sub="SSA avg" tone="success" />
        <Metric label="Change"    value={`${sign}${improvement.delta.toFixed(1)}`} sub="points" tone={improvement.delta > 0 ? "success" : "neutral"} />
      </div>

      {improvement.biggestImprovement && (
        <div className="rounded-xl bg-[var(--surface-2)] border border-[var(--border-subtle)] p-2.5 text-[11.5px] text-[var(--text-secondary)] leading-snug">
          <div className="flex items-center justify-between gap-2 mb-1.5">
            <span className="text-[10px] font-extrabold uppercase tracking-wide text-[var(--text-muted)]">
              Biggest improvement
            </span>
            <span className="text-caption font-extrabold text-[#6ee7b7]">
              +{improvement.biggestImprovement.delta.toFixed(1)}
            </span>
          </div>
          <div className="text-body font-extrabold text-[var(--text-primary)]">
            {improvement.biggestImprovement.shortName}
          </div>
        </div>
      )}

      {improvement.improvedInterventions.length > 1 && (
        <div>
          <div className="text-[10px] uppercase tracking-wide font-extrabold text-[var(--text-muted)] mb-1.5">
            All improved areas ({improvement.improvedInterventions.length})
          </div>
          <div className="flex flex-wrap gap-1.5">
            {improvement.improvedInterventions.slice(0, 5).map((i) => (
              <span key={i.intervention} className="premium-badge premium-badge-success">
                {i.shortName} <span className="opacity-80">+{i.delta.toFixed(1)}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <footer className="flex items-center gap-2 mt-1">
        <CardLink href={`/schools/${school.schoolId}?view=ssa`} primary>View SSA</CardLink>
        <CardLink href={`/schools/${school.schoolId}`}>View School</CardLink>
      </footer>
    </article>
  );
}

// ────────────────────────── Struggling ──────────────────────────

function StrugglingTab({
  schools,
  intervention,
  onChangeIntervention,
}: {
  schools: SchoolRow[];
  intervention: Intervention | "ALL";
  onChangeIntervention: (i: Intervention | "ALL") => void;
}) {
  const ranked = useMemo(() => {
    const filtered = schools.filter((s) => {
      if (!isStruggling(s)) return false;
      if (intervention === "ALL") return true;
      return interventionScoresFor(s)[intervention] < 7;
    });
    return filtered.sort(rankForStruggleIn(intervention)).slice(0, 40);
  }, [schools, intervention]);

  return (
    <div className="space-y-3">
      {/* Intervention filter chips — horizontal scroll on mobile */}
      <div
        role="tablist"
        aria-label="Struggle by intervention"
        className="flex items-center gap-1.5 overflow-x-auto scrollbar pb-1 -mx-1 px-1"
      >
        <InterventionChip
          active={intervention === "ALL"}
          onClick={() => onChangeIntervention("ALL")}
        >
          All Interventions
        </InterventionChip>
        {INTERVENTIONS.map((i) => (
          <InterventionChip
            key={i}
            active={intervention === i}
            onClick={() => onChangeIntervention(i)}
          >
            {shortInterventionName(i)}
          </InterventionChip>
        ))}
      </div>

      {ranked.length === 0 ? (
        <EmptyState label="No schools are struggling in this area." />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {ranked.map((s) => (
            <StrugglingCard key={s.schoolId} school={s} focus={intervention} />
          ))}
        </div>
      )}
    </div>
  );
}

function StrugglingCard({
  school,
  focus,
}: {
  school: SchoolRow;
  focus: Intervention | "ALL";
}) {
  const allStruggles = strugglingInterventionsFor(school);
  // If the user picked a specific intervention filter, surface THAT
  // area at the top of the card. Otherwise show the worst.
  const headline = focus === "ALL"
    ? allStruggles[0]
    : (allStruggles.find((s) => s.intervention === focus) ?? allStruggles[0]);
  const recommended = recommendedActionFor(school);
  const other = allStruggles.filter((s) => s.intervention !== headline?.intervention);

  return (
    <article className="premium-card p-4 flex flex-col gap-3">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-body-lg font-extrabold tracking-tight text-[var(--text-primary)] leading-tight">
            {school.schoolName}
          </h3>
          <p className="text-[11px] text-[var(--text-muted)] mt-0.5 inline-flex items-center gap-1.5">
            <MapPin size={10} />
            {school.district} · {school.shippingAddress}
          </p>
        </div>
        {headline && <StatusPill status={headline.status} />}
      </header>

      {headline && (
        <div className="rounded-xl bg-[var(--surface-2)] border border-[var(--border-subtle)] p-3">
          <div className="flex items-baseline justify-between gap-2">
            <div className="min-w-0">
              <div className="text-[10px] uppercase tracking-wide font-extrabold text-[var(--text-muted)]">
                Struggling area
              </div>
              <div className="text-[13.5px] font-extrabold text-[var(--text-primary)] mt-0.5 truncate">
                {headline.shortName}
              </div>
            </div>
            <div className="text-right shrink-0">
              <div className={cn(
                "text-[20px] font-extrabold tabular leading-none",
                headline.status === "Critical"      ? "text-[#fca5a5]" :
                headline.status === "Needs Support" ? "text-[#fcd34d]" :
                                                      "text-[var(--text-primary)]",
              )}>
                {headline.current.toFixed(1)}
              </div>
              <div className="text-[10px] text-[var(--text-muted)] font-semibold">out of 10</div>
            </div>
          </div>
          <TrendRow previous={headline.previous} delta={headline.delta} />
        </div>
      )}

      {other.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wide font-extrabold text-[var(--text-muted)] mb-1.5">
            Other weak areas
          </div>
          <div className="flex flex-wrap gap-1.5">
            {other.slice(0, 4).map((s) => (
              <span key={s.intervention} className={cn(
                "premium-badge",
                s.status === "Critical"      ? "premium-badge-danger"  :
                s.status === "Needs Support" ? "premium-badge-warning" :
                                                "premium-badge-neutral",
              )}>
                {s.shortName} <span className="opacity-80">{s.current.toFixed(1)}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="text-[11.5px] text-[var(--text-secondary)] leading-snug">
        <span className="font-extrabold text-[var(--text-primary)]">Recommended:</span>{" "}
        {recommended.copy}
      </div>

      <footer className="flex items-center gap-2 mt-1">
        <CardLink href={`/schools/${school.schoolId}?view=ssa`} primary>View SSA</CardLink>
        <CardLink href={`/schools/${school.schoolId}?view=plan`}>Plan Action</CardLink>
      </footer>
    </article>
  );
}

// ───────────────────────── Shared bits ──────────────────────────

function BandStrip({
  items,
}: {
  items: Array<{ label: string; value: number; tone: "success" | "warning" | "danger" | "info" | "neutral" }>;
}) {
  return (
    <ul className="grid grid-cols-4 gap-2">
      {items.map((it) => (
        <li
          key={it.label}
          className={cn(
            "premium-card p-2.5 flex flex-col gap-0.5",
            it.tone === "danger"  && "border-[var(--border-danger)]",
            it.tone === "warning" && "border-[var(--border-warn)]",
            it.tone === "success" && "border-[var(--border-success)]",
            it.tone === "info"    && "border-[var(--border-info)]",
          )}
        >
          <span className="text-[10px] uppercase tracking-[0.06em] font-extrabold text-[var(--text-muted)] truncate">
            {it.label}
          </span>
          <span className={cn(
            "text-[20px] font-extrabold tabular num-hero leading-none",
            it.tone === "danger"  && "text-[#fca5a5]",
            it.tone === "warning" && "text-[#fcd34d]",
            it.tone === "success" && "text-[#6ee7b7]",
            it.tone === "info"    && "text-[var(--brand-info)]",
            it.tone === "neutral" && "text-[var(--text-primary)]",
          )}>
            {it.value}
          </span>
        </li>
      ))}
    </ul>
  );
}

function PriorityPill({ band }: { band: Priority }) {
  const className =
    band === "Critical" ? "premium-badge-danger"  :
    band === "High"     ? "premium-badge-warning" :
    band === "Medium"   ? "premium-badge-info"    :
                          "premium-badge-neutral";
  return <span className={cn("premium-badge", className)}>{band}</span>;
}

function ImprovementPill({ band, delta }: { band: ImprovementBand; delta: number }) {
  const className =
    band === "Strong Improvement"     ? "premium-badge-success" :
    band === "Meaningful Improvement" ? "premium-badge-success" :
    band === "Small Improvement"      ? "premium-badge-info"    :
    band === "Declined"               ? "premium-badge-danger"  :
                                        "premium-badge-neutral";
  const sign = delta >= 0 ? "+" : "";
  return (
    <span className={cn("premium-badge", className)}>
      {band === "Strong Improvement" ? <ArrowUp size={10} strokeWidth={3} /> :
       band === "Declined"           ? <ArrowDown size={10} strokeWidth={3} /> :
                                        <Minus size={10} strokeWidth={3} />}
      {sign}{delta.toFixed(1)}
    </span>
  );
}

function StatusPill({ status }: { status: InterventionStatus }) {
  const className =
    status === "Critical"      ? "premium-badge-danger"  :
    status === "Needs Support" ? "premium-badge-warning" :
    status === "Strong"        ? "premium-badge-success" :
                                  "premium-badge-info";
  return <span className={cn("premium-badge", className)}>{status}</span>;
}

function TrendRow({ previous, delta }: { previous: number; delta: number }) {
  const arrow = delta > 0 ? <ArrowUp size={11} strokeWidth={2.5} /> :
                delta < 0 ? <ArrowDown size={11} strokeWidth={2.5} /> :
                            <Minus size={11} strokeWidth={2.5} />;
  const sign = delta >= 0 ? "+" : "";
  return (
    <div className="flex items-center justify-between gap-2 mt-2 pt-2 border-t border-[var(--border-subtle)] text-[11px]">
      <span className="text-[var(--text-muted)]">
        Previous <span className="font-semibold text-[var(--text-secondary)] tabular">{previous.toFixed(1)}</span>
      </span>
      <span className={cn(
        "inline-flex items-center gap-1 font-extrabold tabular",
        delta > 0 ? "text-[#6ee7b7]" :
        delta < 0 ? "text-[#fca5a5]" :
                    "text-[var(--text-muted)]",
      )}>
        {arrow} {sign}{delta.toFixed(1)}
      </span>
    </div>
  );
}

function Metric({
  label, value, sub, tone = "neutral",
}: {
  label: string;
  value: string;
  sub?:  string;
  tone?: "success" | "warning" | "danger" | "neutral";
}) {
  return (
    <div className="rounded-lg bg-[var(--surface-2)] border border-[var(--border-subtle)] px-2.5 py-2">
      <div className="text-[9.5px] uppercase tracking-wide font-extrabold text-[var(--text-muted)]">
        {label}
      </div>
      <div className={cn(
        "text-[13.5px] font-extrabold tabular leading-tight mt-0.5",
        tone === "danger"  && "text-[#fca5a5]",
        tone === "warning" && "text-[#fcd34d]",
        tone === "success" && "text-[#6ee7b7]",
        tone === "neutral" && "text-[var(--text-primary)]",
      )}>
        {value}
      </div>
      {sub && <div className="text-caption text-[var(--text-muted)] mt-0.5 truncate">{sub}</div>}
    </div>
  );
}

function CardLink({
  href, children, primary = false,
}: {
  href: string;
  children: React.ReactNode;
  primary?: boolean;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "premium-button premium-button-sm",
        primary ? "premium-button-primary" : "premium-button-secondary",
      )}
    >
      {children}
      {primary && <ChevronRight size={11} />}
    </Link>
  );
}

function InterventionChip({
  active, onClick, children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      role="tab"
      aria-selected={active}
      className={cn(
        "h-8 px-3 rounded-full text-[11.5px] font-extrabold whitespace-nowrap shrink-0 transition-all",
        active
          ? "bg-[var(--brand-primary)] text-[var(--text-on-brand)] shadow-[0_2px_6px_-2px_rgba(0,0,0,0.25)]"
          : "bg-[var(--surface-2)] text-[var(--text-secondary)] border border-[var(--border-card)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)] active:scale-[0.97]",
      )}
    >
      {children}
    </button>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="premium-card p-8 text-center">
      <p className="text-[13px] text-[var(--text-muted)]">{label}</p>
    </div>
  );
}
