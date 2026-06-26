import { Body, Controller, Get, Param, Post, UseGuards } from '@nestjs/common';
import { ApiBearerAuth, ApiTags } from '@nestjs/swagger';
import { JwtAuthGuard } from '../../common/auth/jwt-auth.guard';
import { PermissionsGuard } from '../../common/rbac/permissions.guard';
import { RequirePermissions } from '../../common/rbac/require-permissions.decorator';
import { PERMISSIONS } from '../../common/rbac/permissions';
import { CurrentUser } from '../../common/auth/current-user.decorator';
import { AuthUser } from '../../common/auth/auth-user';
import { PlReviewService } from './pl-review.service';

@ApiTags('pl-review')
@ApiBearerAuth()
@UseGuards(JwtAuthGuard, PermissionsGuard)
@Controller('pl/review-queue')
export class PlReviewController {
  constructor(private readonly plReview: PlReviewService) {}

  @Get()
  @RequirePermissions(PERMISSIONS.PLANNING_VIEW)
  queue(@CurrentUser() user: AuthUser) {
    return this.plReview.queue(user);
  }

  @Post(':id/confirm')
  @RequirePermissions(PERMISSIONS.PLANNING_VIEW)
  confirm(@Param('id') id: string, @CurrentUser() user: AuthUser) {
    return this.plReview.confirm(id, user);
  }

  @Post(':id/return')
  @RequirePermissions(PERMISSIONS.PLANNING_VIEW)
  returnActivity(@Param('id') id: string, @Body() body: { reason: string }, @CurrentUser() user: AuthUser) {
    return this.plReview.return(id, body.reason, user);
  }
}
