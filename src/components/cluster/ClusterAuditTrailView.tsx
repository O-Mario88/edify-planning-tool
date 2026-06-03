import {
  FolderPlus,
  ArrowRightLeft,
  LogIn,
  LogOut,
  ShieldCheck,
  Copy,
  Archive,
  Handshake,
  History,
  type LucideIcon,
} from "lucide-react";
import {
  clusterAudit,
  clusterById,
  type ClusterAuditEntry,
} from "@/lib/cluster/cluster-core";
import { cn } from "@/lib/utils";

// Read-only audit timeline for cluster mutations. Pure server render off the
// engine's append-only `clusterAudit` store — no mutation, no time/random APIs.

type ActionMeta = {
  label: string;
  Icon: LucideIcon;
  tone: string;
};

const ACTION_META: Record<ClusterAuditEntry["action"], ActionMeta> = {
  cluster_created: {
    label: "Cluster created",
    Icon: FolderPlus,
    tone: "text-emerald-400",
  },
  school_assigned: {
    label: "School assigned",
    Icon: LogIn,
    tone: "text-sky-400",
  },
  school_reassigned: {
    label: "School reassigned",
    Icon: ArrowRightLeft,
    tone: "text-amber-400",
  },
  school_removed: {
    label: "School removed from cluster",
    Icon: LogOut,
    tone: "text-rose-400",
  },
  ia_corrected: {
    label: "IA correction",
    Icon: ShieldCheck,
    tone: "text-violet-400",
  },
  duplicate_assigned: {
    label: "Duplicate-risk school assigned",
    Icon: Copy,
    tone: "text-orange-400",
  },
  partner_assigned: {
    label: "Delegated to partner",
    Icon: Handshake,
    tone: "text-violet-400",
  },
  cluster_archived: {
    label: "Cluster archived",
    Icon: Archive,
    tone: "text-[var(--color-edify-text)] opacity-70",
  },
};

function clusterLabel(id?: string): string | undefined {
  if (!id) return undefined;
  return clusterById(id)?.name ?? id;
}

export function ClusterAuditTrailView() {
  const entries = clusterAudit.slice(0, 50);

  if (entries.length === 0) {
    return (
      <section className="card rounded-2xl p-4">
        <p className="muted text-[12.5px]">No cluster activity yet.</p>
      </section>
    );
  }

  return (
    <section className="card rounded-2xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <History className="h-4 w-4 text-[var(--color-edify-primary)]" />
        <h2 className="text-[16px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
          Recent cluster activity
        </h2>
      </div>

      <ol className="relative space-y-3">
        {entries.map((e) => {
          const meta = ACTION_META[e.action];
          const Icon = meta.Icon;
          const toCluster = clusterLabel(e.newClusterId);
          const place = [e.subCounty, e.district].filter(Boolean).join(", ");
          const stamp = e.timestamp.slice(0, 16).replace("T", " ");

          return (
            <li
              key={e.id}
              className="flex gap-3 rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)] p-3"
            >
              <div className="flex-shrink-0 pt-0.5">
                <Icon className={cn("h-4 w-4", meta.tone)} />
              </div>

              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <span className="text-[12.5px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
                    {meta.label}
                  </span>
                  <span className="muted text-[11px] tabular">{stamp}</span>
                </div>

                <p className="muted text-[12px]">
                  {e.user}
                  <span className="opacity-60"> · {e.role}</span>
                </p>

                {(e.schoolId || toCluster) && (
                  <p className="text-[12px] text-[var(--color-edify-text)]">
                    {e.schoolId && (
                      <span className="tabular">{e.schoolId}</span>
                    )}
                    {e.schoolId && toCluster && (
                      <span className="muted"> → </span>
                    )}
                    {toCluster && <span>{toCluster}</span>}
                  </p>
                )}

                {place && <p className="muted text-[12px]">{place}</p>}

                {e.reason && (
                  <p className="text-[12px] text-[var(--color-edify-text)] opacity-80">
                    “{e.reason}”
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
