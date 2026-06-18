import Link from "next/link";
import { ArrowLeft, Sparkles, AlertTriangle, ArrowRight, ShieldCheck, Building2 } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { ProductiveEmptyState } from "@/components/ui/ProductiveEmptyState";
import { getCurrentUser } from "@/lib/auth";
import { fetchCoverageSummary } from "@/lib/api/surfaces";

// Coverage recommendations — LIVE. The client schools below the SSA support
// threshold (avg < 5), ranked weakest-first: these are the schools to prioritise
// for a support visit / partner assignment.
export default async function CoverageRecommendationsPage() {
  const user = await getCurrentUser();
  const res = await fetchCoverageSummary(user);
  if (!res.live)
    return (
      <ProductiveEmptyState
        Icon={Sparkles}
        tone="info"
        title="No coverage recommendations from live data yet"
        description="Client schools ranked by SSA need will appear here once the backend returns live coverage data."
        actionLabel="Open coverage"
        actionHref="/coverage"
        links={[{ label: "Analytics", href: "/analytics" }]}
      />
    );
  const c = res.data;

  return (
    <StubPage
      title="Coverage Recommendations"
      subtitle="Client schools ranked by SSA need — the weakest schools to prioritise for a support visit or partner assignment."
    >
      <Link href="/coverage" className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline -mt-2">
        <ArrowLeft size={11} /> Back to coverage
      </Link>

      <section className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 flex items-center gap-3 mt-3">
        <Sparkles className="text-amber-600" size={20} />
        <div>
          <div className="text-[13px] font-extrabold tracking-tight">
            {c.schoolsBelowSsaThreshold} client school{c.schoolsBelowSsaThreshold === 1 ? "" : "s"} below the SSA threshold
          </div>
          <div className="text-[11.5px] muted">Out of {c.totalClientSchools.toLocaleString()} client schools · {c.coveragePct}% have an owner.</div>
        </div>
      </section>

      <section className="card p-0 overflow-hidden mt-4">
        <header className="px-4 py-3 border-b border-[var(--color-edify-divider)] flex items-center gap-2">
          <AlertTriangle size={15} className="text-amber-600" />
          <h2 className="text-body-lg font-extrabold tracking-tight">Recommended for support (weakest first)</h2>
        </header>
        {c.priority.length === 0 ? (
          <div className="px-4 py-8 text-center text-[12px] muted">
            <ShieldCheck className="mx-auto text-emerald-500 mb-2" size={20} />
            No client schools are below the SSA support threshold — no urgent recommendations.
          </div>
        ) : (
          <div className="divide-y divide-[var(--color-edify-divider)]">
            {c.priority.map((s, i) => (
              <div key={s.schoolId} className="px-4 py-2.5 grid grid-cols-12 gap-2 items-center text-[12px]">
                <div className="col-span-1 font-extrabold text-[var(--color-edify-muted)]">#{i + 1}</div>
                <div className="col-span-5 inline-flex items-center gap-2 font-extrabold tracking-tight truncate">
                  <Building2 size={13} className="text-[var(--color-edify-muted)] shrink-0" /> {s.name}
                </div>
                <div className="col-span-2 text-secondary truncate">{s.district}</div>
                <div className="col-span-2 font-extrabold text-rose-600">SSA {s.avgSsa ?? "—"}</div>
                <div className="col-span-2 text-right">
                  <Link href={`/schools/${s.schoolId}?view=plan`} className="inline-flex items-center gap-1 h-7 px-2.5 rounded-lg bg-[var(--color-edify-primary)] text-white text-[11px] font-semibold hover:opacity-90">
                    Plan support <ArrowRight size={11} />
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </StubPage>
  );
}
