import Link from "next/link";
import { ArrowLeft, Sparkles, Handshake, ShieldCheck, ChevronRight, AlertTriangle } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { MetricStrip } from "@/components/ui/MetricStrip";
import {
  generatePartnerAssignmentRecommendations,
  type PartnerCertification,
} from "@/lib/coverage-mock";
import { cn } from "@/lib/utils";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

const CERT_TONE: Record<PartnerCertification, string> = {
  "Certified":     "bg-emerald-100 text-emerald-700",
  "Probationary":  "bg-amber-100   text-amber-700",
  "Suspended":     "bg-rose-100    text-rose-700",
};

export default function PartnerAssignmentRecommendationsPage() {
  if (!isMockAllowed()) return <InsufficientData surface="partner-assignment recommendations" />;
  const recs = generatePartnerAssignmentRecommendations();
  const totalSchools = recs.reduce((a, r) => a + r.schoolCount, 0);

  return (
    <StubPage
      title="Partner Assignment Recommendations"
      subtitle="System-generated recommendations ranking remaining client schools by SSA risk and matching them to certified partners with capacity, district coverage, and the right specialization."
    >
      <Link
        href="/coverage"
        className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline -mt-2"
      >
        <ArrowLeft size={11} />
        Back to Coverage
      </Link>

      <MetricStrip
        columns="grid-cols-2 md:grid-cols-4"
        metrics={[
          { key: "recs", label: "Recommendations", value: String(recs.length), caption: "Awaiting assignment" },
          { key: "schools", label: "Schools to cover", value: totalSchools.toLocaleString(), caption: "Ranked by SSA risk", tone: "alert" },
          { key: "partners", label: "Certified partners", value: "6", caption: "With capacity to absorb", tone: "good" },
          { key: "highRisk", label: "High-risk schools", value: "76", caption: "SSA < 5 or no FY SSA", tone: "alert" },
        ]}
      />

      <ol className="space-y-3">
        {recs.map((r) => (
          <li key={r.id} className="card p-3.5">
            <header className="flex items-start gap-3 mb-2">
              <span className="h-10 w-10 rounded-xl bg-violet-100 text-violet-700 grid place-items-center shrink-0">
                <Sparkles size={16} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-[13.5px] font-extrabold tracking-tight">{r.schoolBatch}</div>
                <div className="text-[11px] muted">
                  {r.district} · {r.cluster} · weakest intervention: <span className="font-extrabold text-[var(--color-edify-text)]">{r.weakestIntervention}</span>
                </div>
              </div>
              <span className="text-[18px] font-extrabold tabular text-violet-700 shrink-0">{r.schoolCount}</span>
            </header>

            <p className="text-[11.5px] muted leading-snug mb-3">{r.reason}</p>

            {/* Recommended partner card */}
            <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-3">
              <div className="flex items-start gap-3">
                <span className="h-9 w-9 rounded-md bg-emerald-100 text-emerald-700 grid place-items-center shrink-0">
                  <Handshake size={14} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2 flex-wrap">
                    <span className="text-body font-extrabold tracking-tight">Recommended: {r.recommendedPartner.partnerName}</span>
                    <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap", CERT_TONE[r.recommendedPartner.certification])}>
                      <ShieldCheck size={9} className="mr-0.5" />
                      {r.recommendedPartner.certification}
                    </span>
                  </div>
                  <div className="text-caption muted mt-0.5">
                    {r.recommendedPartner.region} · {r.recommendedPartner.districts.join(", ")} · specialises in {r.recommendedPartner.specialization}
                  </div>
                  <div className="text-caption mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
                    <span><span className="muted">Capacity:</span> <span className="font-extrabold">{r.recommendedPartner.capacityPct}%</span></span>
                    <span><span className="muted">Verification pass:</span> <span className="font-extrabold">{r.recommendedPartner.verificationPassRate}%</span></span>
                    <span><span className="muted">Salesforce:</span> <span className="font-extrabold">{r.recommendedPartner.salesforceCompliancePct}%</span></span>
                  </div>
                </div>
                <div className="flex flex-col gap-1.5 shrink-0">
                  <button
                    type="button"
                    className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-body font-semibold inline-flex items-center gap-1.5"
                  >
                    Assign
                    <ChevronRight size={12} />
                  </button>
                  <Link
                    href={`/partners/${r.recommendedPartner.partnerId}`}
                    className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white text-body font-semibold inline-flex items-center justify-center gap-1"
                  >
                    View partner
                  </Link>
                </div>
              </div>
            </div>

            {/* Alternative partners */}
            {r.alternativePartners.length > 0 && (
              <div className="mt-2.5">
                <div className="text-caption font-extrabold uppercase tracking-wide muted mb-1.5">Alternatives</div>
                <ul className="space-y-1.5">
                  {r.alternativePartners.map((p) => (
                    <li key={p.partnerId} className="flex items-center gap-2 text-[11.5px]">
                      <span className="h-6 w-6 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                        <Handshake size={11} />
                      </span>
                      <span className="font-extrabold tracking-tight">{p.partnerName}</span>
                      <span className={cn("inline-flex items-center px-1.5 py-[1px] rounded-md text-[9.5px] font-extrabold shrink-0", CERT_TONE[p.certification])}>
                        {p.certification}
                      </span>
                      <span className="muted shrink-0">· capacity {p.capacityPct}% · {p.verificationPassRate}% pass</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </li>
        ))}
      </ol>

      <section className="card p-3.5 border-amber-200 bg-amber-50/40 flex items-start gap-3">
        <span className="h-9 w-9 rounded-md bg-amber-100 text-amber-700 grid place-items-center shrink-0">
          <AlertTriangle size={16} />
        </span>
        <div className="flex-1 min-w-0">
          <h3 className="text-[13px] font-extrabold tracking-tight">Why these recommendations matter</h3>
          <p className="text-[11.5px] muted">
            Schools with weakest SSA performance must receive partner support FIRST. The system ranks remaining
            schools by SSA risk (no current-FY SSA → SSA &lt; 5 → SSA 5–6.9 → weak intervention scores) and matches them to certified partners with capacity, geographic
            coverage, and aligned specialization. Non-certified partner visits do not count toward coverage.
          </p>
        </div>
      </section>
    </StubPage>
  );
}

