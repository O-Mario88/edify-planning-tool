import { BadRequestException, Body, Controller, Get, Param, Post, UseGuards } from '@nestjs/common';
import { ApiBearerAuth, ApiTags } from '@nestjs/swagger';
import { CoreService } from './core.service';
import { JwtAuthGuard } from '../../common/auth/jwt-auth.guard';
import { PermissionsGuard } from '../../common/rbac/permissions.guard';
import { RequirePermissions } from '../../common/rbac/require-permissions.decorator';
import { PERMISSIONS } from '../../common/rbac/permissions';
import { CurrentUser } from '../../common/auth/current-user.decorator';
import { AuthUser } from '../../common/auth/auth-user';
import {
  OnboardCoreDto, RejectCandidateDto, ScheduleFollowUpDto, SlotAssignDto, SlotCompleteDto,
  SlotEvidenceDto, SlotReturnDto, SlotScheduleDto, UploadFollowUpSsaDto, VerifyCandidateDto,
} from './dto/core.dto';

const SLOT_ACTIONS = new Set([
  'assign', 'schedule', 'start', 'evidence', 'acceptEvidence', 'returnEvidence',
  'complete', 'plVerify', 'iaVerify', 'return', 'accountantConfirm',
]);

@ApiTags('core')
@ApiBearerAuth()
@UseGuards(JwtAuthGuard, PermissionsGuard)
@Controller('core')
export class CoreController {
  constructor(private readonly core: CoreService) {}

  @Get('candidates')
  @RequirePermissions(PERMISSIONS.PLANNING_VIEW)
  listCandidates(@CurrentUser() user: AuthUser) {
    return this.core.listCandidates(user);
  }

  @Post('candidates/:schoolId/verify')
  @RequirePermissions(PERMISSIONS.SSA_UPLOAD)
  verifyCandidate(
    @Param('schoolId') schoolId: string,
    @Body() dto: VerifyCandidateDto,
    @CurrentUser() user: AuthUser,
  ) {
    return this.core.verifyCandidate(user, schoolId, dto.verificationId, dto.comments);
  }

  @Post('candidates/:schoolId/reject')
  @RequirePermissions(PERMISSIONS.PLANNING_CREATE)
  rejectCandidate(
    @Param('schoolId') schoolId: string,
    @Body() dto: RejectCandidateDto,
    @CurrentUser() user: AuthUser,
  ) {
    return this.core.rejectCandidate(user, schoolId, dto.reason);
  }

  @Post('candidates/:schoolId/onboard')
  @RequirePermissions(PERMISSIONS.PLANNING_CREATE)
  onboard(
    @Param('schoolId') schoolId: string,
    @Body() dto: OnboardCoreDto,
    @CurrentUser() user: AuthUser,
  ) {
    return this.core.onboard(user, schoolId, dto.reason);
  }

  @Get('plans')
  @RequirePermissions(PERMISSIONS.PLANNING_VIEW)
  listPlans(@CurrentUser() user: AuthUser) {
    return this.core.listPlans(user);
  }

  @Get('schools/:schoolId')
  @RequirePermissions(PERMISSIONS.PLANNING_VIEW)
  getDetail(@Param('schoolId') schoolId: string, @CurrentUser() user: AuthUser) {
    return this.core.getDetail(user, schoolId);
  }

  @Post('slots/:slotId/:action')
  @RequirePermissions(PERMISSIONS.PLANNING_VIEW)
  slotAction(
    @Param('slotId') slotId: string,
    @Param('action') action: string,
    @Body() body: Record<string, unknown>,
    @CurrentUser() user: AuthUser,
  ) {
    if (!SLOT_ACTIONS.has(action)) throw new BadRequestException(`Unknown slot action: ${action}`);
    return this.core.slotAction(user, slotId, action, body);
  }

  @Post('plans/:planId/follow-up/schedule')
  @RequirePermissions(PERMISSIONS.PLANNING_VIEW)
  scheduleFollowUp(
    @Param('planId') planId: string,
    @Body() dto: ScheduleFollowUpDto,
    @CurrentUser() user: AuthUser,
  ) {
    return this.core.scheduleFollowUp(user, planId, dto.assignee, dto.monthLabel, dto.week);
  }

  @Post('plans/:planId/follow-up/ssa')
  @RequirePermissions(PERMISSIONS.SSA_UPLOAD)
  uploadFollowUpSsa(
    @Param('planId') planId: string,
    @Body() dto: UploadFollowUpSsaDto,
    @CurrentUser() user: AuthUser,
  ) {
    return this.core.uploadFollowUpSsa(user, planId, dto);
  }

  @Post('schools/:schoolId/champion/advance')
  @RequirePermissions(PERMISSIONS.PLANNING_VIEW)
  advanceChampion(@Param('schoolId') schoolId: string, @CurrentUser() user: AuthUser) {
    return this.core.advanceChampion(user, schoolId);
  }
}
