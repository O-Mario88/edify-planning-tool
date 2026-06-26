import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { EvidenceService, type StoredFile } from './evidence.service';
import type { AuthUser } from '../../common/auth/auth-user';

// recordUpload reads the first bytes of the stored file off disk and magic-byte
// validates them, so the test writes a real (tiny) PDF to a temp dir.
const PDF_BYTES = Buffer.concat([
  Buffer.from('%PDF-1.4\n', 'utf8'),
  Buffer.from('1 0 obj<<>>endobj\n', 'utf8'),
  Buffer.from('%%EOF\n', 'utf8'),
]);

type ActivityRow = { id: string; deliveryType: string; status: string };

function makeService(activity: ActivityRow) {
  const updateCalls: Array<{ where: unknown; data: Record<string, unknown> }> = [];
  const prisma = {
    activity: {
      findFirst: async () => activity,
      update: async (args: { where: unknown; data: Record<string, unknown> }) => {
        updateCalls.push(args);
        return { ...activity, ...args.data };
      },
    },
    evidenceRecord: {
      create: async () => ({ id: 'ev1', originalName: 'proof.pdf', status: 'uploaded' }),
    },
  };
  const scope = {} as never;
  const audit = { log: async () => undefined } as never;
  const authz = { assertCanAccess: async () => undefined } as never;
  const events = {} as never;
  const scanner = { scan: async () => 'skipped' as const };
  const docxConverter = { convert: async () => ({ ok: false, reason: 'converter_unavailable', message: 'noop' } as const), isAvailable: async () => false } as never;
  const svc = new EvidenceService(prisma as never, scope, audit, authz, events, docxConverter, scanner as never);
  return { svc, updateCalls };
}

describe('EvidenceService.recordUpload — activity status advance', () => {
  let dir: string;
  const user: AuthUser = { userId: 'u-partner', name: 'Partner', activeRole: 'Partner' as never, email: 'p@x.io', roles: [] as never };

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'evidence-test-'));
  });
  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  function file(): StoredFile {
    const path = join(dir, 'proof.pdf');
    writeFileSync(path, PDF_BYTES);
    return { originalname: 'proof.pdf', mimetype: 'application/pdf', size: PDF_BYTES.length, filename: 'proof.pdf', path };
  }

  // The core regression: a partner upload must advance the workflow status to
  // evidence_uploaded from ANY pre-evidence status, so the review queue (which
  // keys off status === evidence_uploaded) sees it.
  for (const status of ['assigned_to_partner', 'partner_scheduled', 'scheduled', 'in_progress', 'completion_started']) {
    it(`advances a partner activity from ${status} to evidence_uploaded`, async () => {
      const { svc, updateCalls } = makeService({ id: 'a1', deliveryType: 'partner', status });
      await svc.recordUpload(user, 'a1', 'visit_form', file());
      expect(updateCalls).toHaveLength(1);
      expect(updateCalls[0]!.data.evidenceStatus).toBe('uploaded');
      expect(updateCalls[0]!.data.status).toBe('evidence_uploaded');
    });
  }

  it('does NOT change status for a staff-delivered activity (only flags evidence)', async () => {
    const { svc, updateCalls } = makeService({ id: 'a2', deliveryType: 'staff', status: 'in_progress' });
    await svc.recordUpload(user, 'a2', 'visit_form', file());
    expect(updateCalls[0]!.data.evidenceStatus).toBe('uploaded');
    expect(updateCalls[0]!.data.status).toBeUndefined();
  });

  it('does NOT regress a partner activity already past the evidence stage', async () => {
    const { svc, updateCalls } = makeService({ id: 'a3', deliveryType: 'partner', status: 'evidence_accepted' });
    await svc.recordUpload(user, 'a3', 'visit_form', file());
    expect(updateCalls[0]!.data.status).toBeUndefined();
  });
});
