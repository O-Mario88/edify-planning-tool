"use client";

// CommandCenterAlerts — the persistent operational-risk rail (spec §13/§18).
//
// Unlike notifications (one-shot workflow events) these alerts are generated
// live from data conditions on the backend. A user can dismiss one temporarily;
// it REAPPEARS when the window lapses if the underlying issue is still open, and
// disappears for good only when the issue is resolved. This panel surfaces them,
// lets the user act (deep link) or snooze (dismiss), and refetches on refresh.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, BellOff, ChevronRight, Loader2, ShieldCheck } from "lucide-react";
import { EmptyState, ErrorState } from "@/components/ui/DataStates";
import { csrfHeaders } from "@/lib/csrf-client";

type Alert = {
  id: string;
  alertType: string;
  severity: "low" | "normal" | "high" | "urgent";
  scope: string | null;
  title: string;
  body: string | null;
  targetRoute: string | null;
};

const SEVERITY_STYLE: Record<Alert["severity"], { dot: string; label: string }> = {
  urgent: { dot: "bg-rose-500", label: "Critical" },
  high: { dot: "bg-amber-500", label: "High" },
  normal: { dot: "bg-sky-500", label: "Medium" },
  low: { dot: "bg-slate-400", label: "Low" },
};

export function CommandCenterAlerts() {
  const router = useRouter();
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [dismissing, setDismissing] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch("/api/command-center/alerts", { credentials: "include" })
        .then((r) => r.json())
        .then((j) => {
          if (cancelled) return;
          if (j.live) { setAlerts(j.alerts as Alert[]); setErr(null); }
          else { setAlerts([]); setErr(j.error || "Could not load alerts"); }
        })
        .catch(() => { if (!cancelled) { setAlerts([]); setErr("Could not reach the server"); } });
    };
    load();
    // Refetch when the realtime layer signals a workflow change.
    const onRealtime = () => load();
    window.addEventListener("edify:realtime", onRealtime);
    return () => { cancelled = true; window.removeEventListener("edify:realtime", onRealtime); };
  }, []);

  const dismiss = async (id: string) => {
    setDismissing(id);
    setAlerts((prev) => (prev ? prev.filter((a) => a.id !== id) : prev));
    try {
      await fetch(`/api/command-center/alerts/${encodeURIComponent(id)}/dismiss`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({ hours: 24 }),
      });
    } catch { /* optimistic — it reappears on next load if still unresolved */ }
    setDismissing(null);
  };

  const open = (a: Alert) => { if (a.targetRoute) router.push(a.targetRoute); };

  if (err && !alerts?.length) return <ErrorState message={err} />;
  if (alerts === null) return <div className="card p-6 inline-flex items-center gap-2 text-[13px] muted"><Loader2 size={15} className="animate-spin" /> Loading alerts…</div>;
  if (alerts.length === 0) {
    return <EmptyState icon={ShieldCheck} title="No open operational risks" message="Command-center alerts will appear here when a data condition needs attention." />;
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 px-0.5">
        <AlertTriangle size={15} className="text-amber-500" />
        <h3 className="text-[13px] font-bold">Operational risks</h3>
        <span className="text-[11px] font-bold muted">{alerts.length}</span>
      </div>
      {alerts.map((a) => {
        const sev = SEVERITY_STYLE[a.severity];
        return (
          <div key={a.id} className="card p-3 flex items-start gap-3">
            <span className={`mt-1.5 h-2 w-2 rounded-full shrink-0 ${sev.dot}`} aria-hidden />
            <button onClick={() => open(a)} className="flex-1 text-left group" disabled={!a.targetRoute}>
              <div className="flex items-center gap-2">
                <span className="text-[13px] font-bold">{a.title}</span>
                <span className="text-[9.5px] font-bold uppercase tracking-wide muted">{sev.label}</span>
                {a.targetRoute && <ChevronRight size={14} className="muted opacity-0 group-hover:opacity-100 transition-opacity" />}
              </div>
              {a.body && <p className="text-[12px] muted mt-0.5">{a.body}</p>}
            </button>
            <button
              onClick={() => dismiss(a.id)}
              disabled={dismissing === a.id}
              title="Dismiss for 24h (reappears if unresolved)"
              className="shrink-0 h-8 px-2 inline-flex items-center gap-1 rounded-lg border border-[var(--color-edify-border)] text-[11px] font-bold muted hover:bg-[var(--surface-3)] disabled:opacity-50"
            >
              {dismissing === a.id ? <Loader2 size={13} className="animate-spin" /> : <BellOff size={13} />}
              Snooze
            </button>
          </div>
        );
      })}
    </div>
  );
}
