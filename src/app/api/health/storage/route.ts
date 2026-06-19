import { NextResponse } from "next/server";
import { promises as fs } from "node:fs";
import path from "node:path";

// Evidence-storage probe. Confirms EVIDENCE_STORAGE_DIR exists, is absolute
// (relative = ephemeral → files lost on redeploy), and is writable. Catches the
// classic "uploads work until the next deploy" production trap.
export const dynamic = "force-dynamic";

export async function GET() {
  const dir = process.env.EVIDENCE_STORAGE_DIR ?? "";
  if (!dir) {
    return NextResponse.json({
      ok: false,
      configured: false,
      note: "EVIDENCE_STORAGE_DIR not set — uploads have no persistent target. Prod needs an absolute path on a mounted volume (or object storage).",
      time: new Date().toISOString(),
    });
  }

  const absolute = path.isAbsolute(dir);
  let writable = false;
  let detail: string | undefined;
  try {
    await fs.mkdir(dir, { recursive: true });
    const probe = path.join(dir, ".health-probe");
    await fs.writeFile(probe, String(Date.now()));
    await fs.unlink(probe);
    writable = true;
  } catch (e) {
    detail = e instanceof Error ? e.message : String(e);
  }

  return NextResponse.json({
    ok: writable && absolute,
    configured: true,
    path: dir,
    absolute,
    writable,
    detail,
    note: !absolute
      ? "Path is relative → likely the ephemeral container FS; files are lost on redeploy. Use an absolute path on a mounted volume."
      : !writable
        ? "Path not writable — uploads will fail."
        : undefined,
    time: new Date().toISOString(),
  });
}
