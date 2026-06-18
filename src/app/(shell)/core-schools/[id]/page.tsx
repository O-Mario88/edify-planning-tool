import { notFound } from "next/navigation";
import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import { CorePageHeader } from "@/components/core/CorePageHeader";
import { CoreSchoolDetail } from "@/components/core/CoreSchoolDetail";
import { coreSchoolDetail } from "@/lib/core/core-detail";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

export const dynamic = "force-dynamic";

// Core School detail — the full lifecycle story for one schoolId. Reads the
// unified model only (no replica). 11 tabs from candidate to champion.
export default async function CoreSchoolDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  // The core-school lifecycle detail is built from hand-mocked fixtures
  // (core-detail); no live core-school backend. Withhold rather than render a
  // fabricated school lifecycle.
  if (!isMockAllowed()) {
    return (
      <>
        <CorePageHeader icon="schools" title="Core School" subtitle="Core School lifecycle" />
        <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6">
          <InsufficientData surface="this core-school lifecycle" detail="The core-school lifecycle detail is withheld until it is wired to live backend records — no fabricated school story is shown." />
        </div>
        <RoleBottomNav />
      </>
    );
  }

  const vm = coreSchoolDetail(id);
  if (!vm) notFound();

  const body = (
    <>
      <CorePageHeader
        icon="schools"
        title={vm.schoolName}
        subtitle={`Core School · ${vm.district}${vm.cluster ? ` · ${vm.cluster}` : ""} · ${vm.plan?.status ?? "No core plan"}`}
      />
      <CoreSchoolDetail vm={vm} />
      <RoleBottomNav />
    </>
  );
  return body;
}
