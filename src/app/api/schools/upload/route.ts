import { NextRequest, NextResponse } from "next/server";
import { revalidatePath } from "next/cache";
import { getCurrentUserOrNull } from "@/lib/auth";
import { backendApiBase, backendTokenFor, isBackendEnabled } from "@/lib/api/backend";
import { enforceCsrf } from "@/lib/csrf";

// Proxy a raw school-onboarding spreadsheet (CSV / XLSX) to the backend
// (POST /schools/upload). The browser sends the File here; we attach the scoped
// bearer server-side and forward it as multipart/form-data. Django parses,
// validates, and SAVES the rows in Postgres, then returns the truthful
// created/updated/failed/duplicate/skipped breakdown.
//
// On a successful save we revalidate every surface that reads the directory so
// the School Directory shows the uploaded rows immediately (the directory was
// previously never revalidated after an upload).
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
  const updateExisting = form.get("update_existing");
  if (updateExisting != null) forward.append("update_existing", String(updateExisting));

  try {
    const res = await fetch(`${backendApiBase()}/schools/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` }, // no Content-Type — fetch sets the boundary
      body: forward,
      cache: "no-store",
    });
    const text = await res.text();
    let body: unknown = null;
    try { body = JSON.parse(text); } catch { /* non-json */ }

    // 400 = header/file-level error (nothing saved). 422 = parsed but zero saved.
    if (res.status === 400) {
      const message = (body as { message?: string })?.message ?? `Upload failed (${res.status})`;
      return NextResponse.json({ error: message }, { status: 400 });
    }

    // Both 200 (success) and 422 (nothing saved) carry the truthful contract body.
    const result = body as { success?: boolean } | null;
    if (result && (result.success || res.status === 422)) {
      if (result.success) {
        for (const p of ["/schools", "/data-intake", "/data-intake/upload", "/dashboards/impact", "/analytics"]) {
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
