"""Classify historic planning records against the oversight invariants.

Reports rather than repairs by default, and classifies every finding as one of:

    valid                   — nothing to do
    repairable              — a command can fix it without a judgement call
    manual review required  — a human has to decide

The distinction matters because the two repairable classes have very different
risk. Linking a partner assignment to the activity it became is mechanical.
Deciding who supervises a member of staff is not, and a command that guessed
would put real work under the wrong Program Lead's accountability.

    manage.py audit_planning_oversight              # report only
    manage.py audit_planning_oversight --repair     # apply the mechanical fixes
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = "Audit historic planning records against the oversight invariants."

    def add_arguments(self, parser):
        parser.add_argument(
            "--repair",
            action="store_true",
            help="Apply the mechanical repairs. Judgement calls are never applied.",
        )

    def handle(self, *args, **options):
        from apps.system_health.planning_oversight_health import report

        findings = report()

        self.stdout.write("")
        self.stdout.write("PLANNING OVERSIGHT — HISTORICAL DATA AUDIT")
        self.stdout.write("=" * 60)

        repairable_total = 0
        manual_total = 0

        for check in findings["checks"]:
            classification = self._classify(check)
            if check["count"] == 0:
                self.stdout.write(
                    self.style.SUCCESS(f"  valid                   {check['label']}")
                )
                continue

            if classification == "repairable":
                repairable_total += check["count"]
                style = self.style.WARNING
            else:
                manual_total += check["count"]
                style = self.style.ERROR

            self.stdout.write(
                style(f"  {classification:<23} {check['label']}: {check['count']}")
            )
            self.stdout.write(f"      expected: {check['expected']}")
            for example in check["examples"][:5]:
                detail = example.get("actual", "")
                subject = (
                    example.get("staff")
                    or example.get("school")
                    or example.get("partner")
                    or example.get("id")
                )
                self.stdout.write(f"      - {subject}: {detail}")
            self.stdout.write(f"      resolve: {check['route']}")

        self.stdout.write("")
        self.stdout.write(f"Repairable by command:   {repairable_total}")
        self.stdout.write(f"Manual review required:  {manual_total}")

        if not options.get("repair"):
            self.stdout.write("")
            self.stdout.write("Report only — nothing written. Re-run with --repair.")
            return

        self.stdout.write("")
        self.stdout.write("Applying mechanical repairs…")
        # The only mechanical one: pairing a scheduled assignment with the
        # activity it became, and even that refuses ambiguous cases.
        call_command("repair_partner_assignment_links", "--apply")
        self.stdout.write(
            self.style.SUCCESS(
                "Done. Everything classified as manual review is untouched by design."
            )
        )

    @staticmethod
    def _classify(check) -> str:
        """Whether a command can settle this without a judgement call."""
        mechanical = {"assignment_missing_scheduled_activity"}
        return "repairable" if check["key"] in mechanical else "manual review required"
