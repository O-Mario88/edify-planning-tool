"""
Management command: account_access

Report — and optionally repair — everything that can stop an account signing
in, from a shell rather than from the interface.

Why this exists: every remedy for a blocked sign-in lived behind a sign-in. An
escalated lockout is cleared at /admin-panel/users/<id>, which requires an
authenticated Admin — so when the only Admin is the locked account, the one
person who can lift the lock is the person it is applied to. The same is true
of a disabled status or a stale forced-password-change flag. Support for that
situation was "redeploy with RUN_SEED=true", which reset the password and left
the lockout in place: new credentials against a door still bolted.

Read-only by default. It prints the account's state and names the specific
thing blocking sign-in; nothing changes unless a repair flag is passed.

Usage:
    python manage.py account_access someone@edify.org
    python manage.py account_access someone@edify.org --unlock
    python manage.py account_access someone@edify.org --unlock --clear-password-change
    python manage.py account_access someone@edify.org --activate

Deliberately NOT a password reset. Anyone who can run this can already reset a
password through the documented environment-variable path, and a command that
sets credentials invites being pasted into a shared terminal with the password
in the shell history.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Report and optionally clear whatever is blocking an account's sign-in."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email address of the account.")
        parser.add_argument(
            "--unlock",
            action="store_true",
            help="Clear lockout state (timed and escalated) and reset the failure counters.",
        )
        parser.add_argument(
            "--clear-password-change",
            action="store_true",
            help="Clear must_change_password, so sign-in does not divert to the change-password funnel.",
        )
        parser.add_argument(
            "--activate",
            action="store_true",
            help="Set status=active and is_active=True. Does not undelete a soft-deleted account.",
        )

    def handle(self, *args, **options):
        from apps.accounts.models import User

        email = options["email"].strip().lower()
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            raise CommandError(f"No account with email {email!r}.")

        self._report(user)

        changed = []
        if options["unlock"]:
            user.locked_until = None
            user.lockout_escalated = False
            user.lockout_cycle_count = 0
            user.failed_login_count = 0
            user.failed_login_streak_started_at = None
            changed += [
                "locked_until",
                "lockout_escalated",
                "lockout_cycle_count",
                "failed_login_count",
                "failed_login_streak_started_at",
            ]
        if options["clear_password_change"]:
            user.must_change_password = False
            changed.append("must_change_password")
        if options["activate"]:
            user.status = "active"
            user.is_active = True
            changed += ["status", "is_active"]

        if not changed:
            self.stdout.write(
                "\nNo changes requested. Re-run with --unlock / --activate / "
                "--clear-password-change to repair."
            )
            return

        user.save(update_fields=changed)

        # An out-of-band change to who can sign in is exactly the kind of thing
        # that must leave a trace, precisely because it was made without one.
        try:
            from apps.audit.services import log as audit_log

            audit_log(
                action="auth.access_repaired_via_cli",
                subject_kind="user",
                subject_id=user.id,
                actor_id=None,
                actor_role=None,
                success=True,
                reason="Sign-in blockers cleared from the command line.",
                payload={"fields": changed},
            )
        except Exception:  # noqa: BLE001 — the repair matters more than its record
            self.stdout.write(
                self.style.WARNING("  (audit row could not be written)")
            )

        self.stdout.write(self.style.SUCCESS(f"\nUpdated: {', '.join(changed)}"))
        self.stdout.write("Re-checked state:")
        user.refresh_from_db()
        self._report(user)

    def _report(self, user) -> None:
        from django.conf import settings

        blockers = []
        if user.deleted_at:
            blockers.append("account is soft-deleted (this command will not undo that)")
        if not user.is_active:
            blockers.append("is_active=False")
        if user.status != "active":
            blockers.append(f"status={user.status!r} (only 'active' may sign in)")
        if user.lockout_escalated:
            blockers.append("lockout_escalated=True — needs --unlock")
        elif user.locked_until and user.locked_until > timezone.now():
            remaining = int((user.locked_until - timezone.now()).total_seconds() // 60)
            blockers.append(f"locked for another {remaining} min — --unlock clears it")
        if not user.password:
            blockers.append("no password set (invited but never accepted)")

        mfa_on = getattr(settings, "MFA_REQUIRED_FOR_ALL", False) or user.mfa_enabled
        if mfa_on:
            blockers.append(
                "two-step verification is on — the code is emailed, so it also "
                "needs a working mail provider (RESEND_API_KEY)"
            )

        self.stdout.write(f"\n{user.email}  ({user.name})")
        self.stdout.write(f"  roles            : {user.roles}  active: {user.active_role}")
        self.stdout.write(f"  status           : {user.status}   is_active: {user.is_active}")
        self.stdout.write(f"  locked_until     : {user.locked_until}")
        self.stdout.write(f"  lockout_escalated: {user.lockout_escalated}")
        self.stdout.write(f"  failed_login_cnt : {user.failed_login_count}")
        self.stdout.write(f"  must_change_pwd  : {user.must_change_password}")
        self.stdout.write(f"  mfa_enabled      : {user.mfa_enabled}")
        self.stdout.write(f"  password_set_at  : {user.password_set_at}")

        if blockers:
            self.stdout.write(self.style.ERROR("  BLOCKING SIGN-IN:"))
            for b in blockers:
                self.stdout.write(self.style.ERROR(f"    - {b}"))
        else:
            self.stdout.write(
                self.style.SUCCESS("  Nothing on this account blocks sign-in.")
            )
