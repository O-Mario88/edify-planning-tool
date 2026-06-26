import { BadRequestException, Inject, Injectable, NotFoundException } from '@nestjs/common';
import { closeSync, existsSync, openSync, readSync, rmSync } from 'node:fs';
import { extname, join, resolve } from 'node:path';
import { PrismaService } from '../../prisma/prisma.service';
import { ScopeService } from '../../common/scope/scope.service';
import { AuditService } from '../../common/audit/audit.service';
import { AuthorizationService } from '../../common/authz/authorization.service';
import { DomainEventService } from '../../common/realtime/domain-events.service';
import { AuthUser } from '../../common/auth/auth-user';
import { assertSafeUpload, sanitizeOriginalName } from './file-validation';
import { EVIDENCE_SCANNER, type EvidenceScanner } from './evidence-scanner';
import { DocxConverterService } from './docx-converter.service';

// Where uploaded evidence files live. On Railway, mount a persistent volume at
// this path (EVIDENCE_STORAGE_DIR) so files survive redeploys.
export const EVIDENCE_DIR = resolve(process.env.EVIDENCE_STORAGE_DIR ?? 'uploads/evidence');

// Minimal shape of a multer-stored file (avoids depending on @types/multer).
export interface StoredFile {
  originalname: string;
  mimetype: string;
  size: number;
  filename: string; // the random name multer wrote to EVIDENCE_DIR
  path: string;
}

const VALID_KINDS = new Set([
  'visit_form', 'school_stamp', 'attendance_form', 'meeting_minutes', 'resolutions',
  'evaluation_form', 'assessment_form', 'photo', 'pdf', 'project_report', 'coaching_notes',
]);

