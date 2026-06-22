"use client";

import { useEffect, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CheckCircle2, RotateCcw, Paperclip, AlertTriangle } from "lucide-react";
import { csrfHeaders } from "@/lib/csrf-client";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import type { BePlReviewItem } from "@/lib/api/surfaces";

export function PlReviewQueue() {
  const router = useRouter();
  const [items, setItems] = useState<BePlReviewItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    fetch("/api/pl/review-queue", { credentials: "include", cache: "no-store" })
      .then((r) => r.json())
      .then((j) => {
        if (j.live) setItems(j.items ?? []);
        else setError(j.error || "Could not load review queue");
      })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  function act(id: string, action: "confirm" | "return") {
    let reason: string | undefined;
    if (action === "return") {
      reason = window.prompt("Reason for returning this completion:") ?? undefined;
      if (!reason?.trim()) return;
    }
    setMsg(null);
    start(async () => {
      try {
        const res = await fetch(`/api/pl/review-queue/${encodeURIComponent(id)}/${action}`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", ...csrfHeaders() },
          body: JSON.stringify(action === "return" ? { reason } : {}),
        });
        const j = await res.json();
        if (!res.ok || !j.live) {
          setMsg(j.error || "Action failed");
          return;
        }
        setMsg(action === "confirm" ? "Confirmed — sent to IA." : "Returned to CCEO for correction.");
        load();
        router.refresh();
      } catch {
        setMsg("Could not reach the server");
      }
    });
  }

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!items?.length) {
    return (
      <EmptyState
        title="No completions awaiting your review"
        message="When a CCEO submits field completion with evidence and an Activity Code, it appears here for your confirmation before IA verification."
      />
    );
  }

  return (
    <div className="space-y-3">
      {msg && (
        <p className="text-[12px] font-semibold text-[var(--color-edify-primary)]">{msg}</p>
      )}
      <ul className="space-y-2">
        {items.map((it) => (
          <li key={it.id} className="card p-3.5 flex flex-col sm:flex-row sm:items-center gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-[13px] font-extrabold tracking-tight">
                {(it.school?.name ?? it.cluster?.name ?? "Activity")} · {it.activityType.replace(/_/g, " ")}
              </div>
              <div className="text-[11px] muted mt-0.5">
                {it.responsibleStaff?.user?.name ?? "CCEO"} · Code: {it.salesforceActivityId ?? "—"} · Evidence: {it.evidence.length} file(s)
              </div>
              {it.evidence.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {it.evidence.map((e) => (
                    <Link
                      key={e.id}
                      href={`/activities/${it.id}/evidence`}
                      className="inline-flex items-center gap-1 rounded-md border border-[var(--color-edify-border)] px-2 py-0.5 text-[10.5px] font-bold muted hover:bg-[var(--color-edify-soft)]/40"
                    >
                      <Paperclip size={10} /> {e.originalName ?? e.kind}
                    </Link>
                  ))}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                disabled={pending}
                onClick={() => act(it.id, "confirm")}
                className="inline-flex items-center gap-1 rounded-lg bg-[var(--color-edify-primary)] text-white px-3 py-1.5 text-[11px] font-extrabold disabled:opacity-40"
              >
                <CheckCircle2 size={12} /> Confirm
              </button>
              <button
                type="button"
                disabled={pending}
                onClick={() => act(it.id, "return")}
                className="inline-flex items-center gap-1 rounded-lg border border-amber-200 text-amber-800 px-3 py-1.5 text-[11px] font-extrabold disabled:opacity-40"
              >
                <RotateCcw size={12} /> Return
              </button>
            </div>
          </li>
        ))}
      </ul>
      <p className="text-[10.5px] muted inline-flex items-center gap-1">
        <AlertTriangle size={11} /> Confirm only after evidence and Activity Code are correct — IA receives it next.
      </p>
    </div>
  );
}
