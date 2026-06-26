import { Body, Controller, Get, Post, Query, UseGuards } from '@nestjs/common';
import { ApiBearerAuth, ApiTags } from '@nestjs/swagger';
import { AuthService } from './auth.service';
import { AuthTokensService } from './auth-tokens.service';
import { LoginDto } from './dto/login.dto';
import { ForgotPasswordDto, LogoutDto, RefreshDto, ResetPasswordDto, SetPasswordDto } from './dto/auth-tokens.dto';
import { JwtAuthGuard } from '../../common/auth/jwt-auth.guard';
import { CurrentUser } from '../../common/auth/current-user.decorator';
import { AuthUser } from '../../common/auth/auth-user';
import { ScopeService } from '../../common/scope/scope.service';
import { permissionsForRole } from '../../common/rbac/permissions';
import { RateLimitGuard, RateLimit } from '../../common/security/rate-limit';

@ApiTags('auth')
@Controller('auth')
export class AuthController {
  constructor(
    private readonly auth: AuthService,
    private readonly tokens: AuthTokensService,
    private readonly scope: ScopeService,
  ) {}

  // Brute-force throttle: at most 10 sign-in attempts per IP per minute, layered
  // on top of the per-account lockout in AuthService.
  @Post('login')
  @UseGuards(RateLimitGuard)
  @RateLimit({ name: 'login', limit: 10, windowMs: 60_000 })
  login(@Body() dto: LoginDto) {
    return this.auth.login(dto);
  }

  @ApiBearerAuth()
  @UseGuards(JwtAuthGuard)
  @Get('me')
  async me(@CurrentUser() user: AuthUser) {
    const s = await this.scope.resolveUserScope(user);
    // Return capability flags, not the internal id sets.
    return {
      ...user,
      permissions: permissionsForRole(user.activeRole),
      scope: {
        countryScope: s.countryScope,
        canViewSummaryOnly: s.canViewSummaryOnly,
        canViewSchoolLevelDetail: s.canViewSchoolLevelDetail,
        canViewPartnerData: s.canViewPartnerData,
        canViewFinancialData: s.canViewFinancialData,
        canApprove: s.canApprove,
        canAssign: s.canAssign,
        canExport: s.canExport,
        schoolsInScope: s.countryScope ? null : s.schoolIds.length,
      },
    };
  }

  // ── Refresh + logout (rotating, revocable refresh tokens) ────────────
  @Post('refresh')
  refresh(@Body() dto: RefreshDto) {
    return this.tokens.refresh(dto.refreshToken);
  }

  @Post('logout')
  logout(@Body() dto: LogoutDto) {
    return this.tokens.logout(dto.refreshToken);
  }

  // ── Forgot / reset password ──────────────────────────────────────────
  // Rate-limited so a reset-link flood can't enumerate or abuse the endpoint.
  @Post('forgot-password')
  @UseGuards(RateLimitGuard)
  @RateLimit({ name: 'forgot-password', limit: 4, windowMs: 10 * 60_000 })
  forgotPassword(@Body() dto: ForgotPasswordDto) {
    return this.tokens.forgotPassword(dto.email);
  }

  @Post('reset-password')
  resetPassword(@Body() dto: ResetPasswordDto) {
    return this.tokens.resetPassword(dto.token, dto.password, dto.confirm);
  }

  // ── Invitation: validate (GET) + set-password (POST) ─────────────────
  @Get('invite/validate')
  validateInvite(@Query('token') token: string) {
    return this.tokens.validateInvite(token);
  }

  @Post('set-password')
  setPassword(@Body() dto: SetPasswordDto) {
    return this.tokens.setPassword(dto.token, dto.password, dto.confirm);
  }
}
