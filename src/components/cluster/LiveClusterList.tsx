"use client";

// Backend-backed cluster list for the Clusters hub. Self-fetches the live
// /api/clusters proxy (GET /clusters, role-scoped) and renders the existing
// ClusterManageList. No mock fallback: in-flight → LoadingState, backend
// failure → ErrorState (retryable), zero records → EmptyState.
//
// The backend cluster record (BeCluster) carries id/name/district/sub-county
// and a school count, but not the cluster-leader / partner-delegation /
// meeting fields the row UI can edit — those default to empty here and are
// populated as the user manages each cluster.

import { useCallback, useEffect, useState } from "react";
import { Network } from "lucide-react";
import { ClusterManageList, type ManagedCluster } from "./ClusterManageList";
import { LoadingState, EmptyState, ErrorState } from "@/components/ui/DataStates";

type BeCluster = {
  id: string;
  name: string;
  clusterType?: string;
  status?: string;
  district?: { name: string } | null;
  subCounty?: { name: string } | null;
  subCountyName?: string | null;
  responsibleStaffId?: string | null;
  _count?: { schools: number };
};

function toManaged(c: BeCluster): ManagedCluster {
  const subCounty = c.subCounty?.name ?? c.subCountyName ?? undefined;
  return {
    id: c.id,
    name: c.name,
    district: c.district?.name ?? "",
    subCounties: subCounty ? [subCounty] : [],
    schoolCount: c._count?.schools ?? 0,
  };
}

export function LiveClusterList({ partners }: { partners: { id: string; name: string }[] }) {
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "error"; at: number }
    | { kind: "ready"; clusters: ManagedCluster[] }
  >({ kind: "loading" });

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const res = await fetch("/api/clusters", { cache: "no-store" });
      const json = await res.json();
      if (!res.ok || json?.live === false) {
        setState({ kind: "error", at: Date.now() });
        return;
      }
      const clusters: BeCluster[] = Array.isArray(json?.clusters) ? json.clusters : [];
      setState({ kind: "ready", clusters: clusters.map(toManaged) });
    } catch {
      setState({ kind: "error", at: Date.now() });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (state.kind === "loading") return <LoadingState message="Loading clusters…" />;
  if (state.kind === "error") {
    return <ErrorState message="Could not load clusters." onRetry={load} at={state.at} />;
  }
  if (state.clusters.length === 0) {
    return (
      <EmptyState
        icon={Network}
        title="No clusters yet"
        message="Use “New cluster” to create one, then assign schools from the workspace."
      />
    );
  }
  return <ClusterManageList clusters={state.clusters} partners={partners} />;
}
