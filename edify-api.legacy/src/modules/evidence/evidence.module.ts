import { Module } from '@nestjs/common';
import { EvidenceService } from './evidence.service';
import { EvidenceController } from './evidence.controller';
import { EVIDENCE_SCANNER, NoopEvidenceScanner } from './evidence-scanner';
import { DocxConverterService } from './docx-converter.service';

@Module({
  controllers: [EvidenceController],
  providers: [
    EvidenceService,
    DocxConverterService,
    // Swap NoopEvidenceScanner for a ClamAV-backed scanner in production.
    { provide: EVIDENCE_SCANNER, useClass: NoopEvidenceScanner },
  ],
  exports: [DocxConverterService],
})
export class EvidenceModule {}
