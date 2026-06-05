import { notFound } from "next/navigation";
import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import { CorePageHeader } from "@/components/core/CorePageHeader";
import { CoreSchoolDetail } from "@/components/core/CoreSchoolDetail";
import { coreSchoolDetail } from "@/lib/core/core-detail";

export const dynamic = "force-dynamic";

// Core School detail — the full lifecycle story for one schoolId. Reads the
// unified model only (no replica). 11 tabs from candidate to champion.
export default async function CoreSchoolDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
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
