import { Global, Module } from '@nestjs/common';
import { MailerService } from './mailer.service';

// Global so auth + admin-users can inject MailerService without per-module wiring.
@Global()
@Module({
  providers: [MailerService],
  exports: [MailerService],
})
export class EmailModule {}
