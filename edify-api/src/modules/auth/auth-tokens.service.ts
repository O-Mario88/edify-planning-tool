import { BadRequestException, Injectable, NotFoundException, UnauthorizedException } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import * as bcrypt from 'bcryptjs';
import { PrismaService } from '../../prisma/prisma.service';
import { AuditService } from '../../common/audit/audit.service';
import { permissionsForRole } from '../../common/rbac/permissions';
import { generateToken, hashToken, compareHashes, expiryFromNow, expiryFromNowDays } from '../../common/security/auth-tokens';
import { validatePassword } from '../../common/security/password-rules';

// Token lifetimes — overridable via env. Refresh is long so a user stays signed
// in; reset is short to limit the exposure window of a leaked link; invite is
// generous because a new user may not open it immediately.
const REFRESH_TTL_DAYS = Number(process.env.REFRESH_TOKEN_TTL_DAYS ?? 7);
const RESET_TTL_MINUTES = Number(process.env.PASSWORD_RESET_TOKEN_TTL_MINUTES ?? 45);
const INVITE_TTL_DAYS = Number(process.env.INVITE_TOKEN_TTL_DAYS ?? 7);

/**
 * Auth-token lifecycle: refresh, logout, forgot/reset password, set-password,
 * and invite validation. The User's own passwordHash is updated here too
 * (set-password + reset), using bcrypt at cost 12.
 *
 * Token storage rule: the DB holds ONLY the SHA-256 hash. The raw token is
 * returned to the caller exactly once (in the email link / API response for
 * dev). Single-use + expiring + revocable.
 */
