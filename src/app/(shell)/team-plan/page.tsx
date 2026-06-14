import { redirect } from "next/navigation";
import { PageHeader } from "@/components/ui/PageHeader";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { buildTeamPlan } from "@/lib/cpl/team-plan-engine";
import { TeamPlanBoard } from "@/components/cpl/TeamPlanBoard";
import { CdFlagQueue } from "@/components/cpl/CdFlagQueue";
import { ClusterMeetingRecommendationsCard } from "@/components/cpl/ClusterMeetingRecommendations";
import { clusterMeetingRecommendations } from "@/lib/cluster/cluster-meeting-recommendations";

// /team-plan — the Program Lead's team execution workspace.
//
// One screen answering "what are my CCEOs doing and where is the team
// slipping?" — per-CCEO supervision cards (status label, pacing, portfolio
// gaps, blockers, recommended support) plus the SSA-guided cluster meeting
// recommendations, so reading a gap and scheduling the response live on
// the same page. The PL never needs to open every CCEO page.
export default async function TeamPlanPage() {
  const user = await getCurrentUser();
  if (!["CountryProgramLead", "Admin"].includes(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }

  const { rows, summary } = buildTeamPlan(user.staffId);
  const clusterRecs = clusterMeetingRecommendations(user.staffId);

  return (
    <>
      <PageHeader title="Team Plan" />
      <div className="px-3 sm:px-4 md:px-5 pb-24 md:pb-5 pt-3 md:pt-4 space-y-4">
        {/* Inbound CD flags — the PL acts on what the Country Director monitored. */}
        <CdFlagQueue />
        <TeamPlanBoard rows={rows} summary={summary} />
        <ClusterMeetingRecommendationsCard recommendations={clusterRecs} limit={8} />
      </div>
    </>
  );
}
