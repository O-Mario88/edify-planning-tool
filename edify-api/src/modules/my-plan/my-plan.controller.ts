import { Controller, Get, Query, UseGuards } from '@nestjs/common';
import { ApiBearerAuth, ApiTags } from '@nestjs/swagger';
import { JwtAuthGuard } from '../../common/auth/jwt-auth.guard';
import { PermissionsGuard } from '../../common/rbac/permissions.guard';
import { RequirePermissions } from '../../common/rbac/require-permissions.decorator';
import { PERMISSIONS } from '../../common/rbac/permissions';
import { CurrentUser } from '../../common/auth/current-user.decorator';
import { AuthUser } from '../../common/auth/auth-user';
import { MyPlanService, type MyPlanPeriod } from './my-plan.service';

@ApiTags('my-plan')
@ApiBearerAuth()
@UseGuards(JwtAuthGuard, PermissionsGuard)
@Controller('my-plan')
export class MyPlanController {
  constructor(private readonly myPlan: MyPlanService) {}

  @Get()
  @RequirePermissions(PERMISSIONS.PLANNING_VIEW)
  list(
    @CurrentUser() user: AuthUser,
    @Query('period') period?: MyPlanPeriod,
    @Query('fy') fy?: string,
  ) {
    return this.myPlan.get(user, { period, fy });
  }
}
