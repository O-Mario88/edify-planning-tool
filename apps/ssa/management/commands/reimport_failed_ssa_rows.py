"""
Management command: reimport_failed_ssa_rows

Re-processes SSA UploadBatchRowResult rows that previously failed with
"School X is not in the directory." — now that those schools have been
imported, this command creates the missing SsaRecord entries.

Usage:
    python manage.py reimport_failed_ssa_rows [--dry-run] [--batch-id ID]
"""

from __future__ import annotations

import logging
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

logger = logging.getLogger("edify.management")


class Command(BaseCommand):
    help = "Re-import SSA upload rows that failed because the school was not yet in the directory."

    def add_arguments(self, parser):
        parser.add_argument("--batch-id", default=None)
        parser.add_argument("--dry-run", action="store_true", default=False)

    def handle(self, *args, **options):
        from apps.schools.models import UploadBatch, UploadBatchRowResult, School
        from apps.ssa.services import upload as ssa_upload_service
        from apps.schools.upload_service import _parse_date
        from apps.schools import upload_mapping as M

        dry_run = options["dry_run"]
        batch_id = options["batch_id"]

        qs = UploadBatch.objects.filter(upload_type="ssa")
        if batch_id:
            qs = qs.filter(id=batch_id)

        batches = list(qs.order_by("created_at"))
        if not batches:
            self.stdout.write(self.style.WARNING("No SSA upload batches found."))
            return

        total_imported = 0
        total_skipped = 0

        for batch in batches:
            failed_rows = UploadBatchRowResult.objects.filter(
                upload_batch=batch,
                status="failed",
                error_message__icontains="is not in the directory",
            )
            count = failed_rows.count()
            if count == 0:
                continue

            self.stdout.write(
                f"\nBatch {batch.id}  file={batch.file_name}  failed_rows={count}"
            )
            uploader_id = batch.uploaded_by

            for r in failed_rows:
                school_id = r.school_id
                raw = r.raw_data_json or {}

                # Confirm school now exists
                school = School.objects.filter(school_id=school_id).first()
                if not school:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  row {r.row_number}: School {school_id} still not found — skipping."
                        )
                    )
                    total_skipped += 1
                    continue

                # Rebuild score dict from raw_data_json
                scores = {}
                bad = False
                for interv in M.ALL_INTERVENTIONS:
                    raw_val = (raw.get(interv) or "").strip()
                    if not raw_val:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  row {r.row_number}: Missing score for '{interv}' — skipping."
                            )
                        )
                        bad = True
                        break
                    try:
                        val = float(raw_val)
                        if not (0 <= val <= 10):
                            raise ValueError("out of range")
                        scores[interv] = val
                    except ValueError:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  row {r.row_number}: Invalid score for '{interv}': {raw_val!r} — skipping."
                            )
                        )
                        bad = True
                        break
                if bad:
                    total_skipped += 1
                    continue

                date_raw = (raw.get("date_of_ssa") or "").strip()
                try:
                    ssa_date = _parse_date(date_raw)
                except (ValueError, AttributeError):
                    self.stdout.write(
                        self.style.WARNING(
                            f"  row {r.row_number}: Invalid date '{date_raw}' — skipping."
                        )
                    )
                    total_skipped += 1
                    continue

                new_enrollment_raw = (raw.get("new_enrollment") or "").strip()
                new_enrollment = None
                if new_enrollment_raw:
                    try:
                        new_enrollment = int(float(new_enrollment_raw))
                    except ValueError:
                        pass

                if dry_run:
                    self.stdout.write(
                        f"  [DRY RUN] Would create SSA for school_id={school_id} "
                        f"date={ssa_date} scores={scores}"
                    )
                    total_imported += 1
                    continue

                try:
                    with transaction.atomic():
                        # Build a mock principal with uploader_id
                        class _P:
                            user_id = uploader_id
                            active_role = "Admin"
                            staff_profile_id = None

                        # Build the scores list in the format services.upload() expects
                        scores_list = [
                            {"intervention": k, "score": v} for k, v in scores.items()
                        ]
                        data = {
                            "schoolId": school_id,
                            "dateOfSsa": datetime.combine(
                                ssa_date, datetime.min.time()
                            ).isoformat(),
                            "scores": scores_list,
                            "newEnrollment": new_enrollment,
                            "collectorType": "staff",
                        }
                        ssa_upload_service(data, _P())
                        # Update the row result status
                        r.status = "created"
                        r.error_message = None
                        r.save(update_fields=["status", "error_message"])

                    total_imported += 1
                    self.stdout.write(
                        f"  ✓ SSA created for school_id={school_id} date={ssa_date}"
                    )
                except Exception as exc:  # noqa: BLE001
                    self.stdout.write(
                        self.style.ERROR(
                            f"  ✗ Failed SSA for school_id={school_id}: {exc}"
                        )
                    )
                    total_skipped += 1

        prefix = "[DRY RUN] Would import" if dry_run else "Imported"
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{prefix} {total_imported} SSA records. Skipped: {total_skipped}."
            )
        )
