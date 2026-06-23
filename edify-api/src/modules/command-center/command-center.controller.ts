import { Body, Controller, Get, Param, Post, UseGuards } from '@nestjs/common';
import { ApiBearerAuth, ApiTags } from '@nestjs/swagger';
import { CommandCenterService } from './command-center.service';
import { CommandCenterAlertsService } from './command-center-alerts.service';
import { JwtAuthGuard } from '../../common/auth/jwt-auth.guard';
import { CurrentUser } from '../../common/auth/current-user.decorator';
import { AuthUser } from '../../common/auth/auth-user';

// The recommendation-led home feed. Every authenticated role gets a
// role-scoped "what must I do next" list — no permission gate beyond auth,
// because the service tailors the feed to the caller's role + scope.
@ApiTags('command-center')
@ApiBearerAuth()
@UseGuards(JwtAuthGuard)
@Controller('command-center')
export class CommandCenterController {
  constructor(
    private readonly cc: CommandCenterService,
    private readonly alerts: CommandCenterAlertsService,
  ) {}

  @Get('today')
  today(@CurrentUser() user: AuthUser) {
    return this.cc.today(user);
  }

  // ── Persistent operational alerts (spec §13/§17) ──────────────────────────
  // Generated live from data conditions; reappear while unresolved.
  @Get('alerts')
  listAlerts(@CurrentUser() user: AuthUser) {
    return this.alerts.list(user);
  }

  @Get('alerts/summary')
  alertsSummary(@CurrentUser() user: AuthUser) {
    return this.alerts.summary(user);
  }

  @Post('alerts/:id/dismiss')
  dismissAlert(@Param('id') id: string, @Body() body: { hours?: number }, @CurrentUser() user: AuthUser) {
    return this.alerts.dismiss(user, id, body?.hours);
  }
}
