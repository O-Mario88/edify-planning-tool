"""Management command: recompute_unmatched_ssa_suggestions

Backfills UnmatchedSSARecord.suggested_school/match_confidence for rows that
predate the write-time computation added in Issue 5 of the audit
(apps.ssa.upload_service.import_ssa_batch now calls
apps.ssa.unmatched_service.compute_suggested_match once at upload time).
Idempotent — only touches rows with match_confidence IS NULL by default;
--force recomputes every pending/hold row regardless.

Usage:
    python manage.py recompute_unmatched_ssa_suggestions [--force] [--dry-run]
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Backfill suggested_school/match_confidence for unmatched SSA records that predate write-time computation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Recompute every pending/hold row, not just ones with no suggestion yet.",
        )
        parser.add_argument("--dry-run", action="store_true", default=False)

    def handle(self, *args, **options):
        from apps.schools.models import UnmatchedSSARecord
        from apps.ssa import unmatched_service

        qs = UnmatchedSSARecord.objects.filter(status__in=["pending", "hold"])
        if not options["force"]:
            qs = qs.filter(match_confidence__isnull=True)

        total = qs.count()
        if not total:
            self.stdout.write(self.style.SUCCESS("Nothing to recompute."))
            return

        updated = 0
        for rec in qs.iterator():
            school_id, confidence = unmatched_service.compute_suggested_match(
                rec.school_name_raw,
                rec.district_raw,
            )
            self.stdout.write(
                f"  {rec.id} ({rec.school_name_raw!r}) -> {school_id or 'no match'} "
                f"(confidence={confidence})"
            )
            if options["dry_run"]:
                continue
            rec.suggested_school_id = school_id
            rec.match_confidence = confidence
            rec.save(update_fields=["suggested_school", "match_confidence"])
            updated += 1

        prefix = "[DRY RUN] Would update" if options["dry_run"] else "Updated"
        self.stdout.write(
            self.style.SUCCESS(f"{prefix} {updated} of {total} unmatched record(s).")
        )
