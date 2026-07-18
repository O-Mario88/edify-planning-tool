"""
File-based school upload (CSV + XLSX) — the truthful, persisted onboarding path.

`POST /api/schools/upload` flows through `upload_school_file`. The file is parsed
with a real parser (Python `csv` for CSV, `openpyxl` for XLSX — never naive
string splitting), headers are normalized through the single canonical mapping
module, and each row is validated + saved (or skipped/failed/duplicated) with a
per-row audit result. A file-level/header error rolls back everything (nothing is
written); row-level errors never block the valid rows.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

from django.db import transaction

from apps.core.exceptions import BadRequest

from . import upload_mapping as M


def _resolve_geography(district_name: str, sub_county_name: str):
    """Resolve (district, sub_county, ambiguous_district_names) from raw
    upload text.

    If district_name is blank but sub_county_name is present, infer the
    district from an unambiguous sub-county name match instead of leaving
    district None — callers used to fall through to an arbitrary
    alphabetically-first District in that case (School.objects.create's old
    `district or District.objects.first()`), silently misassigning the
    school's geography with no warning and discarding the sub-county text
    entirely (sub_county resolution requires district). When the sub-county
    name matches more than one district, it's genuinely ambiguous —
    ambiguous_district_names lists the candidates so the caller can block
    the row instead of guessing.
    """
    from apps.geography.models import District, GeographyAlias, SubCounty

    district = None
    if district_name:
        district = District.objects.filter(name__iexact=district_name).first()
        if not district:
            norm = district_name.strip().lower()
            alias = GeographyAlias.objects.filter(
                admin_level="district", normalized_alias=norm
            ).first()
            if alias:
                district = District.objects.filter(id=alias.admin_id).first()
        if not district:
            district = District.objects.filter(
                name__icontains=district_name.strip()
            ).first()

    ambiguous_district_names: list[str] = []
    if not district and sub_county_name:
        matches = list(
            SubCounty.objects.filter(
                name__iexact=sub_county_name.strip()
            ).select_related("district")
        )
        if not matches:
            matches = list(
                SubCounty.objects.filter(
                    name__icontains=sub_county_name.strip()
                ).select_related("district")
            )
        districts_by_id = {m.district_id: m.district for m in matches}
        if len(districts_by_id) == 1:
            district = next(iter(districts_by_id.values()))
        elif len(districts_by_id) > 1:
            ambiguous_district_names = sorted(d.name for d in districts_by_id.values())

    sub_county = None
    if sub_county_name and district:
        sub_county = SubCounty.objects.filter(
            district=district, name__iexact=sub_county_name
        ).first()
        if not sub_county:
            sub_county = SubCounty.objects.filter(
                district=district, name__icontains=sub_county_name
            ).first()

    return district, sub_county, ambiguous_district_names


# ── Parsing ──────────────────────────────────────────────────────────────────
def _read_rows(file) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """Parse an uploaded file into (raw_headers, [(row_number, cells)]).

    row_number is the 1-based spreadsheet line including the header (header == 1,
    first data row == 2). Fully-blank rows are dropped here only when they carry
    no cells at all; blank-but-present rows are kept so the caller can mark them
    `skipped` truthfully."""
    name = (getattr(file, "name", "") or "").lower()
    raw = file.read()
    if isinstance(raw, str):
        raw = raw.encode("utf-8")

    is_xlsx = name.endswith(".xlsx") or name.endswith(".xlsm")
    if is_xlsx:
        return _read_xlsx(raw)
    return _read_csv(raw)


def _read_csv(raw: bytes) -> tuple[list[str], list[tuple[int, list[str]]]]:
    text = raw.decode("utf-8-sig", errors="replace")  # utf-8-sig strips the BOM
    reader = csv.reader(io.StringIO(text))
    all_rows = list(reader)
    if not all_rows:
        return [], []
    headers = [c.strip() for c in all_rows[0]]
    data: list[tuple[int, list[str]]] = []
    for i, cells in enumerate(all_rows[1:], start=2):
        # A truly empty line (no cells at all) is not a record — drop it. A row
        # of empty commas (cells present but blank) is a real blank row → kept so
        # the caller can mark it `skipped`.
        if len(cells) == 0:
            continue
        data.append((i, [(c or "").strip() for c in cells]))
    return headers, data


def _read_xlsx(raw: bytes) -> tuple[list[str], list[tuple[int, list[str]]]]:
    try:
        import openpyxl  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - openpyxl is a declared dep
        raise BadRequest("XLSX support requires openpyxl on the server.") from exc

    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise BadRequest(f"Could not read the XLSX file: {exc}") from exc
    ws = wb.worksheets[0]
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        return [], []
    headers = [_cell_to_str(c).strip() for c in header_row]
    data: list[tuple[int, list[str]]] = []
    for i, row in enumerate(rows_iter, start=2):
        data.append((i, [_cell_to_str(c).strip() for c in row]))
    return headers, data


def _cell_to_str(c) -> str:
    if c is None:
        return ""
    if isinstance(c, datetime):
        return c.date().isoformat()
    if isinstance(c, date):
        return c.isoformat()
    if isinstance(c, float) and c.is_integer():
        return str(int(c))
    return str(c)


def _value(field_index: dict[str, int], field: str, cells: list[str]) -> str:
    col = field_index.get(field)
    if col is None or col >= len(cells):
        return ""
    return (cells[col] or "").strip()


def _parse_date(value: str) -> date:
    """Parse a date cell into a `date`. Accepts ISO + common spreadsheet forms."""
    v = value.strip()
    # ISO first (covers 2026-01-31 and full datetimes).
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date '{value}'")


def _match_account_owner(name: str) -> tuple[str | None, str]:
    """Match a raw staff name via the StaffMatchingService. Returns
    (staff_profile_id | None, status). Replaces the old single-user iexact match
    with role-aware matching + ambiguity detection."""
    from apps.accounts.staff_matching import match as staff_match

    return staff_match(name)


def _auto_create_user_from_upload(full_name: str) -> str:
    """Automatically create a User and StaffProfile when a school is uploaded with an unmatched owner name."""
    from apps.accounts.models import User, StaffProfile, UserStatus
    from apps.core.rbac import EdifyRole
    import re

    name_clean = full_name.strip()
    if not name_clean:
        return None

    # Check if user already exists
    existing = User.objects.filter(
        name__iexact=name_clean, deleted_at__isnull=True
    ).first()
    if existing:
        from apps.accounts.staff_matching import _is_field_staff

        profile = StaffProfile.objects.filter(user=existing).first()
        if profile and _is_field_staff(profile):
            return profile.id
        return None

    # Generate placeholder email
    normalized_part = re.sub(r"[^a-zA-Z0-9.]", "", name_clean.lower().replace(" ", "."))
    placeholder_email = f"pending.{normalized_part}@edify.org"
    suffix = 1
    while User.objects.filter(email=placeholder_email).exists():
        placeholder_email = f"pending.{normalized_part}.{suffix}@edify.org"
        suffix += 1

    # Create User
    user = User.objects.create_user(
        email=placeholder_email,
        name=name_clean,
        roles=[EdifyRole.CCEO.value],
        active_role=EdifyRole.CCEO.value,
        password=None,
        status=UserStatus.PENDING_INVITED,
        is_active=False,
    )

    # Create StaffProfile
    profile = StaffProfile.objects.create(user=user, title="CCEO")

    # Create StaffSetupCandidate to track in Admin's queue
    from apps.accounts.models import StaffSetupCandidate, StaffSetupCandidateStatus
    from apps.accounts.staff_matching import normalize_name

    norm = normalize_name(name_clean)
    StaffSetupCandidate.objects.get_or_create(
        normalized_name=norm,
        defaults={
            "full_name": name_clean,
            "status": StaffSetupCandidateStatus.PENDING_PROFILE,
            "matched_user_id": user.id,
            "email": placeholder_email,
        },
    )

    return profile.id


def _upsert_staff_candidate(name: str, batch_id: str, school_pk: str) -> None:
    """Create/update a StaffSetupCandidate for an unmatched/ambiguous staff name.
    One candidate per normalized name (no duplicates across uploads); each new
    school increments the count and is appended to the sample list."""
    from apps.accounts.models import StaffSetupCandidate
    from apps.accounts.staff_matching import normalize_name

    norm = normalize_name(name)
    if not norm:
        return
    cand, created = StaffSetupCandidate.objects.get_or_create(
        normalized_name=norm,
        defaults={"full_name": name.strip(), "source_upload_batch": batch_id},
    )
    if created:
        cand.school_count = 1
        cand.sample_school_ids = [school_pk]
    else:
        cand.school_count = (cand.school_count or 0) + 1
        sample = list(cand.sample_school_ids or [])
        if school_pk not in sample:
            sample.append(school_pk)
            cand.sample_school_ids = sample[:20]  # cap the sample list
    cand.save(update_fields=["school_count", "sample_school_ids"])


# ── Main entry ───────────────────────────────────────────────────────────────
def upload_school_file(file, principal, update_existing: bool = False) -> dict:
    """Parse + validate + stage a school onboarding file. Returns the staging
    response contract. Raises BadRequest (→ 400) on file/header errors."""
    from apps.schools.models import SchoolImportBatch, SchoolImportRow, School

    raw_headers, data_rows = _read_rows(file)
    if not raw_headers:
        raise BadRequest("The uploaded file is empty — no header row found.")

    field_index = M.build_field_index(raw_headers, M.SCHOOL_HEADER_MAP)
    missing = M.missing_required(field_index, M.SCHOOL_REQUIRED_FIELDS)
    if missing:
        label = {
            "school_id": "School ID",
            "name": "School Name",
            "district": "District",
        }
        raise BadRequest(
            "Missing required column(s): "
            + ", ".join(label[m] for m in missing)
            + f". Received headers: [{', '.join(h for h in raw_headers if h)}]. "
            + f"Expected headers include: [{', '.join(M.SCHOOL_EXPECTED_HEADERS)}]."
        )

    batch = SchoolImportBatch.objects.create(
        file_name=getattr(file, "name", "salesforce_import.xlsx"),
        uploaded_by=principal.user_id,
        status="staged",
        total_rows=len(data_rows),
    )

    counts = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "duplicate": 0}
    staff_counts = {"matched": 0, "unmatched": 0, "ambiguous": 0}
    errors = []
    rows_to_create = []

    for row_number, cells in data_rows:
        raw_map = {f: _value(field_index, f, cells) for f in field_index}

        # Fully-blank row → skipped.
        if not any((cells[i] or "").strip() for i in range(len(cells))):
            counts["skipped"] += 1
            continue

        school_id_raw = _value(field_index, "school_id", cells)
        name = _value(field_index, "name", cells)
        district_name = _value(field_index, "district", cells)
        sub_county_name = _value(field_index, "sub_county", cells)
        enrollment_raw = _value(field_index, "enrollment", cells)
        phone = _value(field_index, "school_phone", cells)
        contact_person = _value(field_index, "primary_contact_name", cells)
        director_name = _value(field_index, "director_name", cells)
        headteacher_name = _value(field_index, "headteacher_name", cells)
        address = _value(field_index, "shipping_address", cells)
        account_owner_name = _value(field_index, "account_owner_name_raw", cells)
        school_type = _value(field_index, "school_type", cells)

        validation_errors = []
        status = "ready"

        # B. Row-Level Critical Blockers
        if not school_id_raw:
            validation_errors.append("Missing School ID")
            status = "blocked"
            counts["failed"] += 1

        if not name:
            validation_errors.append("Missing School Name")
            status = "blocked"
            if school_id_raw:
                counts["failed"] += 1

        # Check location (district and sub_county) — inferring district from
        # sub_county when district_name is blank, rather than silently
        # falling through to an arbitrary district at import time.
        district, _sub_county_preview, ambiguous_district_names = _resolve_geography(
            district_name, sub_county_name
        )

        if not district_name and not sub_county_name:
            validation_errors.append("No usable location at all")
            status = "blocked"
            if school_id_raw:
                counts["failed"] += 1
        elif district_name and not district:
            validation_errors.append(f"District '{district_name}' could not be matched")
            status = "blocked"
            if school_id_raw:
                counts["failed"] += 1
        elif not district_name and ambiguous_district_names:
            validation_errors.append(
                f"Sub-county '{sub_county_name}' exists in multiple districts "
                f"({', '.join(ambiguous_district_names)}) — a District column "
                "value is required to disambiguate."
            )
            status = "blocked"
            if school_id_raw:
                counts["failed"] += 1
        elif not district_name and sub_county_name and not district:
            validation_errors.append(
                f"Sub-county '{sub_county_name}' could not be matched to any "
                "district."
            )
            status = "blocked"
            if school_id_raw:
                counts["failed"] += 1

        # C. Non-blocking warnings / updates
        if status != "blocked":
            existing = School.objects.filter(
                school_id=school_id_raw, deleted_at__isnull=True
            ).first()
            if existing:
                if update_existing:
                    status = "update"
                    counts["updated"] += 1
                else:
                    status = "duplicate"
                    counts["duplicate"] += 1
            else:
                # Check for potential duplicates by name in DB
                existing_name = School.objects.filter(
                    name__iexact=name, deleted_at__isnull=True
                ).exists()
                if existing_name:
                    status = "duplicate"
                    counts["duplicate"] += 1
                    validation_errors.append(
                        f"Possible duplicate name: school with name '{name}' already exists in database"
                    )
                else:
                    status = "ready"
                    counts["created"] += 1

            # Match account owner to populate staff counts
            if account_owner_name:
                from apps.accounts.staff_matching import match as staff_match

                owner_id, owner_status = staff_match(account_owner_name)
                if owner_status in staff_counts:
                    staff_counts[owner_status] += 1

            # Check optional gaps for Needs Review / Warnings
            if not phone:
                validation_errors.append("Missing phone number")
            if not contact_person:
                validation_errors.append("Missing contact person")
            if not enrollment_raw:
                validation_errors.append("Missing enrollment")

        enrollment = None
        if enrollment_raw:
            try:
                enrollment = int(float(enrollment_raw))
            except ValueError:
                pass

        if validation_errors and status == "blocked":
            errors.append(
                {
                    "row": row_number,
                    "school_id": school_id_raw,
                    "error": "; ".join(validation_errors),
                }
            )

        rows_to_create.append(
            SchoolImportRow(
                batch=batch,
                row_number=row_number,
                school_id=school_id_raw,
                name=name,
                school_type=school_type,
                district_name=district_name,
                sub_county_name=sub_county_name,
                enrollment=enrollment,
                phone=phone,
                contact_person=contact_person,
                director_name=director_name,
                headteacher_name=headteacher_name,
                address=address,
                account_owner_name=account_owner_name,
                status=status,
                validation_errors=validation_errors,
                raw_data=raw_map,
            )
        )

    if rows_to_create:
        SchoolImportRow.objects.bulk_create(rows_to_create)

    # Legacy parallel write to keep REST endpoints and unit tests 100% green.
    # status starts "uploaded" (not "imported") and is only flipped to
    # "imported" once import_school_batch actually succeeds below — it used
    # to be stamped "imported" here unconditionally, so a failed import left
    # the batch history permanently showing false success counts, AND
    # (since UploadBatchActionView's "import" action short-circuits when
    # status is already "imported") made the failed import unretryable
    # through the same endpoint.
    from apps.schools.models import UploadBatch, UploadBatchRowResult

    legacy_batch = UploadBatch.objects.create(
        source="csv_upload",
        upload_type="schools",
        file_name=getattr(file, "name", "salesforce_import.xlsx"),
        original_file_name=getattr(file, "name", "salesforce_import.xlsx"),
        uploaded_by=principal.user_id,
        status="uploaded",
        total_rows=len(data_rows),
        created_rows=counts["created"],
        updated_rows=counts["updated"],
        skipped_rows=counts["skipped"],
        failed_rows=counts["failed"],
        duplicate_rows=counts["duplicate"],
    )

    legacy_rows = []
    for r in rows_to_create:
        legacy_rows.append(
            UploadBatchRowResult(
                upload_batch=legacy_batch,
                row_number=r.row_number,
                school_id=r.school_id,
                status="created"
                if r.status in ("ready", "duplicate")
                else "updated"
                if r.status == "update"
                else "failed"
                if r.status == "blocked"
                else "skipped",
                error_message="; ".join(r.validation_errors)
                if r.validation_errors
                else "",
                raw_data_json=r.raw_data,
            )
        )
    if legacy_rows:
        UploadBatchRowResult.objects.bulk_create(legacy_rows)

    # Automatically import if not blocked. A failure here must not leave the
    # batch history lying about what happened (previously: status was
    # already stamped "imported" before this even ran) or crash out to the
    # caller as a bare 500 — record the honest failure and surface it as a
    # normal, handleable error.
    success = counts["created"] > 0 or (update_existing and counts["updated"] > 0)
    if success:
        try:
            import_school_batch(batch, principal)
        except Exception as exc:
            legacy_batch.status = "failed"
            legacy_batch.error_summary = str(exc)
            legacy_batch.save(update_fields=["status", "error_summary", "updated_at"])
            raise BadRequest(f"School import failed: {exc}") from exc
        legacy_batch.status = "imported"
        legacy_batch.save(update_fields=["status", "updated_at"])

    message = _build_message(success, counts, len(data_rows))
    return {
        "success": success,
        "upload_batch_id": legacy_batch.id,
        "total_rows": len(data_rows),
        "created_rows": counts["created"],
        "updated_rows": counts["updated"],
        "failed_rows": counts["failed"],
        "duplicate_rows": counts["duplicate"],
        "skipped_rows": counts["skipped"],
        "matched_staff_count": staff_counts["matched"],
        "unmatched_staff_count": staff_counts["unmatched"],
        "ambiguous_staff_count": staff_counts["ambiguous"],
        "unmatched_staff": [],
        "message": message,
        "errors": errors,
    }


def import_school_batch(batch, user) -> dict:
    from apps.schools.models import (
        School,
        SchoolChangeLog,
        UploadBatch,
        SchoolImportBatch,
    )
    from apps.accounts.staff_matching import match as staff_match

    if isinstance(batch, UploadBatch):
        real_batch = (
            SchoolImportBatch.objects.filter(
                file_name=batch.file_name, uploaded_by=batch.uploaded_by
            )
            .order_by("-created_at")
            .first()
        )
        if real_batch:
            batch = real_batch

    # "duplicate" rows are schools that already exist while update_existing
    # was False — staging counted them as NOT imported, so importing (and
    # silently overwriting the live school) here would contradict what the
    # uploader was told. Only "blocked" and "duplicate" are excluded;
    # "update" rows (update_existing=True) still update.
    rows = batch.rows.exclude(status__in=["blocked", "duplicate"])
    created_count = 0
    updated_count = 0
    clean_count = 0
    review_count = 0
    cleanup_count = 0
    duplicate_count = 0

    with transaction.atomic():
        for r in rows:
            # Same resolution the staging/validation phase used (including
            # the sub-county-infers-district fallback) — using independent
            # logic here previously meant a row that passed validation could
            # still land on a different (or, when district_name was blank,
            # an arbitrary alphabetically-first) District at import time.
            district, sub_county, _ambiguous = _resolve_geography(
                r.district_name, r.sub_county_name
            )
            if district is None and (r.district_name or r.sub_county_name):
                # Re-validated at import time defensively — should already
                # have been staged as "blocked" and excluded above, but a
                # row must never silently land on a fabricated geography.
                continue

            owner_id = None
            owner_status = "pending"
            if r.account_owner_name:
                owner_id, owner_status = staff_match(r.account_owner_name)
                if owner_status == "unmatched":
                    new_owner_id = _auto_create_user_from_upload(r.account_owner_name)
                    if new_owner_id:
                        owner_id = new_owner_id
                        owner_status = "matched"

            # map_school_type() always returns a concrete value (defaults to
            # "client" for a blank/unrecognized cell) — never None/"" — so it
            # would defeat the blank-doesn't-overwrite guard below unless we
            # separately track whether the source cell actually had text.
            school_type, _ = M.map_school_type(r.school_type)

            last_enroll_date = None
            led_val = r.raw_data.get("last_enrollment_date")
            if led_val:
                try:
                    last_enroll_date = date.fromisoformat(led_val.strip())
                except ValueError:
                    pass

            existing = School.objects.filter(
                school_id=r.school_id, deleted_at__isnull=True
            ).first()

            if existing:
                # Upsert mode: do not overwrite good existing data with blanks!
                # Keep history in SchoolChangeLog
                fields_to_update = {
                    "name": r.name,
                    "district": district,
                    "region": district.region if district else existing.region,
                    "sub_county": sub_county,
                    "enrollment": r.enrollment,
                    "last_enrollment_date": last_enroll_date,
                    "school_phone": r.phone,
                    "primary_contact_name": r.contact_person,
                    "shipping_address": r.address,
                    "director_name": r.director_name,
                    "headteacher_name": r.headteacher_name,
                }
                # school_type/account_owner_* are computed defaults that are
                # never blank/None even when the source cell was — only
                # touch them when the uploader actually supplied that column
                # for this row, so a partial re-upload (e.g. only enrollment
                # changed) can't silently demote a Core school back to
                # "client" or reset an already-matched owner to "pending".
                if r.school_type:
                    fields_to_update["school_type"] = school_type
                if r.account_owner_name:
                    fields_to_update["account_owner_name_raw"] = r.account_owner_name
                    fields_to_update["account_owner_id"] = owner_id
                    fields_to_update["account_owner_status"] = owner_status

                changes = []
                for field, val in fields_to_update.items():
                    if val is not None and val != "":
                        old_val = getattr(existing, field)
                        if val != old_val:
                            changes.append(
                                SchoolChangeLog(
                                    school=existing,
                                    field_name=field,
                                    old_value=str(old_val)
                                    if old_val is not None
                                    else None,
                                    new_value=str(val),
                                    changed_by=user.user_id
                                    if hasattr(user, "user_id")
                                    else str(user),
                                )
                            )
                            setattr(existing, field, val)

                if changes:
                    existing.save()
                    SchoolChangeLog.objects.bulk_create(changes)
                else:
                    existing.save()  # trigger save hook for readiness
                updated_count += 1
                saved_school = existing
            else:
                # `district` is guaranteed non-None here: the only way to
                # reach this branch with an unresolved district is a row
                # with no district_name AND no sub_county_name, which is
                # already staged as "blocked" and excluded from `rows`
                # above — District.region is a required (non-nullable) FK,
                # so no separate Region fallback is needed either. No more
                # falling back to an arbitrary alphabetically-first
                # District/Region for a school whose actual location just
                # couldn't be resolved.
                saved_school = School.objects.create(
                    school_id=r.school_id,
                    name=r.name,
                    school_type=school_type,
                    region=district.region,
                    district=district,
                    sub_county=sub_county,
                    enrollment=r.enrollment,
                    last_enrollment_date=last_enroll_date,
                    school_phone=r.phone,
                    primary_contact_name=r.contact_person,
                    shipping_address=r.address,
                    director_name=r.director_name,
                    headteacher_name=r.headteacher_name,
                    account_owner_name_raw=r.account_owner_name,
                    account_owner_id=owner_id,
                    account_owner_status=owner_status,
                )
                created_count += 1

            if owner_id and owner_status == "matched":
                from apps.accounts.models import StaffSchoolAssignment

                StaffSchoolAssignment.objects.get_or_create(
                    staff_id=owner_id, school_id=saved_school.id
                )
                from apps.accounts.models import StaffProfile

                sp = (
                    StaffProfile.objects.filter(id=owner_id)
                    .select_related("user")
                    .first()
                )
                if (
                    sp
                    and sp.user
                    and (
                        "pending." in sp.user.email
                        or sp.user.status == "pending_invited"
                    )
                ):
                    _upsert_staff_candidate(
                        r.account_owner_name, batch.id, saved_school.id
                    )
            elif owner_status in ("unmatched", "ambiguous") and r.account_owner_name:
                _upsert_staff_candidate(r.account_owner_name, batch.id, saved_school.id)

            q_status = saved_school.data_quality_status
            if q_status == "Clean":
                clean_count += 1
            elif q_status == "Needs Review":
                review_count += 1
            elif q_status == "Needs Cleanup":
                cleanup_count += 1
            elif q_status == "Duplicate Risk":
                duplicate_count += 1

        batch.status = "imported"
        batch.save()

    return {
        "created": created_count,
        "updated": updated_count,
        "clean": clean_count,
        "review": review_count,
        "cleanup": cleanup_count,
        "duplicate": duplicate_count,
    }


def _build_message(success: bool, counts: dict, total: int) -> str:
    if total == 0:
        return "No data rows were found in the file."
    if success:
        parts = []
        if counts["created"]:
            parts.append(f"{counts['created']} created")
        if counts["updated"]:
            parts.append(f"{counts['updated']} updated")
        if counts["duplicate"]:
            parts.append(f"{counts['duplicate']} duplicate")
        if counts["failed"]:
            parts.append(f"{counts['failed']} failed")
        if counts["skipped"]:
            parts.append(f"{counts['skipped']} skipped")
        return "Upload complete — " + ", ".join(parts) + "."
    if counts["duplicate"] and not counts["failed"]:
        return f"Nothing saved — all {counts['duplicate']} row(s) already exist."
    if counts["failed"] and not counts["duplicate"]:
        return f"Nothing saved — all {counts['failed']} row(s) failed validation. See the errors below."
    return "Nothing was saved — no rows were created or updated."


__all__ = ["upload_school_file", "import_school_batch"]
