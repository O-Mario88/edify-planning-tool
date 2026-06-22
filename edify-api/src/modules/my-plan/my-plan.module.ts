import { Module } from '@nestjs/common';
import { MyPlanService } from './my-plan.service';
import { MyPlanController } from './my-plan.controller';

@Module({
  controllers: [MyPlanController],
  providers: [MyPlanService],
  exports: [MyPlanService],
})
export class MyPlanModule {}
