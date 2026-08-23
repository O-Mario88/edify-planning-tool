"""
Management command: relink_school_geography

Re-resolves School.district / School.region / School.sub_county from the
geography names the upload originally carried.

Why this exists: Uganda's administrative boundaries were seeded only under
``seed --demo``, so a production database came up with no Region or District
rows. The school upload resolves a district BY NAME, so every school imported
before geography existed kept its raw district text and no foreign key --
leaving district-scoped analytics reporting "Coverage: 0 of 0 districts" while
the register plainly showed a district for each school.

Seeding geography afterwards does not repair those rows on its own: the school
importer only resolves geography at import time. This re-runs that resolution
against the rows already in the database, so a 16,000-school register does not
have to be uploaded again to gain the links it should always have had.

Idempotent, and it never clears an existing link. Without ``--force``, a school
is considered whenever either its district or sub-county link is missing.

Usage:
    python manage.py relink_school_geography --dry-run
    python manage.py relink_school_geography
    python manage.py relink_school_geography --force
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

logger = logging.getLogger("edify.management")


class Command(BaseCommand):
    help = "Re-resolve school district, region, and sub-county geography links."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change and write nothing.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Also re-resolve schools whose geography links are complete.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Rows per bulk_update (default 1000).",
        )

    def handle(self, *args, **options):
        from apps.geography.models import District
        from apps.schools.models import School
        from apps.schools.upload_service import (
            _build_geography_index,
            _resolve_geography,
        )

        dry_run = options["dry_run"]
        force = options["force"]
        batch_size = max(1, options["batch_size"])

        if not District.objects.exists():
            self.stdout.write(
                self.style.ERROR(
                    "No districts exist. Run `python manage.py seed` first — "
                    "geography is reference data and must be seeded before "
                    "schools can be linked to it."
                )
            )
            return

        index = _build_geography_index()

        queryset = School.objects.filter(deleted_at__isnull=True).select_related(
            "district"
        )
        if not force:
            queryset = queryset.filter(
                Q(district__isnull=True) | Q(sub_county__isnull=True)
            )
        queryset = queryset.filter(
            (Q(uploaded_district_text__isnull=False) & ~Q(uploaded_district_text=""))
            | (
                Q(uploaded_sub_county_text__isnull=False)
                & ~Q(uploaded_sub_county_text="")
            )
        )

        total = queryset.count()
        self.stdout.write(f"Candidate schools: {total}")

        resolved = 0
        unresolved: dict[str, int] = {}
        pending: list[School] = []

        for school in queryset.iterator(chunk_size=batch_size):
            district, sub_county, _ambiguous = _resolve_geography(
                school.uploaded_district_text
                or (school.district.name if school.district_id else ""),
                # Sub-county is resolved from the school's own stored value
                # when present; the operational register has left it blank, so
                # this usually contributes nothing and must not invent one.
                getattr(school, "uploaded_sub_county_text", "") or "",
                index=index,
            )
            if district is None:
                name = (school.uploaded_district_text or "").strip()
                unresolved[name] = unresolved.get(name, 0) + 1
                continue

            school.district = district
            school.region = district.region
            # Only set when the register actually supplied one — never infer a
            # sub-county the upload did not name.
            if sub_county is not None:
                school.sub_county = sub_county
            pending.append(school)
            resolved += 1

            if len(pending) >= batch_size and not dry_run:
                self._flush(pending)

        if pending and not dry_run:
            self._flush(pending)

        verb = "would link" if dry_run else "linked"
        self.stdout.write(self.style.SUCCESS(f"{verb} {resolved} school(s)."))

        if unresolved:
            self.stdout.write(
                f"\nStill unresolved ({sum(unresolved.values())} school(s)) — these "
                "district names match no district and no alias:"
            )
            for name, count in sorted(unresolved.items(), key=lambda kv: -kv[1])[:20]:
                self.stdout.write(f"  {count:>6}  {name!r}")
            self.stdout.write(
                "Add each to Command.DISTRICT_UPLOAD_ALIASES in the seed command "
                "(or as a GeographyAlias row) rather than guessing at a match here."
            )

    @staticmethod
    def _flush(pending: list) -> None:
        with transaction.atomic():
            type(pending[0]).objects.bulk_update(
                pending, ["district", "region", "sub_county", "updated_at"]
            )
        pending.clear()
