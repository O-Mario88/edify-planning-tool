"""
Management command: reimport_uploaded_schools

Re-runs the deferred import for school UploadBatch rows that are marked
'created' or 'updated' in UploadBatchRowResult but whose school_id does
not actually exist in the School table (i.e. the import_school_batch step
never ran or failed silently).

Also fixes rows where account_owner_name_raw is unmatched but the name
resolves to a known staff member via a provided alias mapping
(e.g. "Peter Chinyama" → "Paul Chinyama").

Usage:
    # Dry-run (shows what would happen, writes nothing)
    python manage.py reimport_uploaded_schools --dry-run

    # Fix with owner alias
    python manage.py reimport_uploaded_schools \
        --alias "Peter Chinyama=Paul Chinyama"

    # Limit to a specific batch
    python manage.py reimport_uploaded_schools \
        --batch-id cmqxfoyyn009rpudjdfqc \
        --alias "Peter Chinyama=Paul Chinyama"
"""
from __future__ import annotations

import logging
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

logger = logging.getLogger("edify.management")


class Command(BaseCommand):
    help = "Re-import uploaded school rows that were never persisted to the School table."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-id",
            default=None,
            help="Limit to a specific UploadBatch id. Default: all pending batches.",
        )
        parser.add_argument(
            "--alias",
            action="append",
            default=[],
            metavar="OLD_NAME=NEW_NAME",
            help=(
                "Owner name alias: map an unmatched name to the correct one. "
                "Can be repeated. Example: --alias 'Peter Chinyama=Paul Chinyama'"
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print what would happen without writing anything.",
        )

    def handle(self, *args, **options):
        from apps.schools.models import School, UploadBatch, UploadBatchRowResult
        from apps.accounts.models import StaffSchoolAssignment
        from apps.core.enums import AccountOwnerStatus

        dry_run: bool = options["dry_run"]
        batch_id: str | None = options["batch_id"]
        alias_args: list[str] = options["alias"]

        # ── Build alias map ────────────────────────────────────────────────────
        alias_map: dict[str, str] = {}
        for a in alias_args:
            if "=" not in a:
                raise CommandError(f"Invalid alias format '{a}'. Expected OLD_NAME=NEW_NAME")
            old, new = a.split("=", 1)
            alias_map[old.strip()] = new.strip()
        if alias_map:
            self.stdout.write(f"Owner aliases: {alias_map}")

        # ── Find batches to process ────────────────────────────────────────────
        qs = UploadBatch.objects.filter(upload_type="schools")
        if batch_id:
            qs = qs.filter(id=batch_id)

        batches = list(qs.order_by("created_at"))
        if not batches:
            self.stdout.write(self.style.WARNING("No matching upload batches found."))
            return

        total_imported = 0
        total_skipped = 0
        total_already_present = 0

        for batch in batches:
            self.stdout.write(f"\nBatch {batch.id}  file={batch.file_name}  created_rows={batch.created_rows}")

            # Only rows marked 'created' or 'updated' that need the actual school
            pending_rows = UploadBatchRowResult.objects.filter(
                upload_batch=batch, status__in=("created", "updated")
            )

            imported = 0
            skipped = 0
            already = 0

            for r in pending_rows:
                school_id = r.school_id
                if not school_id:
                    skipped += 1
                    continue

                # Already exists — nothing to do
                if School.objects.filter(school_id=school_id).exists():
                    already += 1
                    continue

                raw = r.raw_data_json or {}
                defaults = self._build_defaults(raw, alias_map)

                if not defaults:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  row {r.row_number}: school_id={school_id} — "
                            f"cannot reconstruct defaults (raw_data_json lacks geography). Skipping."
                        )
                    )
                    skipped += 1
                    continue

                if dry_run:
                    owner_raw = defaults.get("account_owner_name_raw") or "(none)"
                    owner_status = defaults.get("account_owner_status", "?")
                    self.stdout.write(
                        f"  [DRY RUN] Would create school_id={school_id} "
                        f"name='{defaults.get('name')}' owner='{owner_raw}' status={owner_status}"
                    )
                    imported += 1
                    continue

                try:
                    with transaction.atomic():
                        school = School.objects.create(school_id=school_id, **defaults)
                        owner_status = defaults.get("account_owner_status")
                        owner_id = defaults.get("account_owner_id")

                        if owner_status == AccountOwnerStatus.MATCHED.value and owner_id:
                            StaffSchoolAssignment.objects.get_or_create(
                                staff_id=owner_id, school_id=school.id
                            )
                    imported += 1
                    self.stdout.write(
                        f"  ✓ Created school_id={school_id} '{defaults.get('name')}' "
                        f"owner_status={defaults.get('account_owner_status')}"
                    )
                except Exception as exc:  # noqa: BLE001
                    self.stdout.write(
                        self.style.ERROR(
                            f"  ✗ Failed school_id={school_id}: {exc}"
                        )
                    )
                    skipped += 1

            self.stdout.write(
                f"  Batch done — imported={imported} already_present={already} skipped={skipped}"
            )
            total_imported += imported
            total_skipped += skipped
            total_already_present += already

        prefix = "[DRY RUN] Would import" if dry_run else "Imported"
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{prefix} {total_imported} schools. "
                f"Already present: {total_already_present}. Skipped: {total_skipped}."
            )
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _build_defaults(self, raw: dict, alias_map: dict[str, str]) -> dict | None:
        """
        Reconstruct the School.objects.create kwargs from a UploadBatchRowResult
        raw_data_json entry.

        Supports two formats:
          1. Has '_defaults' key (new format added Jun 29) — direct use.
          2. Only has flat CSV columns (old Jun 28 format) — re-resolve geography.
        """
        from apps.schools.models import UploadBatchRowResult  # noqa: F401
        from apps.core.enums import AccountOwnerStatus

        # ── Format 1: deferred defaults present ───────────────────────────────
        if "_defaults" in raw:
            d = dict(raw["_defaults"])
            if d.get("last_enrollment_date"):
                try:
                    d["last_enrollment_date"] = date.fromisoformat(d["last_enrollment_date"])
                except ValueError:
                    d.pop("last_enrollment_date", None)
            # Re-run alias substitution
            d = self._apply_alias(d, alias_map)
            return d

        # ── Format 2: flat CSV row (old format — re-resolve geography) ────────
        district_name = (raw.get("district") or "").strip()
        name = (raw.get("name") or "").strip()
        if not district_name or not name:
            return None

        district = self._resolve_district(district_name)
        if not district:
            self.stdout.write(
                self.style.WARNING(
                    f"    District '{district_name}' could not be resolved — skipping."
                )
            )
            return None

        from apps.schools.upload_mapping import map_school_type

        school_type, _ = map_school_type(raw.get("school_type", ""))

        # Enrollment
        enrollment = None
        enrollment_raw = (raw.get("enrollment") or "").strip()
        if enrollment_raw:
            try:
                enrollment = int(float(enrollment_raw))
            except ValueError:
                pass

        # Last enrollment date
        last_enrollment_date = None
        date_raw = (raw.get("last_enrollment_date") or "").strip()
        if date_raw:
            last_enrollment_date = self._parse_date_safe(date_raw)

        # Owner matching with alias substitution
        owner_raw = (raw.get("account_owner_name_raw") or "").strip() or None
        if owner_raw and owner_raw in alias_map:
            self.stdout.write(
                f"    Alias: '{owner_raw}' → '{alias_map[owner_raw]}'"
            )
            owner_raw = alias_map[owner_raw]

        owner_id, owner_status = (None, AccountOwnerStatus.PENDING.value)
        if owner_raw:
            from apps.accounts.staff_matching import match as staff_match
            owner_id, owner_status = staff_match(owner_raw)

        return {
            "name": name,
            "region_id": district.region_id,
            "district_id": district.id,
            "school_type": school_type,
            "enrollment": enrollment,
            "last_enrollment_date": last_enrollment_date,
            "school_phone": raw.get("school_phone") or None,
            "primary_contact_name": raw.get("primary_contact_name") or None,
            "shipping_address": raw.get("shipping_address") or None,
            "account_owner_name_raw": owner_raw,
            "account_owner_id": owner_id,
            "account_owner_status": owner_status,
            "uploaded_district_text": district_name,
        }

    def _apply_alias(self, defaults: dict, alias_map: dict[str, str]) -> dict:
        """Re-run owner alias substitution on a _defaults dict."""
        if not alias_map:
            return defaults
        from apps.core.enums import AccountOwnerStatus

        owner_raw = defaults.get("account_owner_name_raw") or ""
        if owner_raw in alias_map:
            new_name = alias_map[owner_raw]
            self.stdout.write(f"    Alias: '{owner_raw}' → '{new_name}'")
            from apps.accounts.staff_matching import match as staff_match
            owner_id, owner_status = staff_match(new_name)
            defaults = dict(defaults)
            defaults["account_owner_name_raw"] = new_name
            defaults["account_owner_id"] = owner_id
            defaults["account_owner_status"] = owner_status
        return defaults

    def _resolve_district(self, district_name: str):
        from apps.geography.models import District, GeographyAlias

        d = District.objects.select_related("region").filter(name__iexact=district_name).first()
        if not d:
            norm = district_name.strip().lower()
            alias = GeographyAlias.objects.filter(
                admin_level="district", normalized_alias=norm
            ).first()
            if alias:
                d = District.objects.select_related("region").filter(id=alias.admin_id).first()
        if not d:
            d = (
                District.objects.select_related("region")
                .filter(name__icontains=district_name.strip())
                .first()
                or District.objects.select_related("region")
                .filter(name__icontains=district_name.strip().split("(")[0].strip())
                .first()
            )
        return d

    def _parse_date_safe(self, value: str) -> date | None:
        from datetime import datetime

        v = value.strip()
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
        except ValueError:
            pass
        for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(v, fmt).date()
            except ValueError:
                continue
        return None