@Injectable()
export class AuthTokensService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly jwt: JwtService,
    private readonly audit: AuditService,
  ) {}

  // ── Refresh token rotation + logout ──────────────────────────────────

  /** Validate a refresh token, revoke it, and issue a fresh access+refresh
   *  pair. Rotation means a stolen token is useless after one legitimate use. */
  async refresh(refreshToken: string) {
    const tokenHash = hashToken(refreshToken);
    const record = await this.prisma.refreshToken.findFirst({
      where: { tokenHash, revokedAt: null, expiresAt: { gt: new Date() } },
      include: { user: true },
    });
    if (!record || !record.user || record.user.status !== 'active') {
      throw new UnauthorizedException('Invalid or expired refresh token.');
    }
    // Revoke the consumed token (single-use).
    await this.prisma.refreshToken.update({
      where: { id: record.id },
      data: { revokedAt: new Date() },
    });
    return this.issueTokenPair(record.user.id, record.user.activeRole);
  }

  /** Revoke a refresh token (logout). The access JWT expires on its own (15m). */
  async logout(refreshToken?: string) {
    if (!refreshToken) return { ok: true };
    const tokenHash = hashToken(refreshToken);
    await this.prisma.refreshToken.updateMany({
      where: { tokenHash, revokedAt: null },
      data: { revokedAt: new Date() },
    });
    return { ok: true };
  }

  /** Mint an access JWT (15m) + a persisted, hashed refresh token (7d). */
  async issueTokenPair(userId: string, activeRole: string) {
    const accessToken = await this.jwt.signAsync({ sub: userId, activeRole });
    const rawRefresh = generateToken();
    await this.prisma.refreshToken.create({
      data: {
        userId,
        tokenHash: hashToken(rawRefresh),
        expiresAt: expiryFromNowDays(REFRESH_TTL_DAYS),
      },
    });
    return { accessToken, refreshToken: rawRefresh };
  }

  // ── Forgot password ──────────────────────────────────────────────────

  /** If the email exists, generate a single-use reset token + email it.
   *  Always returns the same generic response (no user enumeration). */
  async forgotPassword(email: string): Promise<{ ok: true; devResetToken?: string }> {
    const user = await this.prisma.user.findFirst({ where: { email: email.toLowerCase(), deletedAt: null } });
    if (!user) return { ok: true }; // generic — don't reveal existence

    const rawToken = generateToken();
    await this.prisma.user.update({
      where: { id: user.id },
      data: {
        passwordResetTokenHash: hashToken(rawToken),
        passwordResetExpires: expiryFromNow(RESET_TTL_MINUTES),
      },
    });
    await this.audit.log({ action: 'auth.password.reset_requested', actorId: user.id, actorRole: user.activeRole, success: true });

    // Email is sent by the controller (which has the MailerService). In dev we
    // surface the token so the flow is testable without an email provider.
    return { ok: true, devResetToken: process.env.NODE_ENV === 'production' ? undefined : rawToken };
  }

  /** Consume a reset token + set a new password. Single-use: the hash is
   *  cleared on success. Validates the new password against the policy. */
  async resetPassword(token: string, newPassword: string, confirm: string) {
    if (newPassword !== confirm) throw new BadRequestException('Passwords do not match.');
    const violations = validatePassword(newPassword);
    if (violations.length) throw new BadRequestException(violations.join(' '));

    const user = await this.findUserByResetToken(token);
    if (!user) throw new BadRequestException('This reset link is invalid or has expired.');

    const hash = await bcrypt.hash(newPassword, 12);
    await this.prisma.user.update({
      where: { id: user.id },
      data: { passwordHash: hash, passwordResetTokenHash: null, passwordResetExpires: null },
    });
    // Revoke all refresh tokens — forces a fresh login everywhere.
    await this.prisma.refreshToken.updateMany({
      where: { userId: user.id, revokedAt: null },
      data: { revokedAt: new Date() },
    });
    await this.audit.log({ action: 'auth.password.reset_completed', actorId: user.id, actorRole: user.activeRole, success: true });
    return { ok: true };
  }

  private async findUserByResetToken(token: string) {
    const tokenHash = hashToken(token);
    const user = await this.prisma.user.findFirst({
      where: { passwordResetTokenHash: tokenHash, deletedAt: null },
    });
    if (!user) return null;
    if (!user.passwordResetExpires || user.passwordResetExpires < new Date()) return null;
    return user;
  }

  // ── Invitation: validate + set-password ──────────────────────────────

  /** Validate an invite token WITHOUT consuming it (for the set-password page).
   *  Returns the user's name + email so the page can render a personalised
   *  greeting. Never returns the user id. */
  async validateInvite(token: string): Promise<{ valid: true; email: string; name: string } | { valid: false; reason: 'expired' | 'invalid' | 'used' | 'revoked' }> {
    const invitation = await this.findInvitation(token);
    if (!invitation) return { valid: false, reason: 'invalid' };
    if (invitation.revokedAt) return { valid: false, reason: 'revoked' };
    if (invitation.acceptedAt) return { valid: false, reason: 'used' };
    if (invitation.expiresAt < new Date()) return { valid: false, reason: 'expired' };
    return { valid: true, email: invitation.user.email, name: invitation.user.name };
  }

  /** Consume an invite token + set the user's first password + activate.
   *  Single-use: marks the invitation accepted. */
  async setPassword(token: string, newPassword: string, confirm: string) {
    if (newPassword !== confirm) throw new BadRequestException('Passwords do not match.');
    const invitation = await this.findInvitation(token);
    if (!invitation) throw new BadRequestException('This invitation link is invalid.');
    if (invitation.revokedAt) throw new BadRequestException('This invitation has been revoked.');
    if (invitation.acceptedAt) throw new BadRequestException('This invitation has already been used.');
    if (invitation.expiresAt < new Date()) throw new BadRequestException('This invitation has expired.');

    const violations = validatePassword(newPassword, invitation.user.email);
    if (violations.length) throw new BadRequestException(violations.join(' '));

    const hash = await bcrypt.hash(newPassword, 12);
    await this.prisma.$transaction([
      this.prisma.user.update({
        where: { id: invitation.userId },
        data: { passwordHash: hash, passwordSetAt: new Date(), status: 'active', isActive: true },
      }),
      this.prisma.userInvitation.update({
        where: { id: invitation.id },
        data: { acceptedAt: new Date() },
      }),
    ]);
    await this.audit.log({ action: 'auth.password.set', actorId: invitation.userId, actorRole: invitation.user.activeRole, success: true });
    return { ok: true };
  }

  private async findInvitation(token: string) {
    const tokenHash = hashToken(token);
    return this.prisma.userInvitation.findFirst({
      where: { tokenHash },
      include: { user: true },
    });
  }
}
