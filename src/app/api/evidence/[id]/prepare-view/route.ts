import { NextRequest, NextResponse } from "next/server";
import { getCurrentUserOrNull } from "@/lib/auth";
import { backendFetch, isBackendEnabled } from "@/lib/api/backend";
import { enforceCsrf } from "@/lib/csrf";

// Prepare an evidence record for inline viewing. For DOCX uploads, the
// backend invokes the LibreOffice headless converter on-demand here (and
// caches the rendition); for PDF / image rows this just returns
// `previewStatus: ready`. The FE viewer then decides whether to render
// the original file, the cached PDF rendition, or a "couldn't prepare"
// fallback with a download link.
export const dynamic = "force-dynamic";

type PrepareResponse = {
  id: string;
  previewStatus: "ready" | "pending" | "failed";
  viewKind: "pdf" | "image" | "pdf_rendition" | "docx";
  renditionId: string | null;
  reason?: string;
  message?: string;
};

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const { id } = await ctx.params;
  if (!isBackendEnabled()) return NextResponse.json({ error: "Backend disabled" }, { status: 503 });
  const user = await getCurrentUserOrNull();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const r = await backendFetch<PrepareResponse>(
    `/evidence/${encodeURIComponent(id)}/prepare-view`, user,
    { method: "POST" },
  );
  return r.ok
    ? NextResponse.json({ live: true, data: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
