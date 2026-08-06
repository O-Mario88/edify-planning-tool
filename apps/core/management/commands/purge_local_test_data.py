"""
Purge local test data — removes only records tagged source=local_test_upload.

Usage:
  python manage.py purge_local_test_data            # asks for confirmation
  python manage.py purge_local_test_data --yes      # skip confirmation

Removes local-test operational records (schools, SSA, activities, clusters,
partners, projects, debriefs, evidence, budgets, fund requests, notifications,
messages) WITHOUT touching reference data (permissions, roles, geography) or
production-upload records (source != local_test_upload).

DEV-ONLY: refuses to run in production.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.models import DataSource

# Operational models that carry the `source` field (SourcedModel descendants).
# Reference tables (geography, RBAC, audit, domain event log) are NOT here.
OPERATIONAL_MODELS = [
    "apps.schools.models.School",
    "apps.ssa.models.SsaRecord",
    "apps.activities.models.Activity",
    "apps.clusters.models.Cluster",
    "apps.partners.models.Partner",
    "apps.projects.models.Project",
    "apps.debriefs.models.DailyDebrief",
    "apps.fund_requests.models.FundRequest",
    "apps.monthly_work_plan.models.MonthlyWorkPlanBudget",
    "apps.evidence.models.EvidenceRecord",
    "apps.notifications.models.Notification",
    "apps.messaging.models.Message",
]


def _load(path):
    module, attr = path.rsplit(".", 1)
    mod = __import__(module, fromlist=[attr])
    return getattr(mod, attr)


class Command(BaseCommand):
    help = "Purge local test data (source=local_test_upload) from the local database. Dev-only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes", action="store_true", help="Skip the confirmation prompt."
        )

    def handle(self, *args, **options):
        if settings.IS_PRODUCTION:
            raise CommandError(
                "purge_local_test_data refuses to run in production. It deletes "
                "local test records only — never run it against a production database."
            )

        # Count first so the summary is honest + the confirmation is informed.
        # Only models that actually carry the `source` field are purgeable.
        counts = {}
        for path in OPERATIONAL_MODELS:
            try:
                model = _load(path)
                if "source" not in {f.name for f in model._meta.get_fields()}:
                    continue
                counts[path] = model.objects.filter(
                    source=DataSource.LOCAL_TEST_UPLOAD.value
                ).count()
            except Exception:  # noqa: BLE001 — model/app may not be installed
                continue
        total = sum(counts.values())

        if total == 0:
            self.stdout.write(
                self.style.SUCCESS(
                    "No local test records (source=local_test_upload) found. Nothing to purge."
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(f"Found {total} local test records to purge:")
        )
        for path, n in counts.items():
            if n:
                self.stdout.write(f"  {path.rsplit('.',1)[-1]}: {n}")

        if not options["yes"]:
            confirm = input(
                "\nType 'purge' to delete these local test records (reference/production data is safe): "
            )
            if confirm.strip().lower() != "purge":
                self.stdout.write("Aborted.")
                return

        deleted = 0
        for path in counts:
            try:
                model = _load(path)
                qs = model.objects.filter(source=DataSource.LOCAL_TEST_UPLOAD.value)
                qs.delete()
                deleted += counts[path]
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(f"  could not purge {path}: {exc}")
        self.stdout.write(
            self.style.SUCCESS(
                f"Purged {deleted} local test records. Reference + production data untouched."
            )
        )
