import { notFound } from "next/navigation";
import { GraduationCap } from "lucide-react";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import { PageHeader } from "@/components/ui/PageHeader";
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
      <PageHeader
        title={vm.schoolName}
        subtitle={`Core School · ${vm.district}${vm.cluster ? ` · ${vm.cluster}` : ""} · ${vm.plan?.status ?? "No core plan"}`}
        Icon={GraduationCap}
      />
      <CoreSchoolDetail vm={vm} />
      <RoleBottomNav />
    </>
  );
  return <ResponsiveDashboard mobile={body} desktop={body} />;
}
