"use client";

// SSA Verification QA — the "10% of each staff's Client portfolio must be
// VERIFIED" quality-assurance rule (spec §10–§12). Backend-driven: reads the
// team/country rollup from /api/ssa/verification-summary (role-scoped — IA/CD
// see the country, PL sees their team). No mock.

import { useEffect, useState } from "react";
import { ShieldCheck, Info, CheckCircle2, AlertTriangle } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { MetricStrip } from "@/components/ui/MetricStrip";
import type { BeSsaVerifySummary } from "@/lib/api/surfaces";

const RATE_PCT = 10;

// Accepts (and ignores) highlightStaffId for back-compat with prior call sites.
export function ClientVerificationCard(_props: { highlightStaffId?: string; compact?: boolean } = {}) {
  const [data, setData] = useState<BeSsaVerifySummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true); setError(null);
    fetch("/api/ssa/verification-summary", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setData(j as BeSsaVerifySummary); else setError(j.error || "Could not load verification QA"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const compliance = data?.compliancePct ?? 0;
  const tone = compliance >= 90 ? "#10b981" : compliance >= 70 ? "#f59e0b" : "#ef4444";

  return (
    <article className="card p-3.5 flex flex-col" id="client-verification">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><ShieldCheck size={14} /> SSA verification QA · {RATE_PCT}% rule</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-sky-50 text-sky-700 px-2 py-0.5 text-[10px] font-bold border border-sky-200">Live · scoped</span>
      </header>

      {loading ? (
        <LoadingState compact />
      ) : error ? (
        <ErrorState compact message={error} onRetry={load} />
      ) : !data || data.staffCount === 0 ? (
        <EmptyState compact title="No client portfolios in scope" message="Verification QA appears once staff have client schools assigned." />
      ) : (
        <>
          <p className="text-[11.5px] muted leading-snug mb-3 inline-flex items-start gap-1.5">
            <Info size={13} className="mt-px shrink-0 text-slate-400" />
            Every staff member must have at least <strong className="text-[var(--text-primary)]">{RATE_PCT}%</strong> of their Client-school portfolio with <strong className="text-[var(--text-primary)]">verified</strong> current-FY SSA.
          </p>

          {/* Headline: compliance ring + meeting/below */}
          <div className="flex items-center gap-4 mb-3">
            <div className="grid place-items-center w-16 h-16 rounded-full border-4 shrink-0" style={{ borderColor: tone }}>
              <div className="text-[17px] font-extrabold tabular leading-none" style={{ color: tone }}>{compliance}%</div>
              <div className="text-[7px] uppercase tracking-wide muted">compliant</div>
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-extrabold">{data.staffMeetingRequirement} of {data.staffCount} staff met the {RATE_PCT}% quota</div>
              {data.staffBelowRequirement > 0 ? (
                <div className="text-[11.5px] text-rose-600 font-semibold inline-flex items-center gap-1 mt-0.5"><AlertTriangle size={12} /> {data.staffBelowRequirement} below quota</div>
              ) : (
                <div className="text-[11.5px] text-emerald-600 font-semibold inline-flex items-center gap-1 mt-0.5"><CheckCircle2 size={12} /> All staff compliant</div>
              )}
            </div>
          </div>

          {/* QA metric strip */}
          <MetricStrip
            bare
            className="mb-2"
            columns="grid-cols-3"
            metrics={[
              { key: "verified", label: "Verified sample", value: data.totalVerifiedSample, caption: `of ${data.totalRequiredSample} required` },
              { key: "pending", label: "Partner SSA pending", value: data.partnerPendingTotal, caption: "awaiting review", tone: data.partnerPendingTotal > 0 ? "alert" : "default" },
              { key: "below", label: "Staff below quota", value: data.staffBelowRequirement, caption: "need QA", tone: data.staffBelowRequirement > 0 ? "alert" : "default" },
            ]}
          />

          {data.belowStaff.length > 0 && (
            <div className="mt-1 rounded-lg border border-rose-200 bg-rose-50/50 p-2">
              <div className="text-[10px] font-bold uppercase tracking-wide text-rose-700 mb-1">Staff below the {RATE_PCT}% sample</div>
              <ul className="space-y-0.5">
                {data.belowStaff.slice(0, 5).map((s) => (
                  <li key={s.staffId} className="flex items-center justify-between text-[11px]">
                    <span className="muted">{s.verifiedSampleCount}/{s.requiredSampleCount} verified · {s.clientPortfolioCount} client schools</span>
                    <span className="font-bold text-rose-600">gap {s.gap}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </article>
  );
}
