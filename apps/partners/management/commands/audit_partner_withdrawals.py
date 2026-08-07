"""Classify historic partner-assignment data against the withdrawal invariants.

Reports rather than repairs by default, and classifies every finding as one of:

    valid                   — nothing to do
    repairable              — a command can fix it without a judgement call
    manual review required  — a human has to decide

The distinction is the point. Cancelling an activity whose assignment was
withdrawn is mechanical: the assignment already says the work stopped, and the
activity disagreeing with it is a bug. Deciding which of two partners holding
one support slot is the real one is not — one of them may have already done
the work, and picking wrong loses somebody's delivery.

    manage.py audit_partner_withdrawals              # report only
    manage.py audit_partner_withdrawals --repair     # apply mechanical fixes
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

#: Findings a command can settle without deciding anything.
MECHANICAL = {"withdrawn_work_still_executable"}


class Command(BaseCommand):
    help = "Audit partner-assignment data against the withdrawal invariants."

    def add_arguments(self, parser):
        parser.add_argument(
            "--repair",
            action="store_true",
            help="Apply the mechanical repairs. Judgement calls are never applied.",
        )

    def handle(self, *args, **options):
        from apps.system_health.planning_oversight_health import report

        findings = report()
        withdrawal_keys = {
            "withdrawn_work_still_executable",
            "duplicate_support_slot_holders",
            "replacement_inherited_cost",
            "locked_withdrawal_without_amendment",
            "withdrawal_attribution_mismatch",
        }
        checks = [c for c in findings["checks"] if c["key"] in withdrawal_keys]

        self.stdout.write("")
        self.stdout.write("PARTNER WITHDRAWAL — HISTORICAL DATA AUDIT")
        self.stdout.write("=" * 60)

        repairable = manual = 0
        for check in checks:
            if check["count"] == 0:
                self.stdout.write(
                    self.style.SUCCESS(f"  valid                   {check['label']}")
                )
                continue

            mechanical = check["key"] in MECHANICAL
            label = "repairable" if mechanical else "manual review required"
            style = self.style.WARNING if mechanical else self.style.ERROR
            if mechanical:
                repairable += check["count"]
            else:
                manual += check["count"]

            self.stdout.write(
                style(f"  {label:<23} {check['label']}: {check['count']}")
            )
            self.stdout.write(f"      expected: {check['expected']}")
            for example in check["examples"][:5]:
                subject = (
                    example.get("school") or example.get("partner") or example.get("id")
                )
                self.stdout.write(f"      - {subject}: {example.get('actual', '')}")
            self.stdout.write(f"      resolve: {check['route']}")

        self.stdout.write("")
        self.stdout.write(f"Repairable by command:   {repairable}")
        self.stdout.write(f"Manual review required:  {manual}")

        if not options.get("repair"):
            self.stdout.write("")
            self.stdout.write("Report only — nothing written. Re-run with --repair.")
            return

        self.stdout.write("")
        self.stdout.write("Applying mechanical repairs…")
        fixed = self._cancel_orphaned_activities()
        self.stdout.write(
            self.style.SUCCESS(
                f"Cancelled {fixed} activity(s) whose assignment was already "
                "withdrawn. Everything classified as manual review is untouched "
                "by design."
            )
        )

    def _cancel_orphaned_activities(self) -> int:
        """Bring a withdrawn assignment's activity into line with the decision.

        Idempotent: an activity already cancelled is skipped, so running this
        twice does the work once. Uses the canonical cancellation so the
        budget unwinds the same way it would have at the time — a direct
        status update here would leave the money behind, which is the half of
        the bug that does not show up on the page.
        """
        from apps.activities import services as activity_services
        from apps.partners.withdrawal_models import (
            PartnerAssignmentWithdrawal,
            WithdrawalKind,
        )

        fixed = 0
        candidates = (
            PartnerAssignmentWithdrawal.objects.filter(
                kind__in=(
                    WithdrawalKind.WITHDRAW_UNSCHEDULED,
                    WithdrawalKind.RECALL_SCHEDULED,
                )
            )
            .exclude(linked_activity__isnull=True)
            .select_related("linked_activity")
        )
        for w in candidates:
            activity = w.linked_activity
            if activity is None or activity.status in (
                "cancelled",
                "deferred",
                "rejected",
            ):
                continue
            with transaction.atomic():
                activity_services._cancel_or_defer(
                    activity.id,
                    {
                        "reason": (
                            "Repair: assignment withdrawn "
                            f"{w.requested_at:%Y-%m-%d} but activity stayed live"
                        )
                    },
                    _system_principal(),
                    "cancelled",
                )
            fixed += 1
        return fixed


def _system_principal():
    """The actor on a repair nobody performed interactively.

    A real AuthPrincipal rather than a stub with the right-looking attributes:
    the cancellation path runs a scope check that reads `staff_profile_id`, and
    a duck-typed object missing it crashes the repair — which my first version
    did. `apps/realtime/jobs.py` already builds one this way for scheduled
    jobs, so this follows that rather than inventing a second convention.

    Named "system" so the audit trail says a repair command did this, not that
    an unidentified user cancelled somebody's activity.
    """
    from apps.accounts.jwt import AuthPrincipal

    class _SystemUser:
        user_id = "system"
        name = "Withdrawal audit repair"

    return AuthPrincipal(
        user=_SystemUser(),
        user_id="system:audit_partner_withdrawals",
        email="system@edify",
        name="Withdrawal audit repair",
        roles=["Admin"],
        active_role="Admin",
        staff_profile_id=None,
    )
