"use client";

// Cluster list on the hub — each engine cluster with its leader + coverage,
// plus an inline "Assign to partner" control so staff can delegate a cluster
// to a partner to manage (staff stays the owner; the partner executes).

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Network, MapPin, UserCheck, Handshake, ChevronRight, X } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { assignClusterToPartnerAction } from "@/lib/actions/cluster-actions";

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

  const place = [c.district, ...(c.subCounties ?? [])].filter(Boolean).join(" · ");

  return (
    <div className="px-4 py-3">
      <div className="flex items-start gap-3">
        <span className="grid place-items-center h-9 w-9 rounded-lg bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
          <Network size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <Link href="/clusters/assign" className="text-[13px] font-extrabold tracking-tight hover:underline inline-flex items-center gap-1">
            {c.name} <ChevronRight size={12} className="text-[var(--color-edify-muted)]" />
          </Link>
          <p className="text-[11px] muted inline-flex items-center gap-1 mt-0.5">
            <MapPin size={9} className="text-[var(--color-edify-primary)]" />
            {c.schoolCount} school{c.schoolCount === 1 ? "" : "s"} · {place}
          </p>
          {c.clusterLeaderName && (
            <p className="text-[11px] muted inline-flex items-center gap-1 mt-0.5">
              <UserCheck size={9} className="text-[var(--color-edify-primary)]" />
              Leader: <span className="font-semibold text-[var(--color-edify-text)]">{c.clusterLeaderName}</span>
              {c.clusterLeaderPhone ? ` · ${c.clusterLeaderPhone}` : ""}
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
    </div>
  );
}
