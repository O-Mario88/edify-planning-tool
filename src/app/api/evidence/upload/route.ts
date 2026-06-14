import { NextRequest, NextResponse } from "next/server";
import { getCurrentUserOrNull } from "@/lib/auth";
import { backendApiBase, backendTokenFor, isBackendEnabled } from "@/lib/api/backend";
import { enforceCsrf } from "@/lib/csrf";

// Proxy a real multipart evidence upload to the backend (POST /evidence/upload).
// The browser sends the File here; we attach the scoped bearer server-side and
// forward it as multipart/form-data. The file lands on the backend's disk and a
// real EvidenceRecord row is created.
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

  // Re-pack into a fresh FormData to forward (keeps field names file/activityId/kind).
  const forward = new FormData();
  forward.append("file", file, file.name);
  forward.append("activityId", String(form.get("activityId") ?? ""));
  forward.append("kind", String(form.get("kind") ?? ""));

  try {
    const res = await fetch(`${backendApiBase()}/evidence/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` }, // no Content-Type — fetch sets the boundary
      body: forward,
      cache: "no-store",
    });
    const text = await res.text();
    if (!res.ok) {
      let msg = `Upload failed (${res.status})`;
      try { msg = JSON.parse(text)?.message ?? msg; } catch { /* keep default */ }
      return NextResponse.json({ error: msg }, { status: res.status });
    }
    return NextResponse.json({ live: true, evidence: JSON.parse(text) });
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : "Upload error" }, { status: 502 });
  }
}
