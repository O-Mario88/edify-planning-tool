import { ShieldCheck, Clock, AlertOctagon, CheckCircle2 } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { DataVerificationFunnelCard } from "@/components/impact/DataVerificationFunnelCard";
import { RecentDataUploadsCard } from "@/components/impact/RecentDataUploadsCard";
import { IaVerificationQueue } from "@/components/impact/IaVerificationQueue";
import { verificationFunnel, verificationRate } from "@/lib/impact-mock";
import {
  activities,
  trainingParticipants,
  partnerActivities,
} from "@/lib/actions/store";

export const dynamic = "force-dynamic";

export default function DataVerificationPage() {
  // Source the three IA queues from the live store. Each row is a
  // pre-projected shape the client component renders directly — keeps
  // the client bundle free of store / server-only imports.
  const activityRows = activities()
    .filter((a) => a.status === "SubmittedForVerification" || a.status === "Completed")
    .map((a) => ({
      id: a.id,
      title: a.title,
      status: a.status,
      planId: a.planId,
      assigneeName: a.assigneeId,
      weekOfMonth: a.weekOfMonth,
    }));
  const participantRows = trainingParticipants()
    .filter((p) => p.evidenceStatus === "CceoConfirmed" || p.evidenceStatus === "Uploaded")
    .map((p) => ({
      id: p.id,
      participantName: p.participantName,
      participantType: p.participantType,
      evidenceStatus: p.evidenceStatus,
      activityId: p.activityId,
    }));
  const partnerRows = partnerActivities()
    .filter((a) => a.status === "CceoConfirmed")
    .map((a) => ({
      id: a.id,
      title: a.title,
      partnerName: a.partnerName,
      schoolId: a.schoolId,
      status: a.status,
      evidenceStatus: a.evidenceStatus,
    }));

  return (
    <StubPage
      title="Data Verification"
      subtitle="Review every record that's been uploaded, in review, verified, failed, or resolved. Drill into any stage to action the next batch."
    >
      <IaVerificationQueue
        activities={activityRows}
        participants={participantRows}
        partnerActivities={partnerRows}
      />
      <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {verificationFunnel.map((s) => {
          const Icon =
            s.key === "uploaded"  ? ShieldCheck :
            s.key === "in-review" ? Clock       :
            s.key === "verified"  ? CheckCircle2:
            s.key === "failed-qc" ? AlertOctagon:
                                    CheckCircle2;
          return (
            <a
              key={s.key}
              href={s.href}
              className="card p-3.5 hover:shadow-md transition-shadow"
            >
              <div className="flex items-center gap-2 mb-2">
                <Icon size={14} className="text-[var(--color-edify-muted)]" />
                <span className="text-[11.5px] muted font-semibold">{s.label}</span>
              </div>
              <div className="text-[22px] font-extrabold tabular leading-none">
                {s.value.toLocaleString()}
              </div>
              <div className="text-caption muted mt-1">{s.share} of total</div>
            </a>
          );
        })}
      </section>

      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 md:col-span-5">
          <DataVerificationFunnelCard />
        </div>
        <div className="col-span-12 md:col-span-7">
          <article className="card p-3.5 h-full flex flex-col justify-center">
            <h2 className="text-body-lg font-extrabold tracking-tight mb-1">Verification Rate</h2>
            <div className="text-[44px] font-extrabold tabular text-emerald-600 leading-none mt-2">
              {verificationRate}%
            </div>
            <p className="text-[12px] muted mt-2 max-w-[420px]">
              Verified records as a share of total uploads this cycle.
              The funnel to the left shows where the unverified records sit
              today — start with In Review, then Failed QC.
            </p>
          </article>
        </div>
      </section>

      <RecentDataUploadsCard />
    </StubPage>
  );
}
