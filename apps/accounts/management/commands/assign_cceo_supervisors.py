"""Apply CCEO → Program Lead reporting lines from a mapping file.

A CCEO with no supervising Program Lead is invisible to team oversight and
falls into the country page's "Unassigned" group, so their work belongs to no
team. The fix is a reporting line, and a reporting line is organisational
truth: it cannot be derived from school geography, portfolio size or anything
else in the database without inventing an org chart. This command therefore
applies a mapping somebody supplies rather than guessing at one.

Every write goes through `accounts.supervisor_service.assign_supervisor`, so
the role-level rule (a PL supervises a CCEO) is enforced and the change is
audited exactly as it would be from the Users page. This command is a bulk
front door to that path, not a second way of writing the link.

    manage.py assign_cceo_supervisors --mapping lines.csv           # dry run
    manage.py assign_cceo_supervisors --mapping lines.csv --apply

The file is CSV with a header, two columns, emails:

    cceo_email,program_lead_email
    alex.luyima@edify.org,jane.pl@edify.org
"""

from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Apply CCEO → Program Lead reporting lines from a CSV mapping."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mapping",
            required=True,
            help="CSV with header cceo_email,program_lead_email",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the links. Without it the command only reports.",
        )
        parser.add_argument(
            "--actor",
            default="",
            help="Email of the Admin performing this, for the audit trail.",
        )

    def handle(self, *args, **options):
        from apps.accounts.models import User
        from apps.accounts.supervisor_service import assign_supervisor
        from apps.core.rbac import EdifyRole

        path = Path(options["mapping"])
        if not path.exists():
            raise CommandError(f"Mapping file not found: {path}")

        actor = None
        if options.get("actor"):
            actor = User.objects.filter(email=options["actor"]).first()
            if actor is None:
                raise CommandError(f"No user with email {options['actor']}")
        if actor is None:
            actor = (
                User.objects.filter(active_role=EdifyRole.ADMIN.value, is_active=True)
                .order_by("created_at")
                .first()
            )
        if actor is None:
            raise CommandError(
                "No Admin account to attribute these changes to. A reporting "
                "line written by nobody is not auditable."
            )

        planned, problems = [], []
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                cceo_email = (row.get("cceo_email") or "").strip().lower()
                pl_email = (row.get("program_lead_email") or "").strip().lower()
                if not cceo_email or not pl_email:
                    problems.append((cceo_email or "?", "row is missing an email"))
                    continue

                cceo = self._profile_for(cceo_email)
                lead = self._profile_for(pl_email)
                if cceo is None:
                    problems.append((cceo_email, "no staff profile with this email"))
                    continue
                if lead is None:
                    problems.append((pl_email, "no staff profile with this email"))
                    continue
                if getattr(lead.user, "active_role", "") != (
                    EdifyRole.COUNTRY_PROGRAM_LEAD.value
                ):
                    problems.append(
                        (
                            pl_email,
                            f"is a {getattr(lead.user, 'active_role', 'unknown')}, "
                            "not a Program Lead",
                        )
                    )
                    continue
                planned.append((cceo, lead))

        self.stdout.write("")
        self.stdout.write(f"Reporting lines to set: {len(planned)}")
        for cceo, lead in planned[:40]:
            self.stdout.write(
                f"   {getattr(cceo.user, 'name', ''):<24} → {getattr(lead.user, 'name', '')}"
            )
        if problems:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(f"Rows refused: {len(problems)}"))
            for subject, reason in problems[:20]:
                self.stdout.write(f"   {subject}: {reason}")

        if not options.get("apply"):
            self.stdout.write("")
            self.stdout.write("Dry run — nothing written. Re-run with --apply.")
            return

        written = 0
        with transaction.atomic():
            for cceo, lead in planned:
                assign_supervisor(cceo.id, {"supervisorId": lead.id}, actor)
                written += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Set {written} reporting line(s), attributed to {actor.email}."
            )
        )
        if problems:
            self.stdout.write(
                f"{len(problems)} row(s) were refused and remain unset — see above."
            )

    @staticmethod
    def _profile_for(email: str):
        from apps.accounts.models import StaffProfile

        return (
            StaffProfile.objects.filter(
                user__email__iexact=email, deleted_at__isnull=True
            )
            .select_related("user")
            .first()
        )