@Injectable()
export class EvidenceService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly scope: ScopeService,
    private readonly audit: AuditService,
    private readonly authz: AuthorizationService,
    private readonly events: DomainEventService,
    private readonly docxConverter: DocxConverterService,
    @Inject(EVIDENCE_SCANNER) private readonly scanner: EvidenceScanner,
  ) {}

  /** Remove a rejected/temp upload from disk (best-effort). */
  private discard(absPath?: string): void {
    if (absPath) rmSync(absPath, { force: true });
  }

  /** Read the first ~4KB of a stored file for magic-byte + scan inspection. */
  private readHead(absPath: string, bytes = 4100): Buffer {
    const fd = openSync(absPath, 'r');
    try {
      const buf = Buffer.alloc(bytes);
      const read = readSync(fd, buf, 0, bytes, 0);
      return buf.subarray(0, read);
    } finally {
      closeSync(fd);
    }
  }

  async recordUpload(user: AuthUser, activityId: string, kind: string, file: StoredFile) {
    if (!file) throw new BadRequestException('A file is required.');
    if (!VALID_KINDS.has(kind)) throw new BadRequestException(`Invalid evidence kind: ${kind}`);
    const activity = await this.prisma.activity.findFirst({
      where: { id: activityId, deletedAt: null },
      select: { id: true, deliveryType: true, status: true },
    });
    if (!activity) {
      this.discard(file.path);
      throw new NotFoundException('Activity not found');
    }
    // Object-level: the uploader must own/deliver this activity (a partner is
    // pinned to their own assigned work; staff to their portfolio).
    await this.authz.assertCanAccess(user, { kind: 'evidence', loadedEntity: { id: '', activityId, uploadedBy: user.userId } }, 'upload');

    // Content validation: extension + MIME + magic-byte sniff. The declared
    // type is NOT trusted — bytes must match, and active/executable content is
    // rejected. On any failure the temp file is removed.
    const head = this.readHead(file.path);
    try {
      assertSafeUpload(file, head);
    } catch (err) {
      this.discard(file.path);
      throw err;
    }

    // Malware scan (no-op default → 'skipped'). An infected file is quarantined
    // and deleted; it never reaches storage as servable.
    const scanStatus = await this.scanner.scan(file.path, head);
    if (scanStatus === 'infected') {
      this.discard(file.path);
      await this.audit.log({
        action: 'evidence.quarantine', subjectKind: 'Activity', subjectId: activityId,
        actorId: user.userId, actorRole: user.activeRole,
        payload: { originalName: sanitizeOriginalName(file.originalname), reason: 'malware-scan' },
      });
      throw new BadRequestException('The file was rejected by the malware scan.');
    }

    // Preview routing — set previewStatus based on file type so the FE viewer
    // knows whether to render immediately (PDF/image) or wait for a server
    // conversion (DOCX). The on-demand DOCX→PDF converter is called from
    // `prepareInlineView` the first time the user opens a DOCX rendition.
    const ext = extname(file.originalname || '').toLowerCase();
    const isPdf = file.mimetype === 'application/pdf' || ext === '.pdf';
    const isImage = file.mimetype.startsWith('image/');
    const isDocx =
      file.mimetype === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ||
      file.mimetype === 'application/msword' ||
      ext === '.docx' || ext === '.doc';
    const previewStatus = isPdf || isImage
      ? 'ready'
      : isDocx
        ? 'pending'
        : 'not_required';

    // The on-disk filename is the stored reference (relative to EVIDENCE_DIR).
    const rec = await this.prisma.evidenceRecord.create({
      data: {
        activityId, kind: kind as never, uri: file.filename,
        originalName: sanitizeOriginalName(file.originalname), mimeType: file.mimetype,
        fileExtension: ext || null,
        fileSize: file.size,
        storageProvider: 'local',
        uploadedBy: user.userId, uploaderRole: user.activeRole as never,
        status: 'uploaded', scanStatus,
        previewStatus,
      } as never,
    });
    // Partner-delivered work moves to "evidence uploaded" awaiting staff review;
    // staff-delivered just flags evidence present.
    //
    // The status must advance from ANY pre-evidence active status, not only
    // assigned_to_partner/partner_scheduled. Previously a partner who pressed
    // "Complete" (→ completion_started) or whose work sat in_progress before
    // uploading left the activity stuck — evidenceStatus said "uploaded" but the
    // workflow status never reached evidence_uploaded, so the CCEO/staff review
    // queue and command-center counts (which key off status === evidence_uploaded)
    // never surfaced the upload. We now advance from the full pre-evidence set.
    const PRE_EVIDENCE_STATUSES = new Set([
      'assigned_to_partner', 'partner_scheduled', 'scheduled', 'in_progress', 'completion_started',
    ]);
    const advancePartner = activity.deliveryType === 'partner' && PRE_EVIDENCE_STATUSES.has(activity.status);
    await this.prisma.activity.update({
      where: { id: activityId },
      data: {
        evidenceStatus: 'uploaded',
        ...(advancePartner ? { status: 'evidence_uploaded' as never } : {}),
      },
    });
    await this.audit.log({
      action: 'evidence.upload', subjectKind: 'Activity', subjectId: activityId,
      actorId: user.userId, actorRole: user.activeRole,
      payload: { kind, originalName: rec.originalName, size: file.size, mimeType: file.mimetype, scanStatus },
    });
    return { id: rec.id, kind, originalName: rec.originalName, size: file.size, status: rec.status };
  }

  async listForActivity(_user: AuthUser, activityId: string) {
    const rows = await this.prisma.evidenceRecord.findMany({
      where: { activityId }, orderBy: { createdAt: 'desc' }, take: 100,
    });
    return rows.map((r) => ({
      id: r.id, kind: r.kind, status: r.status, originalName: r.originalName, mimeType: r.mimeType,
      uploadedBy: r.uploadedBy, uploaderRole: (r as never as { uploaderRole?: string }).uploaderRole ?? null,
      uploadedAt: r.createdAt, reviewNote: r.reviewNote,
      fileSize: (r as never as { fileSize?: number }).fileSize ?? null,
      fileExtension: (r as never as { fileExtension?: string }).fileExtension ?? null,
      previewStatus: (r as never as { previewStatus?: string }).previewStatus ?? 'ready',
      pdfRenditionStatus: (r as never as { pdfRenditionStatus?: string }).pdfRenditionStatus ?? null,
      viewCount: (r as never as { viewCount?: number }).viewCount ?? 0,
    }));
  }

  /** Prepare a DOCX evidence record for inline viewing.
   *
   *  The View Evidence flow (spec §22):
   *    1. FE clicks View Evidence on a DOCX row
   *    2. FE calls POST /evidence/:id/prepare-view
   *    3. Backend checks the row — if `previewStatus === 'ready'` (PDF/image
   *       OR a cached DOCX rendition), it returns immediately.
   *    4. Otherwise it kicks the DOCX→PDF converter. Success → caches the
   *       rendition next to the original under `<base>.pdf` and sets
   *       `pdfRenditionStorageKey + pdfRenditionStatus = 'ready' +
   *       previewStatus = 'ready'`. Failure → `previewStatus = 'failed'`
   *       and the FE shows the "download original" fallback.
   *
   *  This is the SINGLE place the converter is invoked, so the failure mode
   *  is centralized + audited. */
  async prepareInlineView(user: AuthUser, id: string) {
    const rec = await this.prisma.evidenceRecord.findUnique({
      where: { id },
      select: {
        id: true, activityId: true, uploadedBy: true, uri: true, mimeType: true,
        originalName: true, quarantined: true,
        fileExtension: true, previewStatus: true,
        pdfRenditionStorageKey: true, pdfRenditionStatus: true,
      } as never,
    });
    if (!rec) throw new NotFoundException('Evidence not found');
    const r = rec as never as {
      id: string; activityId: string; uri: string; mimeType: string | null;
      fileExtension: string | null; previewStatus: string | null;
      pdfRenditionStorageKey: string | null; pdfRenditionStatus: string | null;
      quarantined: boolean; uploadedBy: string;
    };
    if (r.quarantined) throw new NotFoundException('Evidence file is unavailable');
    await this.authz.assertCanAccess(user, { kind: 'evidence', id, loadedEntity: rec }, 'download');

    // Already ready — PDF, image, or DOCX with cached rendition.
    if (r.previewStatus === 'ready' || (r.pdfRenditionStorageKey && r.pdfRenditionStatus === 'ready')) {
      return {
        id: r.id,
        previewStatus: 'ready',
        viewKind: r.pdfRenditionStorageKey ? 'pdf_rendition' : (r.mimeType?.startsWith('image/') ? 'image' : 'pdf'),
        renditionId: r.pdfRenditionStorageKey ? r.id : null,
      };
    }

    // DOCX needs conversion.
    const ext = (r.fileExtension ?? '').toLowerCase();
    const isDocx = ext === '.docx' || ext === '.doc' ||
      r.mimeType === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ||
      r.mimeType === 'application/msword';

    if (!isDocx) {
      // Not a DOCX and not pre-marked ready: treat as PDF/image (the upload
      // flow already set previewStatus on those — this is a defensive default).
      await this.prisma.evidenceRecord.update({
        where: { id },
        data: { previewStatus: 'ready' } as never,
      });
      return { id, previewStatus: 'ready', viewKind: r.mimeType?.startsWith('image/') ? 'image' : 'pdf', renditionId: null };
    }

    // Convert.
    const sourceAbs = join(EVIDENCE_DIR, r.uri.replace(/[/\\]/g, ''));
    if (!existsSync(sourceAbs)) {
      throw new NotFoundException('Evidence file missing on disk');
    }
    const renditionName = `${r.uri.replace(/\.[^.]+$/, '')}.pdf`;
    const result = await this.docxConverter.convert(sourceAbs, EVIDENCE_DIR, renditionName);

    if (!result.ok) {
      await this.prisma.evidenceRecord.update({
        where: { id },
        data: {
          previewStatus: 'failed',
          pdfRenditionStatus: 'failed',
          pdfRenditionError: result.message,
          pdfRenditionAt: new Date(),
        } as never,
      });
      await this.audit.log({
        action: 'evidence.convert.failed',
        subjectKind: 'Activity', subjectId: r.activityId,
        actorId: user.userId, actorRole: user.activeRole,
        payload: { evidenceId: id, reason: result.reason, message: result.message },
      });
      return { id, previewStatus: 'failed', viewKind: 'docx', renditionId: null, reason: result.reason, message: result.message };
    }

    await this.prisma.evidenceRecord.update({
      where: { id },
      data: {
        previewStatus: 'ready',
        pdfRenditionStorageKey: result.pdfFilename,
        pdfRenditionStatus: 'ready',
        pdfRenditionAt: new Date(),
      } as never,
    });
    await this.audit.log({
      action: 'evidence.convert.success',
      subjectKind: 'Activity', subjectId: r.activityId,
      actorId: user.userId, actorRole: user.activeRole,
      payload: { evidenceId: id, durationMs: result.durationMs },
    });

    return { id, previewStatus: 'ready', viewKind: 'pdf_rendition', renditionId: id };
  }

  /** Resolve a PDF rendition (DOCX→PDF cached output) for inline viewing.
   *  Streamed by the controller through the same authorization path as the
   *  original file. */
  async renditionFor(user: AuthUser, id: string): Promise<{ absPath: string; mimeType: string; originalName: string }> {
    const rec = await this.prisma.evidenceRecord.findUnique({
      where: { id },
      select: {
        id: true, activityId: true, uploadedBy: true, originalName: true, quarantined: true,
        pdfRenditionStorageKey: true, pdfRenditionStatus: true,
      } as never,
    });
    if (!rec) throw new NotFoundException('Evidence not found');
    const r = rec as never as {
      pdfRenditionStorageKey: string | null; pdfRenditionStatus: string | null;
      originalName: string | null; quarantined: boolean;
    };
    if (r.quarantined) throw new NotFoundException('Evidence file is unavailable');
    await this.authz.assertCanAccess(user, { kind: 'evidence', id, loadedEntity: rec }, 'download');
    if (!r.pdfRenditionStorageKey || r.pdfRenditionStatus !== 'ready') {
      throw new NotFoundException('PDF rendition is not ready');
    }
    const safe = r.pdfRenditionStorageKey.replace(/[/\\]/g, '');
    const absPath = join(EVIDENCE_DIR, safe);
    if (!existsSync(absPath)) throw new NotFoundException('Rendition file missing on disk');

    // Count + audit the view — every successful authorized inline view leaves
    // a trail.
    await this.prisma.evidenceRecord.update({
      where: { id },
      data: { viewCount: { increment: 1 } } as never,
    }).catch(() => undefined);
    await this.audit.log({
      action: 'evidence.view',
      subjectKind: 'Activity', subjectId: (rec as never as { activityId: string }).activityId,
      actorId: user.userId, actorRole: user.activeRole,
      payload: { evidenceId: id, viewKind: 'pdf_rendition' },
    });
    return {
      absPath,
      mimeType: 'application/pdf',
      originalName: sanitizeOriginalName((r.originalName ?? 'evidence').replace(/\.[^.]+$/, '') + '.pdf'),
    };
  }

  /** Resolve an evidence record to its absolute on-disk path (for streaming).
   *  Authorizes the CALLER against the parent activity (closes the download
   *  IDOR — the endpoint used to gate only on PLANNING_VIEW with no row check),
   *  blocks quarantined files, and audits the access as a sensitive download. */
  async fileFor(user: AuthUser, id: string): Promise<{ absPath: string; mimeType: string; originalName: string }> {
    const record = await this.prisma.evidenceRecord.findUnique({
      where: { id },
      select: { id: true, activityId: true, uploadedBy: true, uri: true, mimeType: true, originalName: true, quarantined: true },
    });
    if (!record) throw new NotFoundException('Evidence not found');
    if (record.quarantined) throw new NotFoundException('Evidence file is unavailable');
    // Object-level: the parent activity must be in the caller's scope.
    await this.authz.assertCanAccess(user, { kind: 'evidence', id, loadedEntity: record }, 'download');
    // Guard against path traversal — the uri is just a filename.
    const safe = record.uri.replace(/[/\\]/g, '');
    const absPath = join(EVIDENCE_DIR, safe);
    if (!existsSync(absPath)) throw new NotFoundException('Evidence file missing on disk');
    // Audit + view counter — every authorized download / inline view leaves
    // a trail (spec §22 audit logs). The audit row carries actor/time; the
    // counter is the cheap aggregate for the viewer chip.
    await this.prisma.evidenceRecord.update({
      where: { id },
      data: { viewCount: { increment: 1 } } as never,
    }).catch(() => undefined);
    await this.audit.log({
      action: 'evidence.view',
      subjectKind: 'Activity', subjectId: record.activityId,
      actorId: user.userId, actorRole: user.activeRole,
      payload: { evidenceId: id, viewKind: record.mimeType?.startsWith('image/') ? 'image' : 'pdf' },
    });
    return {
      absPath,
      mimeType: record.mimeType ?? 'application/octet-stream',
      originalName: sanitizeOriginalName(record.originalName ?? safe),
    };
  }

  /** Staff/PL/IA review of an uploaded evidence file: accept or return with a
   *  reason. Propagates to Activity.evidenceStatus so the IA / accountant
   *  payment gate is backed by an actually-reviewed file. */
  async review(user: AuthUser, id: string, action: 'accept' | 'return', note?: string) {
    const rec = await this.prisma.evidenceRecord.findUnique({ where: { id }, select: { id: true, activityId: true, uploadedBy: true } });
    if (!rec) throw new NotFoundException('Evidence not found');
    if (action === 'return' && !note?.trim()) throw new BadRequestException('A reason is required when returning evidence.');
    // Object-level: reviewer needs EVIDENCE_REVIEW + the activity in scope, and
    // can NEVER review evidence they uploaded themselves (no self-approval).
    await this.authz.assertCanAccess(user, { kind: 'evidence', id, loadedEntity: rec }, 'verify');
    const status = action === 'accept' ? 'accepted' : 'returned';
    const updated = await this.prisma.evidenceRecord.update({
      where: { id },
      data: { status: status as never, reviewedBy: user.userId, reviewedAt: new Date(), reviewNote: note ?? null },
    });
    // Advance the ACTIVITY workflow on acceptance. Once a CCEO accepts the
    // (partner-uploaded) evidence and no Salesforce ID has been recorded yet,
    // the activity now NEEDS that ID — move it to `salesforce_id_required` so it
    // surfaces in the command-center "enter Salesforce ID" queue and My Plan's
    // salesforceId section. complete() then transitions it to
    // awaiting_ia_verification. If the SF ID is already on the record (the
    // alternate order where the ID is entered before final review), we only
    // update evidenceStatus and leave the workflow status untouched.
    const activity = await this.prisma.activity.findUnique({
      where: { id: rec.activityId }, select: { status: true, salesforceActivityId: true },
    });
    const NEEDS_SF_FROM = new Set(['assigned_to_partner', 'partner_scheduled', 'in_progress', 'evidence_uploaded', 'evidence_accepted']);
    const advanceToSfRequired =
      action === 'accept' && !!activity && !activity.salesforceActivityId && NEEDS_SF_FROM.has(activity.status);
    await this.prisma.activity.update({
      where: { id: rec.activityId },
      data: {
        evidenceStatus: status as never,
        ...(advanceToSfRequired ? { status: 'salesforce_id_required' as never } : {}),
      },
    });
    await this.audit.log({
      action: `evidence.${action}`, subjectKind: 'Activity', subjectId: rec.activityId,
      actorId: user.userId, actorRole: user.activeRole, payload: { evidenceId: id, note },
    });
    // On accept, the evidence issue is handled — resolve any open "evidence
    // missing / re-upload needed" alerts for this activity so they don't linger.
    if (action === 'accept') {
      await this.events.resolveContext('evidence', rec.activityId);
    }
    // Close the handoff: tell the uploader their evidence was accepted/returned.
    // A return is actionable (re-upload); an accept is informational. Without
    // this, the partner/staff who submitted had no signal and had to poll. The
    // route is resolved role-aware by the engine (a partner uploader lands on
    // /partner/activities, a staff uploader on /my-plan — never the wrong page).
    if (rec.uploadedBy) {
      await this.events.emit({
        type: action === 'accept' ? 'EvidenceAccepted' : 'EvidenceReturned',
        actorId: user.userId, actorRole: user.activeRole, subjectKind: 'Activity', subjectId: rec.activityId,
        payload: { evidenceId: id },
        notify: [{
          recipientId: rec.uploadedBy,
          title: action === 'accept' ? 'Evidence accepted' : 'Evidence returned — re-upload needed',
          body: action === 'accept'
            ? 'Your submitted evidence was accepted.'
            : note ? `Returned: ${note}` : 'Please review and re-upload your evidence.',
          contextType: 'evidence',
          contextId: rec.activityId,
          actionRequired: action === 'return',
          priority: action === 'return' ? 'high' : 'normal',
        }],
        liveUserIds: [user.userId, rec.uploadedBy],
      });
    }
    return { id: updated.id, status: updated.status };
  }
}
