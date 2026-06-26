import { Injectable, Logger } from '@nestjs/common';

// Email delivery for auth flows (invitations, password resets).
//
// Two modes:
//   • dev (default / EMAIL_PROVIDER unset) — logs the link to the console AND
//     the caller returns it in the API response so an admin can copy it into
//     the browser. No external dependency. Safe for local + docker-compose.
//   • production (EMAIL_PROVIDER=resend + RESEND_API_KEY) — sends via Resend.
//
// Rule: NEVER include a password in any email. Only links + context. Reset +
// invite links carry a one-time token; the email contains only that link.

export type MailMessage = {
  to: string;
  subject: string;
  /** Plain-text body. */
  text: string;
  /** Optional HTML body. */
  html?: string;
};

@Injectable()
export class MailerService {
  private readonly log = new Logger('Mailer');

  /** The app's public base URL, used to build absolute invite/reset links. */
  private get appBaseUrl(): string {
    return (process.env.APP_BASE_URL ?? 'http://localhost:3000').replace(/\/$/, '');
  }

  private get provider(): 'resend' | 'console' {
    return process.env.EMAIL_PROVIDER === 'resend' && process.env.RESEND_API_KEY ? 'resend' : 'console';
  }

  /** True when email delivery is actually wired (not the console stub). */
  get isConfigured(): boolean {
    return this.provider === 'resend';
  }

  /** Send a message. In console mode, logs instead of sending. */
  async send(msg: MailMessage): Promise<{ delivered: boolean; devPreview?: string }> {
    if (this.provider === 'resend') {
      return this.sendViaResend(msg);
    }
    // Console / dev — log the full message so a tester can complete the flow.
    this.log.log(`📧 [dev mail] To: ${msg.to} | Subject: ${msg.subject}\n${msg.text}`);
    return { delivered: false, devPreview: msg.text };
  }

  private async sendViaResend(msg: MailMessage): Promise<{ delivered: boolean }> {
    try {
      const res = await fetch('https://api.resend.com/emails', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${process.env.RESEND_API_KEY}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          from: process.env.EMAIL_FROM ?? 'Edify Planning <noreply@edify.org>',
          to: msg.to,
          subject: msg.subject,
          text: msg.text,
          ...(msg.html ? { html: msg.html } : {}),
        }),
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => res.statusText);
        this.log.error(`Resend delivery failed (${res.status}): ${detail}`);
        return { delivered: false };
      }
      return { delivered: true };
    } catch (e) {
      this.log.error(`Resend delivery error: ${(e as Error).message}`);
      return { delivered: false };
    }
  }

  // ── Templates ────────────────────────────────────────────────────────

  /** Invitation email — the new-user set-password link. */
  async sendInvitation(args: { to: string; name: string; invitedByName: string; token: string }): Promise<{ delivered: boolean; devPreview?: string }> {
    const link = `${this.appBaseUrl}/set-password?token=${args.token}`;
    const subject = 'You have been invited to Edify Planning and Monitoring Tool';
    const text = [
      `Hello ${args.name},`,
      '',
      `${args.invitedByName} has invited you to join the Edify Planning and Monitoring Tool.`,
      '',
      'To activate your account, set your password by opening this link:',
      link,
      '',
      'This invitation expires in 7 days and can only be used once.',
      '',
      'If you did not expect this invitation, you can safely ignore this email.',
      '',
      '— Edify Planning and Monitoring Tool',
    ].join('\n');
    return this.send({ to: args.to, subject, text });
  }

  /** Password-reset email — the forgot-password reset link. */
  async sendPasswordReset(args: { to: string; name: string; token: string }): Promise<{ delivered: boolean; devPreview?: string }> {
    const link = `${this.appBaseUrl}/reset-password?token=${args.token}`;
    const subject = 'Reset your Edify Planning password';
    const text = [
      `Hello ${args.name},`,
      '',
      'We received a request to reset your password. You can set a new one here:',
      link,
      '',
      'This link expires in 45 minutes and can only be used once.',
      '',
      'If you did not request a password reset, you can safely ignore this email.',
      '',
      '— Edify Planning and Monitoring Tool',
    ].join('\n');
    return this.send({ to: args.to, subject, text });
  }
}
