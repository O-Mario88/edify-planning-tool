# Authentication Lockout Policy

Resolves the audit finding (Issue 3): **three login surfaces enforced login
lockout differently, and one — Django's own `/admin/login/` — enforced no
lockout at all.**

## The three systems this replaces

Before this fix:

1. **Web session login** (`apps/frontend/views/auth_views.py::login_view`)
   hand-rolled its own failed-count/lock logic directly on the `User` row,
   including setting `locked_until` to a ~100-year-out timestamp as a
   "permanent lock" convention on the Nth failure.
2. **DRF API login** (`apps.accounts.auth_services.login`) hand-rolled a
   *second*, independently-written version of the same idea, with different
   fallback constants (`AUTH_MAX_FAILED_LOGINS` defaulted to 5 here vs. 10 on
   the web path) — so the same account could be locked on one surface and
   not the other after an identical sequence of attempts.
3. **Django admin login** (`/admin/login/`) went through plain
   `django.contrib.auth.backends.ModelBackend`, which only checks the
   password and `is_active` — no lockout logic at all. An attacker (or a
   locked-out legitimate user) could always try again via `/admin/login/`
   regardless of how many times they'd failed on the other two surfaces.

## The fix: one backend, one service

`AUTHENTICATION_BACKENDS` (see `config/settings/base.py`) now contains
exactly one entry:

```python
AUTHENTICATION_BACKENDS = [
    "apps.accounts.auth_backend.LockoutEnforcingModelBackend",
]
```

`LockoutEnforcingModelBackend` (`apps/accounts/auth_backend.py`) is a thin
wrapper: it resolves the user, checks lockout state, checks account
lifecycle status, and checks the password — recording the outcome via
`AuthenticationLockoutService` either way. Because this is a Django
*authentication backend*, not view code, **every** call to
`django.contrib.auth.authenticate()` enforces the same policy — including
calls this codebase doesn't own the view code for, like Django admin's
`AdminAuthenticationForm`.

All three surfaces now call `authenticate()` and nothing else:

- `apps/frontend/views/auth_views.py::login_view`
- `apps.accounts.auth_services.login` (the DRF `/api/auth/login` path)
- Django's built-in `/admin/login/` (unmodified — it already called
  `authenticate()`; it just picks up the new backend automatically)

The actual policy — thresholds, lock duration, escalation, audit, admin
notification — lives in exactly one place:
`apps/accounts/lockout_service.py::AuthenticationLockoutService`. No login
path may compute its own lockout logic; if a new login surface is ever
added, it must call `authenticate()`, not reimplement this.

## Policy (the "safer enterprise default")

Chosen over the two systems it replaces, which either locked permanently on
a single burst (the web path's 100-year-lock convention) or didn't lock
persistently at all in a way both surfaces agreed on:

1. **`AUTH_MAX_FAILED_LOGINS`** (default 10) consecutive failures trigger a
   **temporary** lock of **`AUTH_LOCKOUT_DURATION_MINUTES`** (default 15)
   that auto-expires. Never permanent from a single burst — an ordinary
   user who mistypes their password repeatedly is never one bad afternoon
   away from needing IT support.
2. If **`AUTH_LOCKOUT_ESCALATION_COUNT`** (default 3) separate lock cycles
   happen within **`AUTH_LOCKOUT_ESCALATION_WINDOW_HOURS`** (default 24) of
   each other, the account **escalates**: locked until an administrator
   explicitly unlocks it (`AUTH_REQUIRE_ADMIN_UNLOCK_AFTER_ESCALATION`,
   default `True`) — not on a timer. Repeated lockouts in a short window are
   a much stronger brute-force signal than one burst, and warrant a human
   look.
3. A failed-attempt streak older than
   **`AUTH_FAILED_LOGIN_RESET_WINDOW_MINUTES`** (default 30) doesn't count
   toward the threshold — matches "a successful login resets the counter"
   for someone who simply stopped attempting, rather than someone who got
   locked and is still trying.
4. All state changes are atomic (`select_for_update` inside
   `transaction.atomic`), so concurrent requests against the same account
   can never race past the threshold — see
   `test_concurrent_failed_attempts_do_not_bypass_threshold` in
   `apps/accounts/test_lockout_unification.py`.
5. Every escalation, admin unlock, and admin manual lock is audited
   (`apps.audit.services.log`) and an escalation additionally notifies every
   `ADMIN`-role user via `WorkflowNotificationService`.
6. No login path reveals whether an email address has an account —
   unknown-email and wrong-password responses are identical in status code
   and message on every surface (`test_unknown_email_does_not_leak_account_existence`).

## Admin actions

- **Unlock** (`AuthenticationLockoutService.admin_unlock`) clears failed
  count, temporary lock, cycle count, and escalation together — a partial
  unlock (e.g. only clearing `locked_until` while leaving
  `lockout_escalated=True`) would leave the account looking unlocked in the
  admin UI while still rejecting every login. The admin-panel "reset
  password" action delegates to this too, for the same reason (see
  `test_admin_password_reset_clears_escalation`).
- **Manual lock** (`AuthenticationLockoutService.admin_lock`) lets an admin
  immediately escalate-lock a suspected-compromised account without waiting
  for `AUTH_LOCKOUT_ESCALATION_COUNT` failed cycles.

## Legacy data: the pre-unification "permanent lock" convention

Rows written by the old web-login code path used
`locked_until = now + 100 years` to mean "permanent, requires admin
unlock" — a magic date rather than a real flag. Migration
`apps/accounts/migrations/0016_migrate_legacy_permanent_locks.py` converts
any such row (idempotently, on deploy) to the new
`lockout_escalated=True` convention, which the new code actually checks.

If a row using the old convention ever reappears after that migration has
run (e.g. a data import or fixture load written against the old shape), the
**System Health** page's "Authentication Lockout" → "Legacy Lock Records"
check (`apps/accounts/health.py::auth_lockout_health`) flags it, and
`python manage.py repair_legacy_lock_records` (optionally `--dry-run` first)
re-runs the same idempotent conversion on demand.

## System Health checks

Wired into `/system-health` under "Authentication Lockout"
(`apps/accounts/health.py::auth_lockout_health`):

| Check | Flags |
|---|---|
| `auth_backend_unified` | `AUTHENTICATION_BACKENDS` drifted from the single expected backend — some login path may be silently bypassing lockout. |
| `legacy_lock_records` | Any account still using the pre-Issue-3 far-future-`locked_until` convention. |
| `escalated_accounts_pending_unlock` | Operational visibility — accounts currently blocked pending an admin unlock (not itself a defect, just something that shouldn't sit unnoticed). |

## Tests

`apps/accounts/test_lockout_unification.py` — the dedicated Issue 3 suite
(13 required tests + 2 regression bonus tests covering the System Health
check and the admin-reset-clears-escalation fix). `apps/core/tests/test_admin_user_operations.py`
covers the admin-panel UI-level flows (lock/unlock/reset through the actual
HTML forms).
