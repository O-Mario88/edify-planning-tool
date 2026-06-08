"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { EntityIndex } from "@/components/shell/EntityIndex";
import { StatusBadge, type ChipTone } from "@/components/ui/primitives";
import { CheckCircle2, AlertOctagon, Footprints, type LucideIcon } from "lucide-react";
import { ConfirmCompletionButton } from "@/components/my-targets/ConfirmCompletionButton";
import { LoadingState, EmptyState, ErrorState } from "@/components/ui/DataStates";
import type { VisitRow } from "@/app/api/visits/route";

// Visits are scoped activities of a visit kind (school_visit, follow_up_visit,
// coaching_visit, core_visit), fetched live from the backend via /api/visits.
// A visit is confirmed by entering its Salesforce Visit ID (SVE-) — that's all
// a visit needs (no trainee counts).
type LoadState =
  | { phase: "loading" }
  | { phase: "ready"; visits: VisitRow[] }
  | { phase: "error"; error: string | null; at: number };

export default function VisitsIndex() {
  const [state, setState] = useState<LoadState>({ phase: "loading" });

  const load = useCallback(async () => {
    setState({ phase: "loading" });
    try {
      const res = await fetch("/api/visits", { cache: "no-store" });
      const data = (await res.json()) as { live: boolean; visits?: VisitRow[]; error?: string | null };
      if (!res.ok || !data.live) {
        setState({ phase: "error", error: data.error ?? null, at: Date.now() });
        return;
      }
      setState({ phase: "ready", visits: data.visits ?? [] });
    } catch (e) {
      setState({ phase: "error", error: e instanceof Error ? e.message : "Network error", at: Date.now() });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const rowIcon = (status: string): { Icon: LucideIcon; bg: string; text: string } =>
    status === "Verified" ? { Icon: CheckCircle2, bg: "bg-emerald-100", text: "text-emerald-700" }
    : status === "Awaiting SF ID" ? { Icon: AlertOctagon, bg: "bg-rose-100", text: "text-rose-700" }
    : { Icon: Footprints, bg: "bg-sky-100", text: "text-sky-700" };

  const tone = (status: string): ChipTone =>
    status === "Verified" ? "green"
    : status === "Awaiting SF ID" ? "red"
    : status === "In Progress" ? "blue" : "amber";

  const visits = state.phase === "ready" ? state.visits : [];

  return (
    <EntityIndex
      title="Visits"
      subtitle="Every school visit on your plan. Confirm a visit by entering its Salesforce Visit ID (SVE-)."
      Icon={Footprints}
      count={state.phase === "ready" ? visits.length : undefined}
      searchPlaceholder="Search by school, cluster"
    >
      <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
        {state.phase === "loading" && <LoadingState message="Loading visits…" />}
        {state.phase === "error" && (
          <ErrorState message="Could not load visits." onRetry={load} at={state.at} />
        )}
        {state.phase === "ready" && visits.length === 0 && (
          <EmptyState title="No visits yet" message="Plan a school visit and it will appear here." icon={Footprints} />
        )}
        {state.phase === "ready" && visits.map((v) => {
          const ic = rowIcon(v.status);
          return (
            <div key={v.id} className="flex items-center gap-3 px-4 py-3.5">
              <span className={`h-9 w-9 rounded-md grid place-items-center shrink-0 ${ic.bg} ${ic.text}`}>
                <ic.Icon size={15} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-body font-extrabold tracking-tight truncate">{v.type} — {v.context}</div>
                <div className="text-caption muted truncate">{v.date}</div>
              </div>
              <StatusBadge tone={tone(v.status)}>{v.status}</StatusBadge>
              {v.status !== "Verified" && (
                <ConfirmCompletionButton
                  activity={{ id: v.id, schoolName: v.context, activityType: v.type, purpose: v.date }}
                />
              )}
              <Link href={`/plans/${v.id}`} className="btn btn-sm" aria-label={`View ${v.type}`}>
                View
              </Link>
            </div>
          );
        })}
      </section>
    </EntityIndex>
  );
}
