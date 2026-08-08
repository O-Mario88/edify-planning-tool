"""Read the current data against the portfolio-ownership rules.

Read-only. There is no --apply, and that is deliberate: every finding this
surfaces is either a decision somebody has to make or is fixed by an existing
targeted command. A blanket "repair everything" here would write guessed owners
into the field that decides who may touch a record.

  python manage.py audit_portfolio_ownership
  python manage.py audit_portfolio_ownership --examples   # show sample rows
  python manage.py audit_portfolio_ownership --key cluster_without_owner
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.clusters.portfolio_audit import REPAIRABLE, report


class Command(BaseCommand):
    help = "Audit school and cluster ownership against the portfolio rules."

    def add_arguments(self, parser):
        parser.add_argument(
            "--examples",
            action="store_true",
            help="Print sample rows for each finding.",
        )
        parser.add_argument(
            "--key",
            default="",
            help="Show only one check, by key.",
        )

    def handle(self, *args, **options):
        data = report()
        checks = data["checks"]
        if options["key"]:
            checks = [c for c in checks if c["key"] == options["key"]]
            if not checks:
                self.stdout.write(self.style.ERROR("No check with that key."))
                return

        if data["clean"]:
            self.stdout.write(self.style.SUCCESS("Portfolio ownership is clean."))
            return

        self.stdout.write(
            f"{data['issueCount']} issue(s): "
            f"{data['repairable']} repairable, {data['manual']} needing a decision.\n"
        )

        for check in checks:
            if check["clean"]:
                self.stdout.write(self.style.SUCCESS(f"  OK    {check['label']}"))
                continue
            style = (
                self.style.ERROR if check["severity"] == "high" else self.style.WARNING
            )
            tag = "REPAIR" if check["classification"] == REPAIRABLE else "DECIDE"
            self.stdout.write(
                style(f"  {tag:6s} {check['count']:>6}  {check['label']}")
            )
            self.stdout.write(f"         expected: {check['expected']}")
            if options["examples"]:
                for row in check["examples"][:5]:
                    subject = row.get("school") or row.get("cluster") or "—"
                    self.stdout.write(f"           {subject}: {row.get('actual', '')}")
                    self.stdout.write(f"             → {row.get('resolution', '')}")

        self.stdout.write("")
        self.stdout.write(
            "Nothing was written. Findings marked REPAIR have one unambiguous "
            "answer in the data;\nthose marked DECIDE do not, and guessing an "
            "owner is the one thing this must never do."
        )
        if any(c["key"] == "cluster_without_owner" and not c["clean"] for c in checks):
            self.stdout.write(
                "\nFor cluster owners specifically: "
                "python manage.py list_ownerless_clusters --suggest"
            )
