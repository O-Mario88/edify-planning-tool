import { Body, Controller, Delete, Get, Param, Post, Query, UseGuards } from '@nestjs/common';
import { ApiBearerAuth, ApiTags } from '@nestjs/swagger';
import { MonthlyWorkPlanService } from './monthly-work-plan.service';
import { JwtAuthGuard } from '../../common/auth/jwt-auth.guard';
import { PermissionsGuard } from '../../common/rbac/permissions.guard';
import { RequirePermissions } from '../../common/rbac/require-permissions.decorator';
import { PERMISSIONS } from '../../common/rbac/permissions';
import { CurrentUser } from '../../common/auth/current-user.decorator';
import { AuthUser } from '../../common/auth/auth-user';

@ApiTags('monthly-work-plan-budget')
@ApiBearerAuth()
@UseGuards(JwtAuthGuard, PermissionsGuard)
@Controller('monthly-work-plan-budget')
export class MonthlyWorkPlanController {
  constructor(private readonly mwp: MonthlyWorkPlanService) {}

  @Get()
  @RequirePermissions(PERMISSIONS.PLANNING_VIEW)
  list(@CurrentUser() user: AuthUser, @Query('fy') fy?: string) {
    return this.mwp.list(user, { fy });
  }

  @Get(':id')
  @RequirePermissions(PERMISSIONS.PLANNING_VIEW)
  getOne(@Param('id') id: string, @CurrentUser() user: AuthUser) {
    return this.mwp.getOne(user, id);
  }

  // CD adds admin items (rent, airtime, internet, …).
  @Post(':id/admin-lines')
  @RequirePermissions(PERMISSIONS.BUDGET_APPROVE)
  addAdminLine(
    @Param('id') id: string,
    @Body() body: { costCategory: string; description: string; quantity?: number; unitCost: number; justification?: string },
    @CurrentUser() user: AuthUser,
  ) {
    return this.mwp.addAdminLine(user, id, body);
  }

  @Delete(':id/admin-lines/:lineId')
  @RequirePermissions(PERMISSIONS.BUDGET_APPROVE)
  removeAdminLine(
    @Param('id') id: string, @Param('lineId') lineId: string,
    @CurrentUser() user: AuthUser,
  ) {
    return this.mwp.removeAdminLine(user, id, lineId);
  }

  // CD → RVP routing.
  @Post(':id/submit-to-rvp')
  @RequirePermissions(PERMISSIONS.BUDGET_APPROVE)
  submitToRvp(@Param('id') id: string, @CurrentUser() user: AuthUser) {
    return this.mwp.submitToRvp(user, id);
  }

  @Post(':id/rvp-approve')
  @RequirePermissions(PERMISSIONS.BUDGET_APPROVE)
  rvpApprove(@Param('id') id: string, @Body() body: { note?: string }, @CurrentUser() user: AuthUser) {
    return this.mwp.rvpReview(user, id, 'approve', body?.note);
  }

  @Post(':id/rvp-return')
  @RequirePermissions(PERMISSIONS.BUDGET_APPROVE)
  rvpReturn(@Param('id') id: string, @Body() body: { note?: string }, @CurrentUser() user: AuthUser) {
    return this.mwp.rvpReview(user, id, 'return', body?.note);
  }

  @Post(':id/send-to-accountant')
  @RequirePermissions(PERMISSIONS.BUDGET_APPROVE)
  sendToAccountant(@Param('id') id: string, @CurrentUser() user: AuthUser) {
    return this.mwp.markSentToAccountant(user, id);
  }
}
