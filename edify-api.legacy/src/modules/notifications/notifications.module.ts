import { Module } from '@nestjs/common';
import { NotificationsService } from './notifications.service';
import { NotificationsController } from './notifications.controller';
import { NotificationJobsService } from './notification-jobs.service';

@Module({
  controllers: [NotificationsController],
  providers: [NotificationsService, NotificationJobsService],
  exports: [NotificationJobsService],
})
export class NotificationsModule {}
