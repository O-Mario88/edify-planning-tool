import { BadRequestException, ConflictException, Injectable, NotFoundException } from '@nestjs/common';
import { EdifyRole } from '@prisma/client';
import { PrismaService } from '../../prisma/prisma.service';
import { AuditService } from '../../common/audit/audit.service';
import { generateToken, hashToken, expiryFromNow, expiryFromNowDays } from '../../common/security/auth-tokens';

// How long a (re)sent invitation remains valid.
const INVITE_TTL_DAYS = Number(process.env.INVITE_TOKEN_TTL_DAYS ?? 7);

/**
 * Admin user management: create + invite, resend/revoke invite,
 * suspend/disable/reactivate, force password reset. All actions are
 * permission-guarded at the controller (USER_MANAGE) + audit-logged here.
 *
 * The create flow NEVER sets a password — the user sets their own via the
 * one-time invite link (/auth/set-password). This is the spec's core rule:
 * "Admin creates users. User receives invite link. User sets password."
 */
@Injectable()
export class AdminUsersService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly audit: AuditService,
  ) {}

  /** Roster with status, last login, invitation + onboarding state. */
  async list() {
    const users = await this.prisma.user.findMany({
      where: { deletedAt: null },
      orderBy: { createdAt: 'desc' },
      include: {
        staffProfile: { select: { id: true, onboardingState: true, primaryDistrict: { select: { name: true } } } },
        invitations: { orderBy: { createdAt: 'desc' }, take: 1 },
      },
    });
    return users.map((u) => ({
      id: u.id,
      name: u.name,
      email: u.email,
      phone: u.phone,
      roles: u.roles,
      activeRole: u.activeRole,
      status: u.status,
      isActive: u.isActive,
      lastLoginAt: u.lastLoginAt,
      passwordSet: !!u.passwordSetAt,
      primaryDistrict: u.staffProfile?.primaryDistrict?.name ?? null,
      onboardingState: u.staffProfile?.onboardingState ?? null,
      invitation: u.invitations[0]
        ? {
            status: u.invitations[0].acceptedAt ? 'accepted' : u.invitations[0].revokedAt ? 'revoked' : u.invitations[0].expiresAt < new Date() ? 'expired' : 'pending',
            expiresAt: u.invitations[0].expiresAt,
            createdAt: u.invitations[0].createdAt,
          }
        : null,
    }));
  }

  /**
   * Create a user in `pending_invited` status (no password) + issue a one-time
   * invite token. Returns the raw token ONCE so the controller can email it.
   * Throws ConflictException if the email already exists.
   */
  async create(actorId: string, dto: { name: string; email: string; phone?: string; role: EdifyRole; additionalRoles?: EdifyRole[]; primaryDistrictId?: string }) {
    const email = dto.email.toLowerCase();
    const existing = await this.prisma.user.findFirst({ where: { email, deletedAt: null } });
    if (existing) throw new ConflictException('A user with this email already exists.');

    const roles = Array.from(new Set([dto.role, ...(dto.additionalRoles ?? [])]));
    const user = await this.prisma.user.create({
      data: {
        email,
        name: dto.name,
        phone: dto.phone,
        // passwordHash left null — set via the invite link.
        roles,
        activeRole: dto.role,
        status: 'pending_invited',
        isActive: false,
        passwordSetAt: null,
        ...(dto.primaryDistrictId
          ? { staffProfile: { create: { primaryDistrictId: dto.primaryDistrictId, onboardingState: 'pending' } } }
          : {}),
      },
    });

    const inviteToken = await this.createInvitation(user.id, actorId);
    await this.audit.log({ action: 'admin.user.invited', actorId, subjectKind: 'User', subjectId: user.id, success: true, payload: { email, role: dto.role } });
    return { user: { id: user.id, email, name: user.name, status: user.status }, inviteToken };
  }

  /** Issue (or re-issue) an invitation token for a user. Returns the raw token. */
  async createInvitation(userId: string, invitedById: string): Promise<string> {
    const rawToken = generateToken();
    await this.prisma.userInvitation.create({
      data: {
        userId,
        invitedById,
        tokenHash: hashToken(rawToken),
        expiresAt: expiryFromNowDays(INVITE_TTL_DAYS),
      },
    });
    return rawToken;
  }

  /** Resend the invitation (issue a fresh token; old ones stay valid but the
   *  newest is what gets emailed). Only for users not yet active. */
  async resendInvite(actorId: string, userId: string) {
    const user = await this.findUserOrThrow(userId);
    if (user.status === 'active' && user.passwordSetAt) {
      throw new BadRequestException('This user has already accepted their invitation.');
    }
    const inviteToken = await this.createInvitation(userId, actorId);
    await this.audit.log({ action: 'admin.user.invite_resent', actorId, subjectKind: 'User', subjectId: userId, success: true });
    return { inviteToken };
  }

  /** Revoke all pending invitations for a user. */
  async revokeInvite(actorId: string, userId: string) {
    await this.findUserOrThrow(userId);
    await this.prisma.userInvitation.updateMany({
      where: { userId, acceptedAt: null, revokedAt: null },
      data: { revokedAt: new Date() },
    });
    await this.audit.log({ action: 'admin.user.invite_revoked', actorId, subjectKind: 'User', subjectId: userId, success: true });
    return { ok: true };
  }

  /** Suspend: block login but keep the account (reversible). */
  async suspend(actorId: string, userId: string) {
    await this.findUserOrThrow(userId);
    await this.prisma.user.update({ where: { id: userId }, data: { status: 'suspended', isActive: false } });
    // Revoke all active refresh tokens — ends current sessions immediately.
    await this.prisma.refreshToken.updateMany({ where: { userId, revokedAt: null }, data: { revokedAt: new Date() } });
    await this.audit.log({ action: 'admin.user.suspended', actorId, subjectKind: 'User', subjectId: userId, success: true });
    return { ok: true };
  }

  /** Disable: permanent deactivation (account kept for audit, cannot log in). */
  async disable(actorId: string, userId: string) {
    await this.findUserOrThrow(userId);
    await this.prisma.user.update({ where: { id: userId }, data: { status: 'disabled', isActive: false } });
    await this.prisma.refreshToken.updateMany({ where: { userId, revokedAt: null }, data: { revokedAt: new Date() } });
    await this.audit.log({ action: 'admin.user.disabled', actorId, subjectKind: 'User', subjectId: userId, success: true });
    return { ok: true };
  }

  /** Reactivate a suspended/disabled user back to active. */
  async reactivate(actorId: string, userId: string) {
    const user = await this.findUserOrThrow(userId);
    if (!user.passwordSetAt) {
      throw new BadRequestException('This user has not set a password yet. Resend their invitation instead.');
    }
    await this.prisma.user.update({ where: { id: userId }, data: { status: 'active', isActive: true } });
    await this.audit.log({ action: 'admin.user.reactivated', actorId, subjectKind: 'User', subjectId: userId, success: true });
    return { ok: true };
  }

  /** Force a password reset: issue a reset token the admin relays to the user. */
  async forcePasswordReset(actorId: string, userId: string) {
    const user = await this.findUserOrThrow(userId);
    const rawToken = generateToken();
    await this.prisma.user.update({
      where: { id: userId },
      data: { passwordResetTokenHash: hashToken(rawToken), passwordResetExpires: expiryFromNow(Number(process.env.PASSWORD_RESET_TOKEN_TTL_MINUTES ?? 45)) },
    });
    await this.prisma.refreshToken.updateMany({ where: { userId, revokedAt: null }, data: { revokedAt: new Date() } });
    await this.audit.log({ action: 'admin.user.force_password_reset', actorId, subjectKind: 'User', subjectId: userId, success: true });
    return { resetToken: rawToken };
  }

  private async findUserOrThrow(userId: string) {
    const user = await this.prisma.user.findFirst({ where: { id: userId, deletedAt: null } });
    if (!user) throw new NotFoundException('User not found.');
    return user;
  }
}
