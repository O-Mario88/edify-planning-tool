import { ShieldCheck, ShieldAlert, Users, Copy, FileQuestion, CheckCircle2 } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { ProductiveEmptyState } from "@/components/ui/ProductiveEmptyState";
import { getCurrentUser } from "@/lib/auth";
import { fetchSchoolDirectorySummary, fetchLeadershipSummary } from "@/lib/api/surfaces";
import { cn } from "@/lib/utils";

// Data-quality checks — LIVE from the backend. Real integrity counts over the
// caller's scope: schools missing a current-FY SSA, schools with an unmatched
// account owner, and potential duplicate schools. (Activity-level Salesforce/
// evidence gaps surface in the IA verification queue as testing generates them.)
export default async function QualityChecksPage() {
  const user = await getCurrentUser();
  const [dir, lead] = await Promise.all([
    fetchSchoolDirectorySummary(user),
    fetchLeadershipSummary(user),
  ]);
  if (!dir.live || !lead.live)
    return (
      <ProductiveEmptyState
        Icon={ShieldCheck}
        title="Data-quality checks aren't computed from live data yet"
        description="SSA, account-owner, and duplicate-school integrity counts are withheld until they trace to live source records."
        actionLabel="Open Analytics"
        actionHref="/analytics"
        links={[{ label: "Schools", href: "/schools" }]}
        note="No fabricated integrity counts are shown."
      />
    );

  const missingSsa = lead.data.ssaPending;
  const unmatchedOwners = dir.data.unmatchedOwners;
  const duplicates = dir.data.potentialDuplicates;
  const totalIssues = missingSsa + unmatchedOwners + duplicates;

  const checks = [
    { key: "ssa", label: "Schools missing current-FY SSA", value: missingSsa, Icon: FileQuestion, good: "All schools have a complete SSA" },
    { key: "owners", label: "Schools with an unmatched owner", value: unmatchedOwners, Icon: Users, good: "Every school has a matched account owner" },
    { key: "dupes", label: "Potential duplicate schools", value: duplicates, Icon: Copy, good: "No suspected duplicates" },
  ];

  return (
    <StubPage
      title="Data Quality Checks"
      subtitle={
        totalIssues === 0
          ? "No open data-quality issues across the schools in your scope. The directory is clean and ready for planning."
          : `${totalIssues} data-quality issue${totalIssues === 1 ? "" : "s"} across the schools in your scope. Resolve these so program counting stays accurate.`
      }
    >
      <section className={cn("rounded-xl border p-4 flex items-center gap-3", totalIssues === 0 ? "border-emerald-200 bg-emerald-50/60" : "border-amber-200 bg-amber-50/60")}>
        {totalIssues === 0 ? <ShieldCheck className="text-emerald-600" size={22} /> : <ShieldAlert className="text-amber-600" size={22} />}
        <div>
          <div className="text-[14px] font-extrabold tracking-tight">
            {totalIssues === 0 ? "Data quality: clean" : `Data quality: ${totalIssues} open issue${totalIssues === 1 ? "" : "s"}`}
          </div>
          <div className="text-[11.5px] muted">
            {lead.data.schools.toLocaleString()} schools checked · SSA complete {lead.data.ssaCompletePct}%
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-4">
        {checks.map((c) => (
          <div key={c.key} className="card p-4">
            <div className="flex items-center justify-between">
              <c.Icon size={16} className={c.value === 0 ? "text-emerald-600" : "text-amber-600"} />
              {c.value === 0 ? <CheckCircle2 size={15} className="text-emerald-500" /> : <span className="text-[11px] font-extrabold text-amber-700 bg-amber-100 rounded-full px-2 py-0.5">{c.value}</span>}
            </div>
            <div className={cn("text-2xl font-extrabold tracking-tight mt-2", c.value === 0 ? "text-emerald-600" : "text-amber-600")}>{c.value.toLocaleString()}</div>
            <div className="text-[12px] font-semibold mt-0.5">{c.label}</div>
            <div className="text-[11px] muted mt-1">{c.value === 0 ? c.good : "Needs attention before these schools count toward impact."}</div>
          </div>
        ))}
      </section>
    </StubPage>
  );
}
