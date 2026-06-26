import { describe, it, expect } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DocxConverterService } from './docx-converter.service';

// The DOCX→PDF converter relies on LibreOffice headless (`soffice`) being
// installed on the server. CI / local-dev environments without LibreOffice
// MUST get a clean, deterministic failure (so the UI shows the "couldn't
// prepare PDF preview — download original" fallback instead of hanging).
//
// These tests verify the contract — they do NOT exercise a real conversion
// (which would require pinning LibreOffice in CI). The graceful-degradation
// contract is the load-bearing piece for production correctness.

describe('DocxConverterService — graceful degradation', () => {
  it('isAvailable() resolves to a boolean (true if soffice on PATH, false otherwise)', async () => {
    const svc = new DocxConverterService();
    const ok = await svc.isAvailable();
    expect(typeof ok).toBe('boolean');
  });

  it('returns invalid_input when the source file does not exist', async () => {
    const svc = new DocxConverterService();
    const outDir = mkdtempSync(join(tmpdir(), 'docx-out-'));
    try {
      const r = await svc.convert(join(outDir, 'missing.docx'), outDir, 'out.pdf');
      expect(r.ok).toBe(false);
      if (!r.ok) expect(r.reason).toBe('invalid_input');
    } finally {
      rmSync(outDir, { recursive: true, force: true });
    }
  });

  it('returns converter_unavailable | conversion_failed for a placeholder DOCX when soffice is absent', async () => {
    const svc = new DocxConverterService();
    const dir = mkdtempSync(join(tmpdir(), 'docx-in-'));
    try {
      const src = join(dir, 'sample.docx');
      writeFileSync(src, Buffer.from([0x50, 0x4b, 0x03, 0x04])); // ZIP magic — recognized as docx by file-validation
      const r = await svc.convert(src, dir, 'sample.pdf', { timeoutMs: 4000 });
      // The result MUST be a structured failure (never an exception). The
      // viewer relies on this to show the download-original fallback.
      expect(r.ok).toBe(false);
      if (!r.ok) {
        expect(['converter_unavailable', 'conversion_failed', 'timeout']).toContain(r.reason);
      }
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
