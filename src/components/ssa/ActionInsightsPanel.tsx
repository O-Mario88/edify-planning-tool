"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertCircle, ArrowRight, Lightbulb } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import type { BeSsaPerformanceGrouped } from "@/lib/api/surfaces";

// SSA Insights & Recommendations — derived live from the backend SSA grid
// (groupBy=district). We surface the genuinely worst district and the single
// weakest intervention portfolio-wide as actionable recommendations. No mock
// fallback: empty when nothing is assessed, error on failure.

type Insight = { id: string; title: string; body: string; href: string };

function deriveInsights(data: BeSsaPerformanceGrouped): Insight[] {
  const out: Insight[] = [];
  const assessed = data.rows.filter((r) => r.overallAverage != null && r.schoolsAssessed > 0);

  // Weakest district overall.
  const worst = [...assessed].sort((a, b) => (a.overallAverage ?? 99) - (b.overallAverage ?? 99))[0];
  if (worst && worst.overallAverage != null) {
    out.push({
      id: "worst-district",
      title: `${worst.groupName} is the lowest-scoring district`,
      body: `Overall SSA average ${worst.overallAverage.toFixed(2)}/10 across ${worst.schoolsAssessed} assessed schools — prioritise intervention here.`,
      href: "/schools",
    });
  }

  // Weakest intervention portfolio-wide (school-weighted).
  let weakCode: string | null = null;
  let weakAvg = Infinity;
  for (const iv of data.interventions) {
    let sum = 0;
    let w = 0;
    for (const r of data.rows) {
      const v = r.interventions[iv.code];
      if (v != null && r.schoolsAssessed > 0) {
        sum += v * r.schoolsAssessed;
        w += r.schoolsAssessed;
      }
    }
    if (w > 0) {
      const avg = sum / w;
      if (avg < weakAvg) {
        weakAvg = avg;
        weakCode = iv.code;
      }
    }
  }
  if (weakCode) {
    const label = data.interventions.find((iv) => iv.code === weakCode)?.label ?? weakCode;
    out.push({
      id: "weak-intervention",
      title: `${label} is the weakest intervention`,
      body: `Portfolio-wide average ${weakAvg.toFixed(2)}/10 — the highest-leverage area to target across schools.`,
      href: "/schools",
    });
  }

  return out;
}

export function ActionInsightsPanel() {
  const [insights, setInsights] = useState<Insight[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/analytics/ssa-performance?groupBy=district&schoolType=all", {
        credentials: "include",
      });
      const j = (await res.json()) as (BeSsaPerformanceGrouped & { live?: boolean; error?: string }) | null;
      if (!res.ok || !j || j.live === false) {
        setError(j?.error ?? "Could not load SSA insights.");
        setInsights(null);
      } else {
        setInsights(deriveInsights(j));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
      setInsights(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <SectionCard title="SSA Insights & Recommendations">
      {loading ? (
        <LoadingState message="Loading insights…" compact />
      ) : error ? (
        <ErrorState message={error} onRetry={load} compact />
      ) : !insights || insights.length === 0 ? (
        <EmptyState
          compact
          icon={Lightbulb}
          title="No recommendations yet"
          message="SSA recommendations appear once schools in scope have a completed self-assessment."
        />
      ) : (
        <div className="flex-1 flex flex-col gap-2.5">
          {insights.map((a) => (
            <Link
              key={a.id}
              href={a.href}
              className="flex-1 flex items-center gap-3 rounded-xl border bg-rose-50 border-rose-200 px-3.5 py-3 hover:opacity-95 transition-opacity"
            >
              <span className="w-9 h-9 rounded-lg grid place-items-center shrink-0 bg-rose-100 text-rose-700">
                <AlertCircle size={16} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-body font-bold leading-tight">{a.title}</div>
                <div className="text-[11px] muted mt-0.5 leading-snug">{a.body}</div>
              </div>
              <ArrowRight size={13} className="text-[var(--color-edify-muted)] shrink-0" />
            </Link>
          ))}
        </div>
      )}
    </SectionCard>
  );
}
