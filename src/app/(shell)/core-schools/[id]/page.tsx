import { notFound } from "next/navigation";
import { Building2 } from "lucide-react";
import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import { CorePageHeader } from "@/components/core/CorePageHeader";
import { CoreSchoolDetail } from "@/components/core/CoreSchoolDetail";
import { coreSchoolDetail } from "@/lib/core/core-detail";
import { isMockAllowed } from "@/lib/mock-policy";
import { ProductiveEmptyState } from "@/components/ui/ProductiveEmptyState";

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
          <ProductiveEmptyState
            Icon={Building2}
            title="This core-school lifecycle isn't wired to live records yet"
            description="The full candidate-to-champion lifecycle detail is withheld until it traces to live source records."
            actionLabel="Open Core Schools"
            actionHref="/core-schools"
            links={[{ label: "Schools", href: "/schools" }]}
            note="No fabricated school lifecycle story is shown."
          />
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
