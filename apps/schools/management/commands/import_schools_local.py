"""
Local-only school import from CSV.

Usage:
  python manage.py import_schools_local path/to/schools.csv

Creates School records from a CSV with columns (any subset works; the required
ones are schoolId, name, region, district):
  schoolId, name, region, district, subCounty, parish, schoolType, enrollment,
  schoolPhone, primaryContactName, primaryContactPhone, shippingAddress

Records are tagged source=local_test_upload so purge_local_test_data can remove
them without touching real production data.

DEV-ONLY: refuses to run when DEBUG=False / in production. Production receives
real data through the normal API upload / admin workflows, never this command.
"""
from __future__ import annotations

import csv

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.enums import SchoolType
from apps.core.models import DataSource
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


REQUIRED_COLS = ("schoolId", "name", "region", "district")


class Command(BaseCommand):
    help = "Import schools into the LOCAL database from a CSV file (dev-only)."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the schools CSV file.")
        parser.add_argument("--env-tag", default="local",
                            help="environment tag (default: local). Use 'production' only for authorized real uploads.")

    def handle(self, *args, **options):
        if settings.IS_PRODUCTION:
            raise CommandError(
                "import_schools_local refuses to run in production. Real data is "
                "uploaded through the backend API / admin after deployment."
            )
        csv_path = options["csv_path"]
        env_tag = options["env_tag"]
        source = DataSource.LOCAL_TEST_UPLOAD.value if env_tag == "local" else DataSource.PRODUCTION_UPLOAD.value

        created = updated = skipped = 0
        try:
            with open(csv_path, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                missing = [c for c in REQUIRED_COLS if not reader.fieldnames or c not in reader.fieldnames]
                if missing:
                    raise CommandError(f"CSV is missing required columns: {', '.join(missing)}")
                for row in reader:
                    try:
                        region = Region.objects.filter(name__iexact=row["region"].strip()).first()
                        district = District.objects.filter(name__iexact=row["district"].strip()).first()
                        if not region or not district:
                            skipped += 1
                            self.stderr.write(f"  skip {row.get('schoolId')}: region/district not found")
                            continue
                        sub_county = None
                        if row.get("subCounty"):
                            sub_county = SubCounty.objects.filter(name__iexact=row["subCounty"].strip(), district=district).first()
                        defaults = {
                            "name": row["name"].strip(),
                            "region": region,
                            "district": district,
                            "sub_county": sub_county,
                            "school_type": row.get("schoolType", SchoolType.CLIENT).strip() or SchoolType.CLIENT,
                            "enrollment": int(row["enrollment"]) if row.get("enrollment") else None,
                            "school_phone": (row.get("schoolPhone") or "").strip() or None,
                            "primary_contact_name": (row.get("primaryContactName") or "").strip() or None,
                            "primary_contact_phone": (row.get("primaryContactPhone") or "").strip() or None,
                            "shipping_address": (row.get("shippingAddress") or "").strip() or None,
                            "source": source,
                            "environment": env_tag,
                        }
                        _obj, is_new = School.objects.update_or_create(
                            school_id=row["schoolId"].strip(), defaults=defaults
                        )
                        if is_new:
                            created += 1
                        else:
                            updated += 1
                    except Exception as exc:  # noqa: BLE001
                        skipped += 1
                        self.stderr.write(f"  skip {row.get('schoolId')}: {exc}")
        except FileNotFoundError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(
            f"Imported {created} schools (created={created}, updated={updated}, skipped={skipped}). "
            f"source={source}, environment={env_tag}."
        ))
