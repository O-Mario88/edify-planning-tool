"""
Local-only SSA import from CSV.

Usage:
  python manage.py import_ssa_local path/to/ssa.csv

CSV columns:
  schoolId, dateOfSsa, teaching_and_learning, financial_health,
  christlike_behaviour, exposure_to_word_of_god, government_requirements,
  leadership, education_technology, learning_environment,
  newEnrollment (optional), collectorType (optional, default staff)

Creates SsaRecord + 8 SsaScore rows, derives FY/quarter from the date, and
recomputes the school's planning readiness. Tagged source=local_test_upload.

DEV-ONLY: refuses in production.
"""
from __future__ import annotations

import csv
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.models import DataEnvironment, DataSource
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore
from apps.ssa.services import _recompute_readiness


INTERVENTIONS = [i.value for i in SsaIntervention]


class Command(BaseCommand):
    help = "Import SSA records into the LOCAL database from a CSV file (dev-only)."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the SSA CSV file.")
        parser.add_argument("--env-tag", default="local")

    def handle(self, *args, **options):
        if settings.IS_PRODUCTION:
            raise CommandError(
                "import_ssa_local refuses to run in production. Real data is "
                "uploaded through the backend API / admin after deployment."
            )
        csv_path = options["csv_path"]
        env_tag = options["env_tag"]
        source = DataSource.LOCAL_TEST_UPLOAD.value if env_tag == "local" else DataSource.PRODUCTION_UPLOAD.value
        created = skipped = 0

        try:
            with open(csv_path, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    try:
                        school = School.objects.filter(school_id=row["schoolId"].strip()).first()
                        if not school:
                            skipped += 1
                            self.stderr.write(f"  skip {row.get('schoolId')}: school not in directory")
                            continue
                        date = datetime.fromisoformat(row["dateOfSsa"].strip())
                        scores = []
                        for interv in INTERVENTIONS:
                            raw = row.get(interv)
                            if raw is None or str(raw).strip() == "":
                                raise ValueError(f"missing score for {interv}")
                            scores.append((interv, float(raw)))
                        if len(scores) != 8:
                            raise ValueError("all 8 intervention scores are required")
                        avg = round(sum(s for _, s in scores) / 8, 1)
                        collector = row.get("collectorType", "staff").strip() or "staff"
                        partner_collected = collector == "partner"
                        record = SsaRecord.objects.create(
                            school=school, date_of_ssa=date, fy=get_operational_fy(date),
                            quarter=get_quarter_for_date(date),
                            new_enrollment=int(row["newEnrollment"]) if row.get("newEnrollment") else None,
                            average_score=avg, uploaded_by="local_import",
                            collector_type=collector,
                            verification_status="pending" if partner_collected else "confirmed",
                            verification_source="partner_submitted" if partner_collected else "staff_self_verified",
                            source=source, environment=env_tag,
                        )
                        if not partner_collected:
                            record.verified_by_user_id = "local_import"
                            record.verified_at = timezone.now()
                            record.save(update_fields=["verified_by_user_id", "verified_at"])
                        SsaScore.objects.bulk_create(
                            [SsaScore(ssa_record=record, intervention=interv, score=score) for interv, score in scores]
                        )
                        if record.verification_status == "confirmed":
                            school.current_fy_ssa_status = "done"
                            school.save(update_fields=["current_fy_ssa_status"])
                        _recompute_readiness(school)
                        created += 1
                    except Exception as exc:  # noqa: BLE001
                        skipped += 1
                        self.stderr.write(f"  skip {row.get('schoolId')}: {exc}")
        except FileNotFoundError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(
            f"Imported {created} SSA records (skipped={skipped}). source={source}."
        ))
