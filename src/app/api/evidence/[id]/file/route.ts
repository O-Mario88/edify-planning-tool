import { NextRequest, NextResponse } from "next/server";
import { getCurrentUserOrNull } from "@/lib/auth";
import { backendApiBase, backendTokenFor, isBackendEnabled } from "@/lib/api/backend";

// Stream an evidence file's bytes back to the browser for preview/download.
// Proxies GET /evidence/:id/file with the scoped bearer and forwards the
// backend's Content-Type + Content-Disposition (so PDFs/images preview inline
// and Word/Excel download with the right filename). ?download=1 forces a
// download disposition.
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!isBackendEnabled()) return NextResponse.json({ error: "Backend disabled" }, { status: 503 });
  const user = await getCurrentUserOrNull();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const token = await backendTokenFor(user);
  if (!token) return NextResponse.json({ error: "Backend auth unavailable" }, { status: 502 });

  const upstream = await fetch(`${backendApiBase()}/evidence/${encodeURIComponent(id)}/file`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!upstream.ok || !upstream.body) {
    return NextResponse.json({ error: `Evidence unavailable (${upstream.status})` }, { status: upstream.status || 502 });
  }

  const contentType = upstream.headers.get("content-type") ?? "application/octet-stream";
  let disposition = upstream.headers.get("content-disposition") ?? "inline";
  if (req.nextUrl.searchParams.get("download") === "1") {
    disposition = disposition.replace(/^inline/, "attachment");
    if (!/attachment/.test(disposition)) disposition = `attachment; ${disposition}`;
  }
  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": contentType,
      "Content-Disposition": disposition,
      "Cache-Control": "private, no-store",
      // Defang the evidence stream: no MIME sniffing, no active content, no
      // framing by other origins. Mirrors the backend's file headers so the
      // protection holds whether served direct or through this proxy.
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "default-src 'none'; img-src 'self' data:; object-src 'none'; sandbox",
      "X-Frame-Options": "SAMEORIGIN",
      "Referrer-Policy": "no-referrer",
    },
  });
}
