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

import logging

import csv
import io
import time
from collections import defaultdict
from datetime import date, datetime

from django.db import transaction

from apps.core.exceptions import BadRequest

from . import upload_mapping as M

logger = logging.getLogger(__name__)


def _lookup_key(value: str | None) -> str:
    return (value or "").strip().casefold()


def _build_geography_index() -> dict:
    """Load geography once for a whole import instead of once per row."""
    from apps.geography.models import District, GeographyAlias, SubCounty

    districts = list(District.objects.select_related("region").order_by("name", "id"))
    sub_counties = list(
        SubCounty.objects.select_related("district", "district__region").order_by(
            "name", "id"
        )
    )
    district_exact: dict[str, list] = defaultdict(list)
    sub_county_exact: dict[str, list] = defaultdict(list)
    sub_counties_by_district: dict[str, list] = defaultdict(list)
    for district in districts:
        district_exact[_lookup_key(district.name)].append(district)
    for sub_county in sub_counties:
        sub_county_exact[_lookup_key(sub_county.name)].append(sub_county)
        sub_counties_by_district[sub_county.district_id].append(sub_county)

    aliases = {}
    for alias, admin_id in GeographyAlias.objects.filter(
        admin_level="district"
    ).values_list("normalized_alias", "admin_id"):
        aliases.setdefault(_lookup_key(alias), admin_id)

    return {
        "districts": districts,
        "district_exact": district_exact,
        "district_by_id": {district.id: district for district in districts},
        "district_aliases": aliases,
        "sub_counties": sub_counties,
        "sub_county_exact": sub_county_exact,
        "sub_counties_by_district": sub_counties_by_district,
    }


def _resolve_geography(
    district_name: str,
    sub_county_name: str,
    *,
    index: dict | None = None,
):
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
    index = index or _build_geography_index()

    district = None
    district_key = _lookup_key(district_name)
    sub_county_key = _lookup_key(sub_county_name)
    if district_key:
        exact = index["district_exact"].get(district_key, [])
        district = exact[0] if exact else None
        if not district:
            alias_id = index["district_aliases"].get(district_key)
            district = index["district_by_id"].get(alias_id)
        if not district:
            district = next(
                (
                    candidate
                    for candidate in index["districts"]
                    if district_key in _lookup_key(candidate.name)
                ),
                None,
            )

    ambiguous_district_names: list[str] = []
    if not district and sub_county_key:
        matches = list(index["sub_county_exact"].get(sub_county_key, []))
        if not matches:
            matches = [
                candidate
                for candidate in index["sub_counties"]
                if sub_county_key in _lookup_key(candidate.name)
            ]
        districts_by_id = {m.district_id: m.district for m in matches}
        if len(districts_by_id) == 1:
            district = next(iter(districts_by_id.values()))
        elif len(districts_by_id) > 1:
            ambiguous_district_names = sorted(d.name for d in districts_by_id.values())

    sub_county = None
    if sub_county_key and district:
        candidates = index["sub_counties_by_district"].get(district.id, [])
        sub_county = next(
            (
                candidate
                for candidate in candidates
                if _lookup_key(candidate.name) == sub_county_key
            ),
            None,
        )
        if not sub_county:
            sub_county = next(
                (
                    candidate
                    for candidate in candidates
                    if sub_county_key in _lookup_key(candidate.name)
                ),
                None,
            )

    return district, sub_county, ambiguous_district_names


def _build_staff_index() -> dict[str, list]:
    """Map normalized field-staff names to profiles with one query."""
    from apps.accounts.models import StaffProfile
    from apps.accounts.staff_matching import _is_field_staff, normalize_name

    index: dict[str, list] = defaultdict(list)
    profiles = StaffProfile.objects.select_related("user").filter(
        deleted_at__isnull=True,
        user__is_active=True,
    )
    for profile in profiles:
        if _is_field_staff(profile):
            index[normalize_name(profile.user.name)].append(profile)
    return index


def _match_staff_from_index(name: str | None, index: dict[str, list]):
    from apps.accounts.staff_matching import normalize_name

    if not (name or "").strip():
        return None, "pending"
    candidates = index.get(normalize_name(name), [])
    if len(candidates) == 1:
        return candidates[0].id, "matched"
    if len(candidates) > 1:
        return None, "ambiguous"
    return None, "unmatched"


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
        # The parser's own message can name a temporary path or a library
        # internal. What the person uploading needs is that the file could not
        # be read; the detail belongs in the log.
        logger.warning("XLSX parse failed", exc_info=exc)
        raise BadRequest(
            "Could not read the XLSX file. Check it opens in a spreadsheet "
            "application and is not password-protected."
        ) from exc
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


