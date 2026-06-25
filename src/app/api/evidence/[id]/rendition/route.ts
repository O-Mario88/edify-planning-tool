import { NextRequest, NextResponse } from "next/server";
import { getCurrentUserOrNull } from "@/lib/auth";
import { backendApiBase, backendTokenFor, isBackendEnabled } from "@/lib/api/backend";

// Stream the cached PDF rendition for a DOCX evidence file. The FE viewer
// iframe points here once `/prepare-view` reports `previewStatus: ready`
// with `viewKind: pdf_rendition`.
export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!isBackendEnabled()) return NextResponse.json({ error: "Backend disabled" }, { status: 503 });
  const user = await getCurrentUserOrNull();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const token = await backendTokenFor(user);
  if (!token) return NextResponse.json({ error: "Backend auth unavailable" }, { status: 502 });

  const upstream = await fetch(`${backendApiBase()}/evidence/${encodeURIComponent(id)}/rendition`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!upstream.ok || !upstream.body) {
    return NextResponse.json({ error: `Rendition unavailable (${upstream.status})` }, { status: upstream.status || 502 });
  }
  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/pdf",
      "Content-Disposition": upstream.headers.get("content-disposition") ?? "inline",
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "default-src 'none'; img-src 'self' data:; object-src 'none'; sandbox",
      "X-Frame-Options": "SAMEORIGIN",
      "Referrer-Policy": "no-referrer",
    },
  });
}
