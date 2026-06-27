import { NextRequest, NextResponse } from "next/server";
import { revalidatePath } from "next/cache";
import { getCurrentUserOrNull } from "@/lib/auth";
import { backendApiBase, backendTokenFor, isBackendEnabled } from "@/lib/api/backend";
import { enforceCsrf } from "@/lib/csrf";

// Proxy a raw SSA spreadsheet (CSV / XLSX) to the backend (POST /ssa/upload).
// Django parses + validates each row (existing school + 8 numeric scores) and
// saves valid rows through the existing SSA service (FY/quarter derivation,
// school SSA-status + planning-readiness recompute), returning the truthful
// breakdown. A successful save revalidates the directory + planning surfaces.
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  if (!isBackendEnabled()) {
    return NextResponse.json({ error: "Backend disabled" }, { status: 503 });
  }
  const user = await getCurrentUserOrNull();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const token = await backendTokenFor(user);
  if (!token) return NextResponse.json({ error: "Backend auth unavailable" }, { status: 502 });

  const form = await req.formData();
  const file = form.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json({ error: "A file is required" }, { status: 400 });
  }

  const forward = new FormData();
  forward.append("file", file, file.name);

  try {
    const res = await fetch(`${backendApiBase()}/ssa/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: forward,
      cache: "no-store",
    });
    const text = await res.text();
    let body: unknown = null;
    try { body = JSON.parse(text); } catch { /* non-json */ }

    if (res.status === 400) {
      const message = (body as { message?: string })?.message ?? `Upload failed (${res.status})`;
      return NextResponse.json({ error: message }, { status: 400 });
    }

    const result = body as { success?: boolean } | null;
    if (result && (result.success || res.status === 422)) {
      if (result.success) {
        for (const p of ["/schools", "/data-intake", "/planning", "/dashboards/impact", "/analytics"]) {
          try { revalidatePath(p); } catch { /* outside request scope */ }
        }
      }
      return NextResponse.json(result, { status: 200 });
    }

    return NextResponse.json(
      { error: (body as { message?: string })?.message ?? `Upload failed (${res.status})` },
      { status: res.status },
    );
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : "Upload error" }, { status: 502 });
  }
}
