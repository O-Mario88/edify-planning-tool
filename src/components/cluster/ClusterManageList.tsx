"use client";

// Cluster list on the hub — each engine cluster with its leader + coverage,
// plus an inline "Assign to partner" control so staff can delegate a cluster
// to a partner to manage (staff stays the owner; the partner executes).

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Network, MapPin, UserCheck, Handshake, ChevronRight, X, Pencil, Check, CalendarDays } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { assignClusterToPartnerAction, updateClusterLeaderAction } from "@/lib/actions/cluster-actions";
import { ClusterMeetingScheduler } from "./ClusterMeetingScheduler";

export type ManagedCluster = {
  id: string;
  name: string;
  district: string;
  subCounties: string[];
  schoolCount: number;
  clusterLeaderName?: string;
  clusterLeaderPhone?: string;
  managedByPartnerId?: string;
  managedByPartnerName?: string;
  meetingCount?: number;
};

export function ClusterManageList({
  clusters,
  partners,
}: {
  clusters: ManagedCluster[];
  partners: { id: string; name: string }[];
}) {
  return (
    <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
      {clusters.map((c) => (
        <ClusterRow key={c.id} cluster={c} partners={partners} />
      ))}
    </section>
  );
}

function ClusterRow({ cluster: c, partners }: { cluster: ManagedCluster; partners: { id: string; name: string }[] }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Editable leader (staff can change leadership later).
  const [editingLeader, setEditingLeader] = useState(false);
  const [leaderName, setLeaderName] = useState(c.clusterLeaderName ?? "");
  const [leaderPhone, setLeaderPhone] = useState(c.clusterLeaderPhone ?? "");

  function setPartner(partnerId: string) {
    setError(null);
    startTransition(async () => {
      const res = await assignClusterToPartnerAction(c.id, partnerId);
      if (!res.ok) {
        setError(res.reason === "FORBIDDEN" ? "No permission." : "Failed.");
        return;
      }
      setPicking(false);
      router.refresh();
    });
  }

  function saveLeader() {
    setError(null);
    startTransition(async () => {
      const res = await updateClusterLeaderAction(c.id, leaderName, leaderPhone);
      if (!res.ok) {
        setError(res.reason === "FORBIDDEN" ? "No permission." : "Failed.");
        return;
      }
      setEditingLeader(false);
      router.refresh();
    });
  }

  const place = [c.district, ...(c.subCounties ?? [])].filter(Boolean).join(" · ");

  return (
    <div className="px-4 py-3">
      <div className="flex items-start gap-3">
        <span className="grid place-items-center h-9 w-9 rounded-lg bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
          <Network size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <Link href={`/clusters/${c.id}`} className="text-[13px] font-extrabold tracking-tight hover:underline inline-flex items-center gap-1">
            {c.name} <ChevronRight size={12} className="text-[var(--color-edify-muted)]" />
          </Link>
          <p className="text-[11px] muted inline-flex items-center gap-1 mt-0.5">
            <MapPin size={9} className="text-[var(--color-edify-primary)]" />
            {c.schoolCount} school{c.schoolCount === 1 ? "" : "s"} · {place}
          </p>
          {editingLeader ? (
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <input
                value={leaderName}
                onChange={(e) => setLeaderName(e.target.value)}
                placeholder="Leader name"
                className="h-7 px-2 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] w-36"
              />
              <input
                value={leaderPhone}
                onChange={(e) => setLeaderPhone(e.target.value)}
                placeholder="Phone"
                className="h-7 px-2 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] w-32"
              />
              <button
                type="button"
                onClick={saveLeader}
                disabled={pending}
                className="inline-flex items-center gap-1 h-7 px-2 rounded-md bg-[var(--color-edify-primary)] text-white text-[11px] font-semibold disabled:opacity-50"
              >
                <Check size={11} /> Save
              </button>
              <button
                type="button"
                onClick={() => { setEditingLeader(false); setLeaderName(c.clusterLeaderName ?? ""); setLeaderPhone(c.clusterLeaderPhone ?? ""); }}
                className="text-[11px] muted hover:text-[var(--color-edify-text)]"
              >
                Cancel
              </button>
            </div>
          ) : (
            <p className="text-[11px] muted inline-flex items-center gap-1 mt-0.5">
              <UserCheck size={9} className="text-[var(--color-edify-primary)]" />
              {c.clusterLeaderName ? (
                <>Leader: <span className="font-semibold text-[var(--color-edify-text)]">{c.clusterLeaderName}</span>{c.clusterLeaderPhone ? ` · ${c.clusterLeaderPhone}` : ""}</>
              ) : (
                <span className="italic">No leader set</span>
              )}
              <button
                type="button"
                onClick={() => setEditingLeader(true)}
                className="ml-1 inline-flex items-center gap-0.5 text-[var(--color-edify-primary)] hover:underline"
                aria-label="Edit cluster leader"
              >
                <Pencil size={9} /> {c.clusterLeaderName ? "Edit" : "Set"}
              </button>
            </p>
          )}
        </div>

        {/* Partner management */}
        <div className="shrink-0 text-right">
          {c.managedByPartnerName ? (
            <div className="inline-flex flex-col items-end gap-1">
              <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg bg-violet-50 text-violet-700 text-[11px] font-bold">
                <Handshake size={11} /> {c.managedByPartnerName}
              </span>
              <button
                type="button"
                onClick={() => setPartner("")}
                disabled={pending}
                className="text-[10.5px] muted hover:text-rose-600 inline-flex items-center gap-0.5"
              >
                <X size={10} /> Remove partner
              </button>
            </div>
          ) : picking ? (
            <select
              autoFocus
              defaultValue=""
              disabled={pending}
              onChange={(e) => e.target.value && setPartner(e.target.value)}
              className="h-8 px-2 rounded-lg border border-[var(--color-edify-primary)] bg-white text-[11.5px]"
            >
              <option value="">Pick a partner…</option>
              {partners.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          ) : (
            <button
              type="button"
              onClick={() => setPicking(true)}
              className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11px] font-semibold text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60 transition-colors"
            >
              <Handshake size={12} className="text-[var(--color-edify-primary)]" /> Assign to partner
            </button>
          )}
          {error && <p className="text-[10px] text-rose-600 mt-1">{error}</p>}
        </div>
      </div>

      {/* Footer — Edify staff can run their own activities (esp. training)
          on the cluster regardless of partner delegation. */}
      <div className="mt-2.5 flex items-center gap-2 flex-wrap">
        <span className="text-[10.5px] muted inline-flex items-center gap-1">
          <CalendarDays size={11} className="text-[var(--color-edify-primary)]" />
          {c.meetingCount ? `${c.meetingCount} meeting${c.meetingCount === 1 ? "" : "s"} scheduled` : "No meetings yet"}
        </span>
        <ClusterMeetingScheduler clusterId={c.id} buttonLabel="Schedule Edify training" defaultKind="training" />
      </div>
    </div>
  );
}