# ── Main entry ───────────────────────────────────────────────────────────────
def upload_school_file(file, principal, update_existing: bool = False) -> dict:
    """Parse + validate + stage a school onboarding file. Returns the staging
    response contract. Raises BadRequest (→ 400) on file/header errors."""
    from apps.schools.models import SchoolImportBatch, SchoolImportRow, School

    started_at = time.perf_counter()
    raw_headers, data_rows = _read_rows(file)
    if not raw_headers:
        raise BadRequest("The uploaded file is empty — no header row found.")

    field_index = M.build_field_index(raw_headers, M.SCHOOL_HEADER_MAP)
    missing = M.missing_required(field_index, M.SCHOOL_REQUIRED_FIELDS)
    if missing:
        label = {
            "school_id": "School ID",
            "name": "School Name",
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
    geography_index = _build_geography_index()
    uploaded_school_ids = {
        _value(field_index, "school_id", cells)
        for _row_number, cells in data_rows
        if _value(field_index, "school_id", cells)
    }
    existing_by_id = School.objects.filter(
        school_id__in=uploaded_school_ids,
        deleted_at__isnull=True,
    ).in_bulk(field_name="school_id")
    existing_name_keys = {
        _lookup_key(name)
        for name in School.objects.filter(deleted_at__isnull=True).values_list(
            "name", flat=True
        )
    }
    staff_index = _build_staff_index()
    accepted_school_ids: set[str] = set()

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

        # Geography is optional during intake. Resolve it when supplied, but
        # preserve unmatched text as a non-blocking warning so the school can
        # still be created and corrected from its profile.
        district, _sub_county_preview, ambiguous_district_names = _resolve_geography(
            district_name,
            sub_county_name,
            index=geography_index,
        )

        if not district_name and not sub_county_name:
            validation_errors.append(
                "District not provided; complete it in the School Profile"
            )
        elif district_name and not district:
            validation_errors.append(f"District '{district_name}' could not be matched")
        elif not district_name and ambiguous_district_names:
            validation_errors.append(
                f"Sub-county '{sub_county_name}' exists in multiple districts "
                f"({', '.join(ambiguous_district_names)}); complete the location "
                "in the School Profile."
            )
        elif not district_name and sub_county_name and not district:
            validation_errors.append(
                f"Sub-county '{sub_county_name}' could not be matched to any "
                "district; complete the location in the School Profile."
            )

        # C. Non-blocking warnings / updates
        if status != "blocked":
            if school_id_raw in accepted_school_ids:
                status = "duplicate"
                counts["duplicate"] += 1
                validation_errors.append(
                    f"Duplicate School ID '{school_id_raw}' within this file"
                )
            elif school_id_raw in existing_by_id:
                if update_existing:
                    status = "update"
                    counts["updated"] += 1
                else:
                    status = "duplicate"
                    counts["duplicate"] += 1
            else:
                # Check for potential duplicates by name in DB
                if _lookup_key(name) in existing_name_keys:
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
                owner_id, owner_status = _match_staff_from_index(
                    account_owner_name, staff_index
                )
                if owner_status in staff_counts:
                    staff_counts[owner_status] += 1

            # Check optional gaps for Needs Review / Warnings
            if not phone:
                validation_errors.append("Missing phone number")
            if not contact_person:
                validation_errors.append("Missing contact person")
            if not enrollment_raw:
                validation_errors.append("Missing enrollment")

            if status in ("ready", "update"):
                accepted_school_ids.add(school_id_raw)

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
            logger.error("School import failed", exc_info=exc)
            raise BadRequest(
                "School import failed. The batch is marked failed and the "
                "reason has been recorded for support."
            ) from exc
        legacy_batch.status = "imported"
        legacy_batch.save(update_fields=["status", "updated_at"])

    message = _build_message(success, counts, len(data_rows))
    processing_seconds = round(time.perf_counter() - started_at, 3)
    logger.info(
        "School upload completed batch=%s rows=%s created=%s updated=%s "
        "failed=%s duration_seconds=%s",
        batch.id,
        len(data_rows),
        counts["created"],
        counts["updated"],
        counts["failed"],
        processing_seconds,
    )
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
        "processing_seconds": processing_seconds,
    }


