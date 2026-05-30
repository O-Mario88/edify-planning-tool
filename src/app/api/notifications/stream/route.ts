// Server-Sent Events endpoint for live notifications + audit ticks.
//
// Client connects via EventSource("/api/notifications/stream"); server
// keeps the response open and streams events as JSON-encoded SSE
// messages. The header bell hook subscribes here and updates the
// unread badge live without polling.
//
// The endpoint runs on the Node runtime (not Edge) because we need
// long-lived TCP. On Vercel: set `runtime = "nodejs"` and accept the
// connection-limit caveat (max ~5 mins on hobby tier). For real Edge
// support, swap to Edge runtime + Upstash pubsub.
//
// Auth: gated by getCurrentUserOrNull so anonymous browsers get 401
// without consuming a slot.

import { getCurrentUserOrNull } from "@/lib/auth";
import { subscribe, type StreamEvent } from "@/lib/infra/notification-bus";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Heartbeat keeps middleware proxies (CloudFront, Vercel) from
 *  killing the connection as idle. 25s is comfortably under the 30s
 *  Vercel idle timeout. */
const HEARTBEAT_MS = 25_000;

export async function GET(req: Request): Promise<Response> {
  const user = await getCurrentUserOrNull();
  if (!user) {
    return new Response("Unauthorized", { status: 401 });
  }

  const encoder = new TextEncoder();
  const abort = req.signal;

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      let closed = false;
      function safeEnqueue(chunk: string) {
        if (closed) return;
        try { controller.enqueue(encoder.encode(chunk)); }
        catch { closed = true; }
      }

      function writeEvent(event: StreamEvent) {
        safeEnqueue(
          `id: ${event.id}\n` +
          `event: ${event.type}\n` +
          `data: ${JSON.stringify(event.data)}\n\n`,
        );
      }

      // SSE protocol prelude — flush a comment so the client knows
      // the stream is alive even before the first real event.
      safeEnqueue(": connected\n\n");

      // Subscribe to this user's channel.
      const unsub = subscribe(user.staffId, (event) => {
        writeEvent(event);
      });

      // Periodic heartbeat keeps the connection from dying idle.
      const heartbeat = setInterval(() => {
        if (closed) return;
        writeEvent({
          id: `ping-${Date.now()}`,
          type: "ping",
          data: { now: Date.now() },
        });
      }, HEARTBEAT_MS);

      function shutdown() {
        if (closed) return;
        closed = true;
        clearInterval(heartbeat);
        unsub();
        try { controller.close(); } catch { /* already closed */ }
      }

      // Client disconnect signal.
      abort.addEventListener("abort", shutdown);

      // Stash close hook on the controller for tests.
      (controller as unknown as { __edifyClose?: () => void }).__edifyClose = shutdown;
    },
  });

  return new Response(stream, {
    headers: {
      "content-type":  "text/event-stream",
      "cache-control": "no-cache, no-transform",
      // CORS: same-origin only by default. If the header-bell is on
      // a different subdomain in production, add the allow-origin
      // dance via middleware.
      "x-accel-buffering": "no",   // nginx hint
    },
  });
}
