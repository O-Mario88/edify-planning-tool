"use client";

// Live notification stream subscription.
//
// Wraps `EventSource` against `/api/notifications/stream` and exposes
// an unread-count state + the latest event. Used by the header bell
// to update in real time, and by /notifications to show a "+ new"
// banner that re-fetches when clicked.
//
// Reconnect strategy: EventSource auto-reconnects on socket-level
// disconnects with exponential backoff baked into the browser. On
// session expiry (server returns 401) we stop trying — that's a
// permanent failure that needs a re-login.

import { useEffect, useRef, useState } from "react";

export type StreamEvent = {
  id: string;
  type: "notification" | "audit" | "ping";
  data: Record<string, unknown>;
};

export type StreamState = {
  /** Number of "notification" events received since mount. */
  liveCount:    number;
  /** Last non-ping event, for surfacing toasts. */
  lastEvent:    StreamEvent | null;
  /** Connection status. */
  status:       "connecting" | "open" | "closed" | "denied";
};

export function useNotificationStream(): StreamState {
  const [state, setState] = useState<StreamState>({
    liveCount: 0,
    lastEvent: null,
    status: "connecting",
  });
  const evtSrcRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (typeof EventSource === "undefined") {
      // Very old browsers or environments without SSE support — give
      // up silently rather than crashing the page.
      setState((s) => ({ ...s, status: "denied" }));
      return;
    }
    const src = new EventSource("/api/notifications/stream");
    evtSrcRef.current = src;

    src.onopen = () => setState((s) => ({ ...s, status: "open" }));

    const onMessage = (kind: StreamEvent["type"]) => (msg: MessageEvent) => {
      let data: Record<string, unknown> = {};
      try { data = JSON.parse(msg.data); } catch { /* ignore parse */ }
      const evt: StreamEvent = { id: msg.lastEventId || `e-${Date.now()}`, type: kind, data };
      setState((s) => ({
        ...s,
        lastEvent: evt,
        liveCount: kind === "notification" ? s.liveCount + 1 : s.liveCount,
      }));
    };
    src.addEventListener("notification", onMessage("notification") as EventListener);
    src.addEventListener("audit",         onMessage("audit")         as EventListener);
    src.addEventListener("ping",          onMessage("ping")          as EventListener);

    src.onerror = () => {
      // Browser will auto-reconnect; mark the badge as "stale" so the
      // user knows they're seeing cached counts.
      setState((s) => ({ ...s, status: s.status === "open" ? "connecting" : s.status }));
    };

    return () => {
      src.close();
      evtSrcRef.current = null;
      setState((s) => ({ ...s, status: "closed" }));
    };
  }, []);

  return state;
}
