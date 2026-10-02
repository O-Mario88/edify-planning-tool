"""
Management command: reconcile_school_holders

Find — and optionally remove — portfolio assignments that name somebody other
than a school's holder.

``School.account_owner_id`` is the holder. ``StaffSchoolAssignment`` is the
same fact as the scoping chain reads it: a person's schools, and through the
reporting line their Programme Lead's team schools. Four paths that named a
new holder (the school upload, the directory's match and bulk match, staff
setup) added the new holder's row and left the previous holder's, so a school
could sit in two people's scope while every list filed it under one. Those
paths now replace the row (`apps.schools.ownership_transfer.hold_schools`);
this repairs what they left behind.

The repair is to make the assignment say what the school record says: remove
the rows naming anyone but the holder, and add the holder's row where it is
missing. A school with no holder, or a holder that resolves to no staff
profile, is left exactly as it is — there is nothing to reconcile it to.

Idempotent, and read-only unless --apply is passed. The deploy runs the same
repair once as schools migration 0023 (`apps.schools.holder_reconcile` is the
one piece of logic both use); this stays for a dry run and for any drift a
future path leaves.

Usage:
    python manage.py reconcile_school_holders              # report only
    python manage.py reconcile_school_holders --list       # and every row
    python manage.py reconcile_school_holders --apply
"""

from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = (
        "Report or remove portfolio assignments that disagree with a school's holder."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Make the assignments match. Without this the command only reports.",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="Print every row that would change, one line each.",
        )

    def handle(self, *args, **options):
        from apps.accounts.models import StaffProfile, StaffSchoolAssignment
        from apps.schools.holder_reconcile import (
            apply_holder_repair,
            plan_holder_repair,
        )
        from apps.schools.models import School

        plan = plan_holder_repair(School, StaffProfile, StaffSchoolAssignment)
        self.stdout.write(f"Schools with a holder: {plan.schools_with_holder}")
        self.stdout.write(
            f"Also assigned to somebody else: {plan.schools_also_assigned_elsewhere}"
        )
        self.stdout.write(f"Holder's own assignment missing: {len(plan.missing)}")
        self.stdout.write(
            f"Holder resolves to no staff profile (left alone): {plan.unresolved}"
        )
        per_holder = Counter(plan.holder_of.values())
        for holder, count in per_holder.most_common(20):
            self.stdout.write(
                f"  {plan.staff_names.get(holder, holder)}: {count} schools"
            )
        if options["list"] or options["apply"]:
            for line in plan.lines():
                self.stdout.write(f"  {line}")

        if not plan:
            self.stdout.write(self.style.SUCCESS("Nothing to reconcile."))
            return
        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING("Report only. Re-run with --apply to reconcile.")
            )
            return

        with transaction.atomic():
            apply_holder_repair(plan, StaffSchoolAssignment)
        self.stdout.write(
            self.style.SUCCESS(f"Reconciled {plan.schools_changed} schools.")
        )
