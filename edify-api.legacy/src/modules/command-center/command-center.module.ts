import { Module } from '@nestjs/common';
import { CommandCenterService } from './command-center.service';
import { CommandCenterAlertsService } from './command-center-alerts.service';
import { CommandCenterController } from './command-center.controller';

@Module({
  controllers: [CommandCenterController],
  providers: [CommandCenterService, CommandCenterAlertsService],
  exports: [CommandCenterAlertsService],
})
export class CommandCenterModule {}
