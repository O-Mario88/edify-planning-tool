import { StubPage } from "@/components/shell/StubPage";
import { getCurrentUser } from "@/lib/auth";
import { openDuplicateCandidates, duplicateCandidates } from "@/lib/intake/duplicate-candidates-mock";
import { DuplicateReviewQueue } from "@/components/intake/DuplicateReviewQueue";
import { Copy } from "lucide-react";
import { isMockAllowed } from "@/lib/mock-policy";
import { ProductiveEmptyState } from "@/components/ui/ProductiveEmptyState";

export default async function DuplicateReviewPage() {
  const me = await getCurrentUser();
  const allowed = ["ImpactAssessment", "Admin"].includes(me.role);

  // Duplicate-match candidates are hand-mocked (duplicate-candidates-mock); no
  // live duplicate-detection backend. Never render fabricated duplicate flags.
  if (!isMockAllowed()) {
    return (
      <StubPage
        title="Duplicate Review Queue"
        subtitle="Possible duplicate schools are flagged on upload — never blocked, never auto-merged, never deleted. Review each and decide."
      >
        {!allowed && (
          <section className="card p-3.5 border-amber-200 bg-amber-50/60">
            <h2 className="text-[13px] font-extrabold tracking-tight">Duplicate review is restricted</h2>
            <p className="text-[11.5px] muted">Only Impact Assessment and Admin resolve duplicate flags.</p>
          </section>
        )}
        <ProductiveEmptyState
          Icon={Copy}
          title="Duplicate detection isn't wired to the backend yet"
          description="Duplicate-match flags are withheld until the duplicate-detection backend is wired."
          actionLabel="Open Schools"
          actionHref="/schools"
          links={[{ label: "Analytics", href: "/analytics" }]}
          note="No fabricated look-alike matches are shown."
        />
      </StubPage>
    );
  }

  const open = openDuplicateCandidates();
  const resolved = duplicateCandidates.filter((d) => d.status !== "Open");
  const strong = open.filter((d) => d.band === "Strong").length;

  return (
    <StubPage
      title="Duplicate Review Queue"
      subtitle="Possible duplicate schools are flagged on upload — never blocked, never auto-merged, never deleted. Review each and decide."
    >
      {!allowed ? (
        <section className="card p-3.5 border-amber-200 bg-amber-50/60">
          <h2 className="text-[13px] font-extrabold tracking-tight">Duplicate review is restricted</h2>
          <p className="text-[11.5px] muted">
            Only Impact Assessment and Admin resolve duplicate flags. Schools stay live until a reviewer decides.
          </p>
        </section>
      ) : (
        <>
          <section className="grid grid-cols-3 gap-3">
            <Kpi label="Open flags"     value={open.length}  tone={open.length > 0 ? "amber" : "green"} />
            <Kpi label="Strong matches" value={strong}       tone={strong > 0 ? "rose" : "green"} />
            <Kpi label="Resolved"       value={resolved.length} tone="slate" />
          </section>

          <DuplicateReviewQueue
            flags={open.map((d) => ({
              id: d.id,
              schoolId: d.schoolId,
              schoolName: d.schoolName,
              matchSchoolId: d.matchSchoolId,
              matchSchoolName: d.matchSchoolName,
              score: d.score,
              band: d.band,
              reasons: d.reasons,
              flaggedAt: d.flaggedAt,
              flaggedBy: d.flaggedBy,
            }))}
          />

          {resolved.length > 0 && (
            <section className="card p-3.5">
              <h2 className="text-[12.5px] font-extrabold tracking-tight mb-2">Recently resolved</h2>
              <ul className="divide-y divide-[var(--color-edify-divider)]">
                {resolved.slice(0, 8).map((d) => (
                  <li key={d.id} className="py-2 flex items-center justify-between gap-2 text-[11.5px]">
                    <span className="truncate">
                      <span className="font-extrabold">{d.schoolName}</span> vs {d.matchSchoolName}
                    </span>
                    <span className={d.status === "Confirmed" ? "text-rose-700 font-extrabold" : "text-emerald-700 font-extrabold"}>
                      {d.status === "Confirmed" ? "Confirmed duplicate" : "Not a duplicate"}
                      {d.resolvedBy ? ` · ${d.resolvedBy}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="card p-3.5 text-[11.5px] muted">
            <span className="font-extrabold text-[var(--color-edify-text)]">How scoring works: </span>
            Each upload is compared to the existing roster on name similarity, district, region, sub-county, phone, and
            address. A score of 85+ is a Strong match, 60–84 is Potential. The school is always created — this queue
            only flags look-alikes for a human to confirm or dismiss.
          </section>
        </>
      )}
    </StubPage>
  );
}

const TONE: Record<string, string> = {
  amber: "text-amber-700",
  rose:  "text-rose-700",
  green: "text-emerald-700",
  slate: "text-slate-700",
};

function Kpi({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="card p-3">
      <div className="text-[10.5px] muted font-semibold truncate">{label}</div>
      <div className={`text-[22px] font-extrabold tabular tracking-tight mt-0.5 ${TONE[tone]}`}>{value}</div>
    </div>
  );
}