def _active_cluster_index() -> dict[str, object]:
    """Return the first active cluster for each covered sub-county."""
    from apps.clusters.models import Cluster

    index = {}
    clusters = (
        Cluster.objects.filter(deleted_at__isnull=True, status="active")
        .prefetch_related("covered_sub_counties")
        .order_by("name", "id")
    )
    for cluster in clusters:
        if cluster.sub_county_id:
            index.setdefault(cluster.sub_county_id, cluster)
        for coverage in cluster.covered_sub_counties.all():
            index.setdefault(coverage.sub_county_id, cluster)
    return index


def _bulk_refresh_quality_issues(schools) -> None:
    from apps.schools.models import (
        DataQualityIssue,
        build_data_quality_issues,
    )

    schools = list(schools)
    if not schools:
        return
    school_ids = [school.id for school in schools]
    DataQualityIssue.objects.filter(
        school_id__in=school_ids,
        status="open",
    ).delete()
    issues = [
        issue for school in schools for issue in build_data_quality_issues(school)
    ]
    if issues:
        DataQualityIssue.objects.bulk_create(issues, batch_size=1000)


def _bulk_upsert_staff_candidates(
    grouped_schools: dict[str, tuple[str, list[str]]],
    batch_id: str,
) -> None:
    if not grouped_schools:
        return

    from apps.accounts.models import StaffSetupCandidate

    existing = {
        candidate.normalized_name: candidate
        for candidate in StaffSetupCandidate.objects.select_for_update().filter(
            normalized_name__in=grouped_schools
        )
    }
    to_create = []
    to_update = []
    for normalized_name, (full_name, school_ids) in grouped_schools.items():
        unique_school_ids = list(dict.fromkeys(school_ids))
        candidate = existing.get(normalized_name)
        if candidate is None:
            to_create.append(
                StaffSetupCandidate(
                    normalized_name=normalized_name,
                    full_name=full_name,
                    source_upload_batch=batch_id,
                    school_count=len(unique_school_ids),
                    sample_school_ids=unique_school_ids[:20],
                )
            )
            continue
        candidate.school_count = (candidate.school_count or 0) + len(unique_school_ids)
        candidate.sample_school_ids = list(
            dict.fromkeys(list(candidate.sample_school_ids or []) + unique_school_ids)
        )[:20]
        if not candidate.source_upload_batch:
            candidate.source_upload_batch = batch_id
        to_update.append(candidate)

    if to_create:
        StaffSetupCandidate.objects.bulk_create(
            to_create,
            batch_size=500,
            ignore_conflicts=True,
        )
    if to_update:
        StaffSetupCandidate.objects.bulk_update(
            to_update,
            ["school_count", "sample_school_ids", "source_upload_batch"],
            batch_size=500,
        )


