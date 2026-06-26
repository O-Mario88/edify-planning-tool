import { Body, Controller, Get, Param, Post, UseGuards } from '@nestjs/common';
import { ApiBearerAuth, ApiTags } from '@nestjs/swagger';
import { AdminUsersService } from './admin-users.service';
import { CreateUserDto } from './dto/admin-users.dto';
import { JwtAuthGuard } from '../../common/auth/jwt-auth.guard';
import { PermissionsGuard } from '../../common/rbac/permissions.guard';
import { RequirePermissions } from '../../common/rbac/require-permissions.decorator';
import { PERMISSIONS } from '../../common/rbac/permissions';
import { CurrentUser } from '../../common/auth/current-user.decorator';
import { AuthUser } from '../../common/auth/auth-user';

@ApiTags('admin-users')
@ApiBearerAuth()
@UseGuards(JwtAuthGuard, PermissionsGuard)
@Controller('admin/users')
export class AdminUsersController {
  constructor(private readonly users: AdminUsersService) {}

  @Get()
  @RequirePermissions(PERMISSIONS.USER_MANAGE)
  list() {
    return this.users.list();
  }

  // Create + invite in one step. Returns the raw invite token once so the
  // caller can email it (or surface it in the admin UI in dev).
  @Post()
  @RequirePermissions(PERMISSIONS.USER_MANAGE)
  create(@CurrentUser() actor: AuthUser, @Body() dto: CreateUserDto) {
    return this.users.create(actor.userId, dto);
  }

  @Post(':id/resend-invite')
  @RequirePermissions(PERMISSIONS.USER_MANAGE)
  resendInvite(@CurrentUser() actor: AuthUser, @Param('id') id: string) {
    return this.users.resendInvite(actor.userId, id);
  }

  @Post(':id/revoke-invite')
  @RequirePermissions(PERMISSIONS.USER_MANAGE)
  revokeInvite(@CurrentUser() actor: AuthUser, @Param('id') id: string) {
    return this.users.revokeInvite(actor.userId, id);
  }

  @Post(':id/suspend')
  @RequirePermissions(PERMISSIONS.USER_MANAGE)
  suspend(@CurrentUser() actor: AuthUser, @Param('id') id: string) {
    return this.users.suspend(actor.userId, id);
  }

  @Post(':id/disable')
  @RequirePermissions(PERMISSIONS.USER_MANAGE)
  disable(@CurrentUser() actor: AuthUser, @Param('id') id: string) {
    return this.users.disable(actor.userId, id);
  }

  @Post(':id/reactivate')
  @RequirePermissions(PERMISSIONS.USER_MANAGE)
  reactivate(@CurrentUser() actor: AuthUser, @Param('id') id: string) {
    return this.users.reactivate(actor.userId, id);
  }

  @Post(':id/force-password-reset')
  @RequirePermissions(PERMISSIONS.USER_MANAGE)
  forcePasswordReset(@CurrentUser() actor: AuthUser, @Param('id') id: string) {
    return this.users.forcePasswordReset(actor.userId, id);
  }
}
