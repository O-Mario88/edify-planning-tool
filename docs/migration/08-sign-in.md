# 8. Sign-in, owned by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): "Implement all application operations in Go, including:
Authentication, login, logout and session management. Password security and
account recovery. Multi-factor authentication where supported." And, with the
app icon brief: "All authentication and user workflows must be handled by Go.
Python must have no responsibility for login."

This is the first piece of that brief. The app now signs in through the Go
gateway; nothing in the app talks to the Python application to sign in. This
replaces the plan in [02 §2.5](02-target-architecture.md#25-authentication)
to forward sign-in to the existing application.

## 8.1 What moved

`edify.identity.v1.SignInService` (`platform/proto/edify/identity/v1/sign_in.proto`),
served by `platform/backend/internal/signin`, without a session:

| Procedure | Existing rule it ports (apps/accounts/…) |
|---|---|
| `SignIn` | `auth_services.login`, `auth_backend`, `lockout_service`, `auth_failure_service` |
| `VerifySignInCode` | `auth_services.verify_mfa`, `mfa_service` (email, SMS, authenticator app) |
| `RefreshSession` | `auth_services.refresh` (rotation, reuse detection, family revocation) |
| `SignOut` | `auth_services.logout` |
| `RequestPasswordReset`, `ResetPassword` | `auth_services.forgot_password`, `reset_password` |
| `CheckInvitation`, `AcceptInvitation` | `auth_services.validate_invite`, `set_password` |
| `GetSignInFigures` | `frontend/views/auth_views._login_stats` |

Ported one for one, with the existing words:

- **Passwords** are checked in the existing formats (`bcrypt$…`, cost 12, and
  `pbkdf2_sha256$…`) and new ones are stored as `bcrypt$…`, so either system
  checks the other's. The policy is `validate_password`, message for message.
- **Lockout**: 10 failures lock for 15 minutes; a streak older than 30 minutes
  starts again; three locks within 24 hours need an administrator. Same
  columns, same `SELECT … FOR UPDATE`. The Admin security alert fires at the
  fifth failure, as on the web.
- **Every refusal reads the same** ("Invalid email or password."): unknown
  address, wrong password, locked, inactive. The real reason goes to the
  audit chain. A locked or unknown account still spends a password check, so
  timing does not tell them apart either.
- **Second factor**: required when enrolled or by `MFA_REQUIRED_FOR_ALL` /
  `MFA_REQUIRED_ROLES`; ten codes an hour per account; five attempts a code;
  ten minutes; one step of TOTP drift; codes and client tokens stored as
  hashes. The app has a code step now (before, an enrolled account was told
  to use the web), worded as the web's `mfa_verify.html`.
- **Sessions**: the same HS256 access token (15 minutes) and rotating refresh
  token (7 days, stored as a SHA-256 hash, in families). A spent token
  presented again revokes its whole family and is audited.
- **Rate limits** per address: sign-in and code 10 a minute, reset requests 4
  per 10 minutes (the existing throttles).
- **A successful sign-in is recorded** in `login_event` for the Staff Activity
  Log, with the existing device label. (The existing API sign-in did not
  record one; the web's did.)

## 8.2 What it writes, and how that is held

The gateway's role stays read-only by default. A sign-in write opens its own
read-write transaction and reaches only what `platform/deploy/db/identity_roles.sql`
grants role `edify_identity_rw`: the sign-in columns of `"user"` (lockout,
password, reset, activation — never roles, email, MFA enrolment or
superuser), `refresh_token`, `mfa_challenge`, `user_invitation.accepted_at`,
`staff_profile.onboarding_state`, `login_event`, and `INSERT` on
`audit_log` / `domain_event_log`. No `DELETE` anywhere, no `UPDATE` of an audit
row.

Proven against a real database (`internal/integration`):
`TestGatewayRoleCanNeitherWriteNorReadSecrets` now refuses changing an
account's roles, email, superuser flag or MFA enrolment, rewriting or deleting
audit rows, deleting sessions or accounts. The staging start-up guard
(`dbguard.VerifyIdentity`) now checks column grants too: a role that could
write any school column or an account's identity columns is refused.

**The audit chain** is one chain. Go appends under the existing advisory lock
(`EDIFYAUD`) with the existing canonical form and hash; the existing
`verify_chain(full=True)` over the test database, after the Go suite wrote
90 sign-in rows into it, answered `ok: True, checkedRows: 572`.

## 8.3 One session, either system

Checked on the development database (2026-11-11): a session Go opened was
accepted by the existing `/api/auth/me`; its refresh token was rotated by the
existing `/api/auth/refresh`; the token that rotation issued was rotated by Go;
and the spent Go token, presented again, was refused and ended the family
across both.

## 8.4 What has not moved yet

- **The web's own sign-in page** still signs in through the existing
  application. Today both systems write the same sign-in columns, under the
  same row locks and the same policy, on development and test databases only.
  This is not the end state: rule 3.7 is one writer per table. **Production
  cutover moves the web's sign-in to Go in the same release** (the web form
  calls `SignInService`), so the existing sign-in write path is switched off
  as Go's is switched on. That cutover needs the owner's approval.
- **Admin alerts** (the security incident at five failures, the escalation
  notice) are raised by the existing application's notifications, which Go
  calls server to server (`POST /api/auth/internal/security-events`, internal
  key), until notifications move to Go.
- Role switching, user creation, invitations, admin unlock and the account
  lifecycle moved to Go next: [09-accounts-and-roles.md](09-accounts-and-roles.md).
- **Configuration parity**: the gateway's `EDIFY_JWT_SECRET`,
  `EDIFY_FIELD_ENCRYPTION_KEY`, `EDIFY_MFA_REQUIRED_FOR_ALL` and
  `EDIFY_MFA_REQUIRED_ROLES` must equal the existing application's
  `JWT_SECRET`, `FIELD_ENCRYPTION_KEY`, `MFA_REQUIRED_FOR_ALL` and
  `MFA_REQUIRED_ROLES` in the same environment. The lockout and token
  lifetimes are the existing defaults, fixed in `signin.DefaultPolicy`.
- A rate-limit window is per gateway process; several gateway instances need
  a shared store (Redis) for one limit.
