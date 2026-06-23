import { redirect } from "next/navigation";
import Link from "next/link";
import { GraduationCap, ArrowRight, School } from "lucide-react";
import { EntityIndex } from "@/components/shell/EntityIndex";
import { resolveCoreOnboardingQueue } from "@/lib/core/core-candidates";
import { CoreOnboardControls } from "@/components/core/CoreOnboardControls";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";

export const dynamic = "force-dynamic";

// Core Onboarding Queue — Verified Potential Core schools awaiting onboarding.
// Onboarding flips the school to Core and creates the real core plan.
const ALLOWED = new Set(["CountryDirector", "CountryProgramLead", "ImpactAssessment", "Admin"]);

export default async function CoreOnboardingPage() {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) redirect(ROLE_REDIRECT[user.role]);

  const queue = await resolveCoreOnboardingQueue({ email: user.email, role: user.role });

  return (
    <EntityIndex
      title="Core Onboarding Queue"
      subtitle="Verified Potential Core schools awaiting onboarding. Onboarding creates the core plan (4 priority interventions, 4 visits + 4 trainings) and flips the school to Core."
      Icon={GraduationCap}
      count={queue.length}
      searchPlaceholder="Search verified candidates"
    >
      {queue.length === 0 ? (
        <section className="card p-8 text-center">
          <School className="mx-auto text-[var(--color-edify-primary)]" size={28} />
          <h2 className="text-[13px] font-extrabold tracking-tight mt-2">Onboarding queue is clear</h2>
          <p className="text-[11.5px] muted max-w-md mx-auto mt-1">
            Verify a candidate from the{" "}
            <Link href="/ssa/core-candidates" className="font-bold text-[var(--color-edify-primary)] hover:underline">SSA Core Candidates</Link>{" "}
            page and it lands here for onboarding.
          </p>
        </section>
      ) : (
        <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
          {queue.map((c) => (
            <div key={c.schoolId} className="flex items-center gap-3 px-4 py-3.5 flex-wrap">
              <span className="h-9 w-9 rounded-md grid place-items-center shrink-0 bg-emerald-100 text-emerald-700">
                <GraduationCap size={15} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-body font-extrabold tracking-tight truncate">
                  {c.schoolName} <span className="text-[10px] muted tabular font-semibold">ID {c.schoolId}</span>
                </div>
                <div className="text-caption muted truncate">
                  {c.district}{c.cluster ? ` · ${c.cluster}` : ""} · Owner {c.accountOwnerName ?? "—"} · Baseline SSA {c.averageScore.toFixed(1)} · Verified ID {c.verificationId}
                </div>
                <div className="text-[10.5px] muted mt-0.5">Recommended: {c.recommendedOnboardingMonth} · {c.recommendedOnboardingFy}</div>
              </div>
              <CoreOnboardControls schoolId={c.schoolId} schoolName={c.schoolName} />
              <Link href={`/schools/${c.schoolId}`} className="btn btn-sm" aria-label={`View ${c.schoolName}`}>
                View <ArrowRight size={12} />
              </Link>
            </div>
          ))}
        </section>
      )}
    </EntityIndex>
  );
}