def import_school_batch(batch, user) -> dict:
    from apps.schools.models import (
        School,
        SchoolChangeLog,
        UploadBatch,
        SchoolImportBatch,
    )
    from apps.accounts.staff_matching import normalize_name
    from apps.accounts.models import StaffProfile, StaffSchoolAssignment
    from apps.clusters.models import SchoolClusterAssignment

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
    rows = list(batch.rows.exclude(status__in=["blocked", "duplicate"]))
    created_count = 0
    updated_count = 0
    clean_count = 0
    review_count = 0
    cleanup_count = 0
    duplicate_count = 0

    geography_index = _build_geography_index()
    cluster_by_sub_county = _active_cluster_index()
    existing_by_id = School.objects.filter(
        school_id__in=[row.school_id for row in rows],
        deleted_at__isnull=True,
    ).in_bulk(field_name="school_id")

    with transaction.atomic():
        # Resolve each distinct owner once. Unknown names retain the existing
        # behavior of creating one pending CCEO profile, but never repeat that
        # user/profile/candidate work for every school carrying the same name.
        owner_names = {
            normalize_name(row.account_owner_name): row.account_owner_name
            for row in rows
            if normalize_name(row.account_owner_name)
        }
        staff_index = _build_staff_index()
        owner_results = {}
        for normalized_name, display_name in owner_names.items():
            owner_id, owner_status = _match_staff_from_index(display_name, staff_index)
            if owner_status == "unmatched":
                owner_id = _auto_create_user_from_upload(display_name)
                if owner_id:
                    owner_status = "matched"
            owner_results[normalized_name] = (owner_id, owner_status)

        new_schools = []
        new_cluster_assignments = []
        new_staff_assignments = []
        candidate_groups: dict[str, tuple[str, list[str]]] = {}
        changed_by = user.user_id if hasattr(user, "user_id") else str(user or "system")

        for r in rows:
            # Same resolution the staging/validation phase used (including
            # the sub-county-infers-district fallback) — using independent
            # logic here previously meant a row that passed validation could
            # still land on a different (or, when district_name was blank,
            # an arbitrary alphabetically-first) District at import time.
            district, sub_county, _ambiguous = _resolve_geography(
                r.district_name,
                r.sub_county_name,
                index=geography_index,
            )
            # Unmatched optional geography is deliberately left null. The raw
            # uploaded text is preserved below for correction in the profile.

            owner_id = None
            owner_status = "pending"
            if r.account_owner_name:
                owner_id, owner_status = owner_results.get(
                    normalize_name(r.account_owner_name),
                    (None, "unmatched"),
                )

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

            existing = existing_by_id.get(r.school_id)

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
                                    changed_by=changed_by,
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
                # A school may enter the directory with only its official ID
                # and name. Missing/unmatched geography remains null and its
                # uploaded text is retained for profile completion—never
                # replaced by an arbitrary district.
                cluster = (
                    cluster_by_sub_county.get(sub_county.id)
                    if sub_county is not None
                    else None
                )
                # A school only ever joins a cluster in its own district.
                # The sub-county index gets there transitively — a cluster's
                # covered sub-counties are constrained to its district when it
                # is created — but an upload writes `cluster_id` straight onto
                # the row, bypassing `set_school_cluster_membership` where that
                # rule is enforced. Checking it here makes the guarantee direct
                # rather than inherited from an invariant two models away.
                if cluster and district and cluster.district_id != district.id:
                    cluster = None
                saved_school = School(
                    school_id=r.school_id,
                    name=r.name,
                    school_type=school_type,
                    region=district.region if district else None,
                    district=district,
                    sub_county=sub_county,
                    uploaded_district_text=r.district_name or None,
                    uploaded_sub_county_text=r.sub_county_name or None,
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
                    cluster_id=cluster.id if cluster else None,
                    cluster_status="clustered" if cluster else "unclustered",
                )
                saved_school.recompute_quality_and_readiness()
                new_schools.append(saved_school)
                if cluster:
                    new_cluster_assignments.append(
                        SchoolClusterAssignment(
                            school=saved_school,
                            cluster=cluster,
                            assigned_by="system_reassign",
                        )
                    )
                if owner_id and owner_status == "matched":
                    new_staff_assignments.append(
                        StaffSchoolAssignment(
                            staff_id=owner_id,
                            school_id=saved_school.id,
                        )
                    )
                created_count += 1

            if existing and owner_id and owner_status == "matched":
                StaffSchoolAssignment.objects.get_or_create(
                    staff_id=owner_id,
                    school_id=saved_school.id,
                )

            q_status = saved_school.data_quality_status
            if q_status == "Clean":
                clean_count += 1
            elif q_status == "Needs Review":
                review_count += 1
            elif q_status == "Needs Cleanup":
                cleanup_count += 1
            elif q_status == "Duplicate Risk":
                duplicate_count += 1

        if new_schools:
            School.objects.bulk_create(new_schools, batch_size=1000)
            _bulk_refresh_quality_issues(new_schools)
        new_by_school_id = {school.school_id: school for school in new_schools}
        if new_cluster_assignments:
            SchoolClusterAssignment.objects.bulk_create(
                new_cluster_assignments,
                batch_size=1000,
                ignore_conflicts=True,
            )
        if new_staff_assignments:
            StaffSchoolAssignment.objects.bulk_create(
                new_staff_assignments,
                batch_size=1000,
                ignore_conflicts=True,
            )

        matched_owner_ids = {
            owner_id
            for owner_id, status in owner_results.values()
            if owner_id and status == "matched"
        }
        pending_owner_ids = {
            profile.id
            for profile in StaffProfile.objects.filter(
                id__in=matched_owner_ids
            ).select_related("user")
            if profile.user
            and (
                "pending." in profile.user.email
                or profile.user.status == "pending_invited"
            )
        }
        for r in rows:
            if not r.account_owner_name:
                continue
            normalized_name = normalize_name(r.account_owner_name)
            owner_id, owner_status = owner_results.get(
                normalized_name,
                (None, "unmatched"),
            )
            if owner_status not in ("unmatched", "ambiguous") and (
                owner_id not in pending_owner_ids
            ):
                continue
            school = existing_by_id.get(r.school_id) or new_by_school_id.get(
                r.school_id
            )
            if school is None:
                continue
            if normalized_name not in candidate_groups:
                candidate_groups[normalized_name] = (
                    r.account_owner_name,
                    [],
                )
            candidate_groups[normalized_name][1].append(school.id)
        _bulk_upsert_staff_candidates(candidate_groups, batch.id)

        batch.status = "imported"
        batch.save(update_fields=["status", "updated_at"])

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


