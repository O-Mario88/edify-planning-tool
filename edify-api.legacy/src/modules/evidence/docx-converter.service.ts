import { Injectable, Logger } from '@nestjs/common';
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, renameSync, rmSync } from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';

// ───────────────────── DOCX → PDF conversion service ─────────────────────
//
// One job: take a DOCX (or DOC) file on disk and produce a PDF rendition
// next to it that the evidence viewer can render inline. The user-facing
// rule (spec §22–25):
//
//   • PDF / image evidence  → previewStatus = "ready" at upload time
//   • DOCX evidence          → previewStatus = "pending" at upload time,
//     transitions to "ready" once this service produces a PDF rendition,
//     or "failed" if the converter isn't available / chokes on the file.
//
// We use the conversion tool that ships pre-installed on most server
// images: **LibreOffice headless** (`soffice --headless --convert-to pdf`).
// On environments where it's not installed (CI without libreoffice,
// developer machines without `brew install libreoffice`), the service
// resolves to `{ ok: false, reason: "converter_unavailable" }` and the
// caller stores `previewStatus = "failed"`. The viewer then falls back to
// "Could not prepare PDF preview — download original" so the workflow is
// never silently broken.
//
// Conversion is **invoked on-demand** by the evidence View Evidence
// handler (lazy + cached). The first viewer pays the latency; every
// subsequent viewer reads the cached PDF rendition from disk.

export type DocxConversionResult =
  | { ok: true; pdfFilename: string; pdfAbsPath: string; durationMs: number }
  | { ok: false; reason: 'converter_unavailable' | 'conversion_failed' | 'timeout' | 'invalid_input'; message: string };

const DEFAULT_TIMEOUT_MS = 30_000;
// Soffice binary candidates — first one that exists on PATH is used.
// `soffice` is the cross-platform CLI shim that LibreOffice installs; on
// macOS `libreoffice` is sometimes used.
const SOFFICE_CANDIDATES = ['soffice', 'libreoffice'];

@Injectable()
export class DocxConverterService {
  private readonly log = new Logger('DocxConverter');
  /** Cache the resolved binary path so we don't `which` on every conversion. */
  private resolvedBinary: string | null | undefined;

  /** Find the soffice binary on PATH. Returns null if not installed. */
  private async findSoffice(): Promise<string | null> {
    if (this.resolvedBinary !== undefined) return this.resolvedBinary;
    for (const candidate of SOFFICE_CANDIDATES) {
      try {
        const ok = await new Promise<boolean>((resolveOk) => {
          const proc = spawn(candidate, ['--version'], { stdio: 'ignore' });
          proc.on('error', () => resolveOk(false));
          proc.on('exit', (code) => resolveOk(code === 0));
        });
        if (ok) {
          this.resolvedBinary = candidate;
          return candidate;
        }
      } catch {
        // continue
      }
    }
    this.resolvedBinary = null;
    return null;
  }

  /** Public health probe — call this once at boot or on demand to know
   *  whether the converter is wired. The System Health page reads it. */
  async isAvailable(): Promise<boolean> {
    const bin = await this.findSoffice();
    return bin != null;
  }

  /** Convert a DOC/DOCX file at `absPath` to a PDF written into `outDir`.
   *  Returns the PDF filename + absolute path on success. */
  async convert(
    absPath: string,
    outDir: string,
    targetName: string,
    opts: { timeoutMs?: number } = {},
  ): Promise<DocxConversionResult> {
    if (!existsSync(absPath)) {
      return { ok: false, reason: 'invalid_input', message: `Source file missing: ${absPath}` };
    }
    const bin = await this.findSoffice();
    if (!bin) {
      this.log.warn(
        `DOCX→PDF conversion unavailable — install LibreOffice (\`brew install libreoffice\` / \`apt-get install libreoffice\`) ` +
          `to enable inline DOCX preview.`,
      );
      return { ok: false, reason: 'converter_unavailable', message: 'LibreOffice is not installed on this server.' };
    }

    // LibreOffice writes to --outdir using the source basename + ".pdf".
    // We spawn into a temp directory we own, then rename the output to the
    // caller's chosen filename to keep the EVIDENCE_DIR layout predictable.
    const work = resolve(tmpdir(), `edify-docx-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`);
    mkdirSync(work, { recursive: true });

    const started = Date.now();
    try {
      const args = ['--headless', '--convert-to', 'pdf', '--outdir', work, absPath];
      const exitCode = await new Promise<number>((resolveCode) => {
        const proc = spawn(bin, args, { stdio: 'pipe' });
        let timer: NodeJS.Timeout | null = setTimeout(() => {
          try {
            proc.kill('SIGKILL');
          } catch {
            /* ignore */
          }
          timer = null;
          resolveCode(124); // timeout exit code (like coreutils)
        }, opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);
        proc.on('error', () => {
          if (timer) clearTimeout(timer);
          resolveCode(127);
        });
        proc.on('exit', (code) => {
          if (timer) clearTimeout(timer);
          resolveCode(code ?? 1);
        });
      });

      if (exitCode === 124) {
        return { ok: false, reason: 'timeout', message: `Conversion exceeded ${opts.timeoutMs ?? DEFAULT_TIMEOUT_MS}ms.` };
      }
      if (exitCode !== 0) {
        return { ok: false, reason: 'conversion_failed', message: `soffice exited with ${exitCode}` };
      }

      // Find the produced file — LibreOffice replaces the extension with .pdf.
      const baseNoExt = basename(absPath).replace(/\.[^.]+$/, '');
      const producedPath = join(work, `${baseNoExt}.pdf`);
      if (!existsSync(producedPath)) {
        return { ok: false, reason: 'conversion_failed', message: 'PDF rendition was not produced.' };
      }

      // Move into the persistent evidence directory under the caller's name.
      mkdirSync(outDir, { recursive: true });
      const targetAbs = join(outDir, targetName);
      renameSync(producedPath, targetAbs);

      return {
        ok: true,
        pdfFilename: targetName,
        pdfAbsPath: targetAbs,
        durationMs: Date.now() - started,
      };
    } finally {
      rmSync(work, { recursive: true, force: true });
    }
  }
}
