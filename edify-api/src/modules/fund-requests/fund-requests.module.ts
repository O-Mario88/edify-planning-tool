import { Module } from '@nestjs/common';
import { FundRequestsService } from './fund-requests.service';
import { FundRequestsController } from './fund-requests.controller';
import { BudgetAutomationService } from './budget-automation.service';
import { MonthlyWorkPlanService } from './monthly-work-plan.service';
import { MonthlyWorkPlanController } from './monthly-work-plan.controller';
import { BudgetModule } from '../budget/budget.module';

@Module({
  imports: [BudgetModule],
  controllers: [FundRequestsController, MonthlyWorkPlanController],
  providers: [FundRequestsService, BudgetAutomationService, MonthlyWorkPlanService],
  exports: [BudgetAutomationService, MonthlyWorkPlanService],
})
export class FundRequestsModule {}