def act_on_upload_batch(batch_id: str, action: str, principal, *, reason: str = ""):
    """Validate, reject, or import a persisted upload batch under one lock."""
    from apps.core.scoping import resolve_user_scope
    from apps.schools.models import UploadBatch

    with transaction.atomic():
        batch = UploadBatch.objects.select_for_update().filter(id=batch_id).first()
        scope = resolve_user_scope(principal)
        if not batch or (
            not scope.country_scope and batch.uploaded_by != principal.user_id
        ):
            from apps.core.exceptions import NotFoundError

            raise NotFoundError("Upload batch not found.")

        if action == "validate":
            if batch.status != "uploaded":
                raise BadRequest("Batch must be in 'uploaded' status to validate.")
            has_failures = batch.row_results.filter(status="failed").exists()
            batch.status = "completed_with_errors" if has_failures else "validated"
            batch.save(update_fields=["status", "updated_at"])
        elif action == "reject":
            if batch.status in {"imported", "rejected"}:
                raise BadRequest(f"An {batch.status} batch cannot be rejected.")
            batch.status = "rejected"
            if reason:
                batch.error_summary = reason
            batch.save(update_fields=["status", "error_summary", "updated_at"])
        elif action == "import":
            if batch.status == "imported":
                return batch
            if batch.status not in {
                "validated",
                "completed_with_errors",
                "uploaded",
            }:
                raise BadRequest("Batch must be validated to import.")
            if batch.upload_type == "schools":
                import_school_batch(batch, principal)
            elif batch.upload_type == "ssa":
                from apps.ssa.upload_service import import_ssa_batch

                import_ssa_batch(batch, principal)
            else:
                raise BadRequest("Unsupported upload type.")
            batch.status = "imported"
            batch.save(update_fields=["status", "updated_at"])
        else:
            raise BadRequest("Invalid action.")
    return batch


def cancel_school_import_batch(batch_id: str, principal):
    """Cancel an unimported school staging batch."""
    from apps.schools.models import SchoolImportBatch

    with transaction.atomic():
        batch = (
            SchoolImportBatch.objects.select_for_update().filter(id=batch_id).first()
        )
        if not batch:
            from apps.core.exceptions import NotFoundError

            raise NotFoundError("School import batch not found.")
        if batch.status != "staged":
            raise BadRequest(f"This batch is already {batch.status}.")
        batch.status = "cancelled"
        batch.save(update_fields=["status", "updated_at"])
    return batch


def mark_upload_batch_inactive(batch_id: str, principal):
    """Mark history as failed/cancelled without pretending to revert its rows."""
    from apps.schools.models import SchoolImportBatch, SSAImportBatch, UploadBatch

    with transaction.atomic():
        batch = (
            SchoolImportBatch.objects.select_for_update().filter(id=batch_id).first()
            or SSAImportBatch.objects.select_for_update().filter(id=batch_id).first()
            or UploadBatch.objects.select_for_update().filter(id=batch_id).first()
        )
        if not batch:
            return None
        if isinstance(batch, UploadBatch):
            batch.status = "failed"
        else:
            batch.status = "cancelled"
        batch.save(update_fields=["status", "updated_at"])

        from apps.audit.services import log as audit_log

        audit_log(
            action="school_upload.batch_marked_inactive",
            subject_kind=type(batch).__name__,
            subject_id=batch.id,
            actor_id=principal.id,
            actor_role=getattr(principal, "active_role", None),
            payload={"status": batch.status},
        )
    return batch


__all__ = [
    "upload_school_file",
    "import_school_batch",
    "act_on_upload_batch",
    "cancel_school_import_batch",
    "mark_upload_batch_inactive",
]
