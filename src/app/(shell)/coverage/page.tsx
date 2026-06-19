import Link from "next/link";
import { Building2, ShieldCheck, AlertTriangle, ArrowRight } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { ProductiveEmptyState } from "@/components/ui/ProductiveEmptyState";
import { getCurrentUser } from "@/lib/auth";
import { fetchCoverageSummary } from "@/lib/api/surfaces";
import { cn } from "@/lib/utils";

// Module-scope so it isn't re-created on every render (react-hooks/static-components).
function Stat({ label, value, caption, tone }: { label: string; value: string | number; caption?: string; tone?: "good" | "alert" }) {
  return (
    <div className="card p-4">
      <div className="text-caption muted">{label}</div>
      <div className={cn("text-2xl font-extrabold tracking-tight mt-1", tone === "good" ? "text-emerald-600" : tone === "alert" ? "text-rose-600" : "")}>{value}</div>
      {caption ? <div className="text-[11px] muted mt-0.5">{caption}</div> : null}
    </div>
  );
}

// Client-school coverage — LIVE from the backend. Real counts of client schools,
// how many have an account owner, and which are below the SSA support threshold
// (avg < 5) and most need coverage/support.
export default async function ClientSchoolCoveragePage() {
  const user = await getCurrentUser();
  const res = await fetchCoverageSummary(user);
  if (!res.live)
    return (
      <ProductiveEmptyState
        Icon={Building2}
        title="Client-school coverage isn't connected to live data yet"
        description="Coverage counts — owned client schools and those below the SSA support threshold — are withheld until they trace to live source records."
        actionLabel="Open Analytics"
        actionHref="/analytics"
        links={[
          { label: "School directory", href: "/schools" },
          { label: "Data room", href: "/analytics/data-room" },
        ]}
        note="No placeholder coverage figures are shown."
      />
    );
  const c = res.data;

  return (
    <StubPage
      title="Client School Coverage"
      subtitle="Coverage of client schools by an account owner, and the schools below the SSA support threshold that most need attention."
    >
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Client schools" value={c.totalClientSchools.toLocaleString()} caption="in your scope" />
        <Stat label="Coverage" value={`${c.coveragePct}%`} caption={`${c.assigned.toLocaleString()} with an owner`} tone={c.coveragePct >= 90 ? "good" : undefined} />
        <Stat label="Unassigned" value={c.unassigned.toLocaleString()} caption="no account owner" tone={c.unassigned > 0 ? "alert" : "good"} />
        <Stat label="Below SSA threshold" value={c.schoolsBelowSsaThreshold.toLocaleString()} caption="avg SSA < 5 — need support" tone={c.schoolsBelowSsaThreshold > 0 ? "alert" : "good"} />
      </section>

      <section className="card p-0 overflow-hidden mt-4">
        <header className="px-4 py-3 border-b border-[var(--color-edify-divider)] flex items-center gap-2">
          <AlertTriangle size={15} className="text-amber-600" />
          <h2 className="text-body-lg font-extrabold tracking-tight">Priority schools — lowest SSA</h2>
          <span className="ml-auto text-caption muted">{c.priority.length} shown</span>
        </header>
        {c.priority.length === 0 ? (
          <div className="px-4 py-8 text-center text-[12px] muted">
            <ShieldCheck className="mx-auto text-emerald-500 mb-2" size={20} />
            No client schools are below the SSA support threshold — coverage is healthy.
          </div>
        ) : (
          <div className="divide-y divide-[var(--color-edify-divider)]">
            {c.priority.map((s) => (
              <Link key={s.schoolId} href={`/schools/${s.schoolId}`} className="px-4 py-2.5 grid grid-cols-12 gap-2 items-center text-[12px] hover:bg-[var(--color-edify-soft)]/40">
                <div className="col-span-5 inline-flex items-center gap-2 font-extrabold tracking-tight truncate">
                  <Building2 size={13} className="text-[var(--color-edify-muted)] shrink-0" /> {s.name}
                </div>
                <div className="col-span-3 text-secondary truncate">{s.district}</div>
                <div className="col-span-2 text-secondary truncate">{s.owner}</div>
                <div className="col-span-2 inline-flex items-center justify-end gap-1 font-extrabold text-rose-600">
                  SSA {s.avgSsa ?? "—"} <ArrowRight size={11} />
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </StubPage>
  );
}
