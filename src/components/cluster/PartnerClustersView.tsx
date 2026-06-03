// Partner-facing view of the clusters delegated to them to manage. Server
// component — renders the partner's clusters with their leader, schools, and
// scheduled meetings, plus an inline scheduler. Staff still run Edify-organised
// activities on these clusters separately (shown as "Edify" meetings here).

import { Network, MapPin, UserCheck, CalendarDays, Building2 } from "lucide-react";
import { ClusterMeetingScheduler } from "./ClusterMeetingScheduler";
import {
  clustersManagedByPartner,
  meetingsForCluster,
  schoolsInCluster,
  CLUSTER_MEETING_LABEL,
} from "@/lib/cluster/cluster-core";

export function PartnerClustersView({ partnerId }: { partnerId: string }) {
  const clusters = clustersManagedByPartner(partnerId);

  if (clusters.length === 0) {
    return (
      <div className="card rounded-2xl p-8 text-center">
        <Network size={24} className="mx-auto text-[var(--color-edify-primary)]" />
        <h2 className="text-[14px] font-extrabold mt-2">No clusters assigned to you yet</h2>
        <p className="text-[12px] muted mt-1">When a CCEO delegates a cluster to your organisation, it appears here for you to manage and schedule meetings.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {clusters.map((c) => {
        const meetings = meetingsForCluster(c.id);
        const schools = schoolsInCluster(c.id).length;
        return (
          <section key={c.id} className="card rounded-2xl p-4">
            <div className="flex items-start gap-3">
              <span className="grid place-items-center h-9 w-9 rounded-lg bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
                <Network size={15} />
              </span>
              <div className="min-w-0 flex-1">
                <h3 className="text-[13px] font-extrabold tracking-tight">{c.name}</h3>
                <p className="text-[11px] muted inline-flex items-center gap-1 mt-0.5">
                  <MapPin size={9} className="text-[var(--color-edify-primary)]" />
                  {c.district}{c.subCounties?.length ? ` · ${c.subCounties.join(", ")}` : ""}
                  <span className="opacity-50">·</span>
                  <Building2 size={9} /> {schools} school{schools === 1 ? "" : "s"}
                </p>
                {c.clusterLeaderName && (
                  <p className="text-[11px] muted inline-flex items-center gap-1 mt-0.5">
                    <UserCheck size={9} className="text-[var(--color-edify-primary)]" />
                    Leader: <span className="font-semibold text-[var(--color-edify-text)]">{c.clusterLeaderName}</span>
                    {c.clusterLeaderPhone ? ` · ${c.clusterLeaderPhone}` : ""}
                  </p>
                )}
              </div>
            </div>

            {/* Scheduled meetings */}
            <div className="mt-3 rounded-lg border border-[var(--color-edify-divider)] divide-y divide-[var(--color-edify-divider)]">
              {meetings.length === 0 ? (
                <p className="px-3 py-2.5 text-[11.5px] muted">No meetings scheduled yet.</p>
              ) : (
                meetings.map((m) => (
                  <div key={m.id} className="px-3 py-2 flex items-center gap-2 text-[11.5px]">
                    <CalendarDays size={12} className="text-[var(--color-edify-primary)] shrink-0" />
                    <span className="font-semibold">{CLUSTER_MEETING_LABEL[m.kind]}</span>
                    <span className="muted">{m.date}</span>
                    <span className={`ml-auto px-1.5 py-[1px] rounded text-[10px] font-bold ${m.organizer === "partner" ? "bg-violet-50 text-violet-700" : "bg-sky-50 text-sky-700"}`}>
                      {m.organizer === "partner" ? "Partner" : "Edify"}
                    </span>
                  </div>
                ))
              )}
            </div>

            <div className="mt-2.5">
              <ClusterMeetingScheduler clusterId={c.id} buttonLabel="Schedule cluster meeting" />
            </div>
          </section>
        );
      })}
    </div>
  );
}
