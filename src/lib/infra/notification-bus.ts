// In-process notification bus for the SSE stream.
//
// emitNotification calls publish(userId, payload); the SSE handler in
// `/api/notifications/stream/route.ts` subscribes per-user and writes
// events to the response.
//
// Single-process only. For multi-replica deploys, swap the registry
// for Redis pubsub: replace `subscribers` with a `SUBSCRIBE` call and
// `publish` with `PUBLISH`. The publish/subscribe shape is the same.

import "server-only";

export type StreamEvent = {
  /** Stable id — used for SSE event ids + client de-dup. */
  id: string;
  /** `notification` for new inbox rows; `audit` for live audit ticks. */
  type: "notification" | "audit" | "ping";
  /** Payload — shape varies by type. */
  data: Record<string, unknown>;
};

type Subscriber = (event: StreamEvent) => void;

const BUS_KEY = "__edify_notification_bus__";
type Bus = { subs: Map<string, Set<Subscriber>> };
type GlobalWithBus = typeof globalThis & { [BUS_KEY]?: Bus };

function getBus(): Bus {
  const g = globalThis as GlobalWithBus;
  if (!g[BUS_KEY]) g[BUS_KEY] = { subs: new Map() };
  return g[BUS_KEY]!;
}

export function subscribe(userId: string, sub: Subscriber): () => void {
  const bus = getBus();
  if (!bus.subs.has(userId)) bus.subs.set(userId, new Set());
  bus.subs.get(userId)!.add(sub);
  return () => {
    const set = bus.subs.get(userId);
    if (!set) return;
    set.delete(sub);
    if (set.size === 0) bus.subs.delete(userId);
  };
}

export function publish(userId: string, event: StreamEvent): void {
  const set = getBus().subs.get(userId);
  if (!set) return;
  for (const sub of set) {
    try { sub(event); } catch { /* ignore */ }
  }
}

/** Broadcast to every connected subscriber. Used for audit ticks
 *  (admin live view) and pings. */
export function broadcast(event: StreamEvent): void {
  const bus = getBus();
  for (const set of bus.subs.values()) {
    for (const sub of set) {
      try { sub(event); } catch { /* ignore */ }
    }
  }
}

/** How many distinct users are currently connected. Used by an
 *  /admin/health surface. */
export function connectedUsers(): number {
  return getBus().subs.size;
}
