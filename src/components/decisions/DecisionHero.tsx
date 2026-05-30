// Decision Hero — the single most important decision on the page.
//
// This is the page's emotional anchor: the one thing the user must
// understand on first glance, with the rationale visible without a
// click. Cost, owner recommendation, projected impact, and alternatives
// all sit inside the same card — no expansion, no detail drawer — so
// leadership can decide in 60 seconds.

import { CheckCircle2 } from "lucide-react";
import type { Decision } from "@/lib/decisions/decision-types";
import { cn } from "@/lib/utils";
import {
  AlternativesStrip,
  CategoryIcon,
  CostStrip,
  DecisionActions,
  MetaRow,
  OwnerChip,
  ProjectedImpact,
  RationaleChain,
  SubjectLine,
  toneRailClass,
} from "./DecisionAtoms";

export function DecisionHero({ decision }: { decision: Decision }) {
  const isAction = decision.kind === "NextBestAction";
  return (
    <article
      className={cn(
        "card-elevated rounded-2xl overflow-hidden",
        toneRailClass(decision.tone),
      )}
      aria-labelledby={`hero-${decision.id}`}
    >
      {/* Top strip — label, category, subject */}
      <div className="px-4 sm:px-5 pt-4 pb-2 flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-caption font-extrabold uppercase tracking-wider">
            <span
              className="inline-flex items-center gap-1.5 px-2 py-[3px] rounded-md text-white"
              style={{ background: "var(--color-edify-dark)" }}
            >
              <CategoryIcon category={decision.category} size={11} />
              {isAction ? "Top action" : "Top decision"}
            </span>
            <span className="text-[var(--color-edify-muted)]">· {labelCategory(decision.category)}</span>
          </div>
          <h2 id={`hero-${decision.id}`} className="mt-1.5 text-[18px] sm:text-[20px] font-extrabold tracking-tight leading-tight text-[var(--color-edify-text)]">
            {decision.headline}
          </h2>
          {decision.subhead && (
            <p className="text-[13px] muted mt-1 leading-snug">{decision.subhead}</p>
          )}
          <div className="mt-2">
            <SubjectLine subject={decision.subject} />
          </div>
        </div>
      </div>

      {/* Meta row — urgency + confidence */}
      <div className="px-4 sm:px-5 pb-3">
        <MetaRow
          urgency={decision.urgency}
          decideBy={decision.decideBy}
          confidence={decision.confidence}
          confidenceWhy={decision.confidenceWhy}
        />
      </div>

      {/* Body — split into two columns on desktop */}
      <div className="px-4 sm:px-5 grid lg:grid-cols-5 gap-4">
        {/* Left: rationale (60%) */}
        <div className="lg:col-span-3 space-y-3">
          <SectionLabel>Why this matters</SectionLabel>
          <RationaleChain
            rationale={decision.rationale}
            triggeredBecause={decision.triggeredBecause}
          />
          {decision.projectedImpact && (
            <ProjectedImpact text={decision.projectedImpact} />
          )}
        </div>

        {/* Right: owner / cost (40%) */}
        <div className="lg:col-span-2 space-y-2.5">
          {decision.recommendedOwner && (
            <OwnerChip owner={decision.recommendedOwner} />
          )}
          {decision.costEstimateUgx !== undefined && (
            <CostStrip totalUgx={decision.costEstimateUgx} breakdown={decision.costBreakdown} />
          )}
        </div>
      </div>

      {/* Alternatives — full width below */}
      {decision.alternatives && decision.alternatives.length > 0 && (
        <div className="px-4 sm:px-5 mt-4">
          <AlternativesStrip alternatives={decision.alternatives} />
        </div>
      )}

      {/* Footer — actions + sources */}
      <div className="mt-4 px-4 sm:px-5 py-3 border-t border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/40 flex items-center justify-between gap-3 flex-wrap">
        <div className="text-caption muted flex items-center gap-1.5">
          <CheckCircle2 size={11} className="text-[var(--color-edify-primary)]" />
          Generated from {decision.sourceSignals.length} signal{decision.sourceSignals.length === 1 ? "" : "s"}: {decision.sourceSignals.join(" · ")}
        </div>
        <DecisionActions
          primary={decision.primaryAction}
          secondary={decision.secondaryAction}
        />
      </div>
    </article>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-caption muted font-bold uppercase tracking-wider">{children}</div>
  );
}

function labelCategory(category: string): string {
  // Convert CamelCase to spaced words.
  return category.replace(/([A-Z])/g, " $1").trim();
}
