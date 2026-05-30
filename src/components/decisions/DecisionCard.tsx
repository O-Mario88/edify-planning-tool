// Decision Card — compact card used in the ranked list below the hero.
//
// Carries the same content as the hero, but tighter: headline, subject,
// meta row, primary rationale (collapsed; expandable to full), cost
// chip if present, primary action. Click-to-expand reveals owner, full
// rationale, projected impact, and alternatives without leaving the page.

"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
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
  formatUgx,
  toneRailClass,
} from "./DecisionAtoms";

export function DecisionCard({ decision, index }: { decision: Decision; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const hasMore =
    decision.rationale.filter((r) => r.weight !== "primary").length > 0 ||
    !!decision.recommendedOwner ||
    !!decision.projectedImpact ||
    !!decision.alternatives?.length ||
    !!decision.costBreakdown?.length;

  return (
    <article
      className={cn(
        "card rounded-2xl overflow-hidden card-lift",
        toneRailClass(decision.tone),
      )}
      aria-labelledby={`card-${decision.id}`}
    >
      <div className="p-4 space-y-3">
        {/* Header row */}
        <div className="flex items-start gap-3">
          <div
            className="mt-0.5 w-7 h-7 rounded-md grid place-items-center text-white shrink-0"
            style={{ background: "var(--color-edify-dark)" }}
            aria-hidden
          >
            <span className="text-[11px] font-extrabold tabular num-hero">{index}</span>
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5 text-[10px] font-extrabold uppercase tracking-wider muted">
              <CategoryIcon category={decision.category} size={10} className="text-[var(--color-edify-primary)]" />
              {labelCategory(decision.category)}
              <span className="text-[var(--color-edify-divider)]">·</span>
              <span>{decision.kind === "NextBestAction" ? "Action" : "Decision"}</span>
            </div>
            <h3 id={`card-${decision.id}`} className="mt-0.5 text-[14.5px] font-extrabold tracking-tight leading-snug">
              {decision.headline}
            </h3>
            {decision.subhead && (
              <p className="text-[12px] muted mt-0.5 leading-snug">{decision.subhead}</p>
            )}
            <div className="mt-1.5">
              <SubjectLine subject={decision.subject} />
            </div>
          </div>
        </div>

        {/* Meta row */}
        <MetaRow
          urgency={decision.urgency}
          decideBy={decision.decideBy}
          confidence={decision.confidence}
          confidenceWhy={decision.confidenceWhy}
        />

        {/* Primary rationale (always visible) */}
        <RationaleChain
          rationale={decision.rationale}
          triggeredBecause={expanded ? decision.triggeredBecause : undefined}
          compact={!expanded}
        />

        {/* Cost chip (compact) when not expanded */}
        {!expanded && decision.costEstimateUgx !== undefined && (
          <div className="text-[11.5px] muted">
            <span className="font-bold text-[var(--color-edify-text)] tabular">{formatUgx(decision.costEstimateUgx)}</span>
            <span className="ml-1">estimated cost</span>
          </div>
        )}

        {/* Expanded panel */}
        {expanded && (
          <div className="space-y-2.5 pt-1">
            {decision.recommendedOwner && <OwnerChip owner={decision.recommendedOwner} />}
            {decision.costEstimateUgx !== undefined && (
              <CostStrip totalUgx={decision.costEstimateUgx} breakdown={decision.costBreakdown} />
            )}
            {decision.projectedImpact && <ProjectedImpact text={decision.projectedImpact} />}
            {decision.alternatives && decision.alternatives.length > 0 && (
              <AlternativesStrip alternatives={decision.alternatives} />
            )}
            <div className="text-caption muted pt-1">
              Generated from {decision.sourceSignals.length} signal{decision.sourceSignals.length === 1 ? "" : "s"}: {decision.sourceSignals.join(" · ")}
            </div>
          </div>
        )}
      </div>

      {/* Footer — actions + expand toggle */}
      <div className="px-4 py-3 border-t border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/30 flex items-center justify-between gap-3 flex-wrap">
        {hasMore ? (
          <button
            type="button"
            onClick={() => setExpanded((s) => !s)}
            className="inline-flex items-center gap-1 text-[11.5px] font-bold text-[var(--color-edify-primary)] hover:underline"
            aria-expanded={expanded}
          >
            <ChevronDown
              size={12}
              className={cn("transition-transform", expanded && "rotate-180")}
            />
            {expanded ? "Show less" : "See full reasoning"}
          </button>
        ) : (
          <span /> /* keep flex spacing */
        )}
        <DecisionActions
          primary={decision.primaryAction}
          secondary={decision.secondaryAction}
          size="compact"
        />
      </div>
    </article>
  );
}

function labelCategory(category: string): string {
  return category.replace(/([A-Z])/g, " $1").trim();
}
