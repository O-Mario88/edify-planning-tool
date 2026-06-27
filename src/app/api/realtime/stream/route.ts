import { getCurrentUserOrNull } from "@/lib/auth";
import { backendApiBase, backendTokenFor, isBackendEnabled } from "@/lib/api/backend";

// SSE proxy: the browser's EventSource can't attach an Authorization header, so
// it connects here; this server route resolves the user's backend token and
// pipes the backend's /realtime/stream straight through. Scope is enforced
// upstream (the backend only streams this user's events).
export const dynamic = "force-dynamic";
export const fetchCache = "force-no-store";

const SSE_HEADERS = {
  "Content-Type": "text/event-stream",
  "Cache-Control": "no-cache, no-transform",
  Connection: "keep-alive",
  "X-Accel-Buffering": "no",
};

export async function GET(req: Request) {
  // Local Django/Daphne runserver can be starved by long-lived SSE sockets.
  // Keep live data reads enabled, but only open realtime when explicitly asked.
  if (process.env.EDIFY_ENABLE_REALTIME !== "true") {
    return new Response(`data: {"type":"off"}\n\n`, { headers: SSE_HEADERS });
  }

  const user = await getCurrentUserOrNull();
  if (!user || !isBackendEnabled()) {
    // One "off" frame so the client stops trying when there's no live backend.
    return new Response(`data: {"type":"off"}\n\n`, { headers: SSE_HEADERS });
  }
  const token = await backendTokenFor(user);
  if (!token) return new Response(`data: {"type":"off"}\n\n`, { headers: SSE_HEADERS });

  const upstream = await fetch(`${backendApiBase()}/realtime/stream`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
    signal: req.signal,
    cache: "no-store",
  }).catch(() => null);

  if (!upstream || !upstream.ok || !upstream.body) {
    return new Response(`data: {"type":"off"}\n\n`, { headers: SSE_HEADERS });
  }
  return new Response(upstream.body, { headers: SSE_HEADERS });
}
