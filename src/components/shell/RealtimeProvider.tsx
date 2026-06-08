"use client";

// The live wire on the client. Opens one EventSource to the SSE proxy and, on
// each domain event, refreshes the current route's server components — so
// dashboards, queues, counters, and analytics update without a manual reload.
// Refreshes are debounced so a burst of events causes one calm refresh, never
// a flickering UI. It also re-broadcasts events on a window event so smaller
// widgets (notification bell, toasts) can react without their own connection.

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

export type RealtimeEvent = { type: string; subjectKind?: string; subjectId?: string; at?: number; meta?: Record<string, unknown> };

export function RealtimeProvider() {
  const router = useRouter();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let es: EventSource | null = null;
    let closed = false;

    const connect = () => {
      if (closed) return;
      es = new EventSource("/api/realtime/stream");
      es.onmessage = (ev) => {
        let data: RealtimeEvent;
        try { data = JSON.parse(ev.data); } catch { return; }
        // Lifecycle frames carry no state change.
        if (data.type === "heartbeat" || data.type === "connected" || data.type === "off") {
          window.dispatchEvent(new CustomEvent("edify:realtime-status", { detail: { connected: data.type !== "off" } }));
          return;
        }
        // Let widgets react immediately (badge bump, toast)…
        window.dispatchEvent(new CustomEvent("edify:realtime", { detail: data }));
        // …and refresh server components, debounced so bursts settle into one.
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => router.refresh(), 450);
      };
      es.onerror = () => {
        // EventSource auto-reconnects; close + retry with a small backoff to
        // avoid hammering when the backend is briefly down.
        es?.close();
        if (!closed) setTimeout(connect, 4000);
      };
    };
    connect();

    return () => {
      closed = true;
      if (timer.current) clearTimeout(timer.current);
      es?.close();
    };
  }, [router]);

  return null;
}
